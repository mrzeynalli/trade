"""Ingestion orchestration.

Turns a user-level intent ("cache Azerbaijan") into the smallest set of
Comtrade requests that satisfies it, normalises the result, validates it and
writes it to Parquet atomically.

Batching facts verified against the live service:
  * 12 periods per request is the hard maximum;
  * omitting ``partnerCode`` returns every partner *and* the World aggregate in
    one response, so partner totals and country totals cost one call together;
  * omitting ``reporterCode`` returns every reporter, so a whole year of the
    global HS2 matrix costs one call per flow;
  * a response is silently truncated at 100000 records, so a result at the cap
    is subdivided deterministically and recombined locally.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable, Sequence

import polars as pl

from . import etl, state
from .comtrade import ComtradeClient, ComtradeError, FetchResult
from .config import get_settings
from .logging_setup import get_logger
from .refs import load_hs

log = get_logger("trade.ingest")

DATA_ENDPOINT = "/data/v1/get/C/{freq}/HS"
AVAIL_ENDPOINT = "/data/v1/getDa/C/{freq}/HS"
LIVE_ENDPOINT = "/data/v1/getLiveUpdate"

BASE_PARAMS = {"partner2Code": 0, "customsCode": "C00", "motCode": 0}


@dataclass
class IngestResult:
    dataset: str
    scope: str
    rows: int
    calls: int
    truncated_segments: int = 0
    issues: list[str] = field(default_factory=list)
    reconciliation: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Period helpers
# --------------------------------------------------------------------------

def annual_periods(start: int, end: int) -> list[str]:
    return [str(y) for y in range(start, end + 1)]


def monthly_periods(count: int, *, end: str | None = None) -> list[str]:
    """The ``count`` most recent months up to and including ``end`` (YYYYMM)."""
    if end and len(end) == 6 and end.isdigit():
        year, month = int(end[:4]), int(end[4:])
    else:
        today = date.today()
        year, month = today.year, today.month
    periods: list[str] = []
    for _ in range(count):
        periods.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return sorted(periods)


def chunk(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i:i + size]) for i in range(0, len(items), size)]


# --------------------------------------------------------------------------
# Fetch with deterministic subdivision
# --------------------------------------------------------------------------

def _hs_codes_at_level(level: int) -> list[str]:
    frame = load_hs().filter(pl.col("level") == level)
    return sorted(frame["hs_code"].to_list())


def fetch_segments(
    client: ComtradeClient,
    freq: str,
    params: dict[str, Any],
    periods: Sequence[str],
    *,
    priority: str = "normal",
    force: bool = False,
    request_type: str = "data",
) -> tuple[list[dict[str, Any]], int, int]:
    """Fetch ``periods`` for ``params``, subdividing whenever a response is
    returned at the record cap. Returns (rows, api_calls, truncated_segments)."""
    settings = get_settings()
    endpoint = DATA_ENDPOINT.format(freq=freq)
    rows: list[dict[str, Any]] = []
    calls = 0
    truncated = 0

    queue: list[tuple[list[str], dict[str, Any]]] = [
        (batch, dict(params)) for batch in chunk(list(periods), settings.max_periods_per_request)
    ]

    while queue:
        batch_periods, batch_params = queue.pop(0)
        request = {**BASE_PARAMS, **batch_params, "period": ",".join(batch_periods), "_freq": freq}
        result: FetchResult = client.fetch(
            endpoint, request, request_type=request_type, priority=priority, force=force
        )
        calls += 0 if result.from_cache else 1
        if not result.truncated:
            rows.extend(result.rows)
            continue

        truncated += 1
        children = _subdivide(batch_periods, batch_params)
        if children is None:
            # Cannot split further: keep what came back but flag it loudly.
            rows.extend(result.rows)
            state.record_error(
                "truncation",
                f"Irreducible truncated segment: {batch_params} periods={batch_periods}",
            )
            log.warning("irreducible truncation", extra={"params": str(batch_params),
                                                        "periods": batch_periods})
            continue
        queue = children + queue

    return rows, calls, truncated


def _subdivide(periods: list[str], params: dict[str, Any]) -> list[tuple[list[str], dict[str, Any]]] | None:
    """Deterministic split order: periods, then flows, then commodity codes."""
    if len(periods) > 1:
        middle = len(periods) // 2
        return [(periods[:middle], dict(params)), (periods[middle:], dict(params))]

    flows = str(params.get("flowCode", "")).split(",")
    if len(flows) > 1:
        return [
            (list(periods), {**params, "flowCode": flow}) for flow in sorted(flows)
        ]

    cmd = str(params.get("cmdCode", "TOTAL"))
    if cmd.startswith("AG"):
        level = int(cmd[2:])
        codes = _hs_codes_at_level(level)
        if len(codes) > 1:
            middle = len(codes) // 2
            return [
                (list(periods), {**params, "cmdCode": ",".join(codes[:middle])}),
                (list(periods), {**params, "cmdCode": ",".join(codes[middle:])}),
            ]
    elif "," in cmd:
        codes = cmd.split(",")
        middle = len(codes) // 2
        return [
            (list(periods), {**params, "cmdCode": ",".join(codes[:middle])}),
            (list(periods), {**params, "cmdCode": ",".join(codes[middle:])}),
        ]

    reporters = str(params.get("reporterCode", "")).split(",")
    if len(reporters) > 1 and reporters != [""]:
        middle = len(reporters) // 2
        return [
            (list(periods), {**params, "reporterCode": ",".join(reporters[:middle])}),
            (list(periods), {**params, "reporterCode": ",".join(reporters[middle:])}),
        ]
    return None


# --------------------------------------------------------------------------
# Availability / invalidation
# --------------------------------------------------------------------------

def sync_availability(client: ComtradeClient, reporter: int, freq: str,
                      priority: str = "normal") -> dict[str, Any]:
    """Record what the source says exists for a reporter, and which local
    partitions that makes stale."""
    result = client.fetch(
        AVAIL_ENDPOINT.format(freq=freq),
        {"reporterCode": reporter, "_freq": freq},
        request_type="availability", priority=priority, force=True,
    )
    changed: list[int] = []
    conn = state.get_conn()
    for row in result.rows:
        dataset_code = str(row.get("datasetCode"))
        checksum = str(row.get("datasetChecksum"))
        last_released = row.get("lastReleased")
        existing = conn.execute(
            "SELECT checksum, last_released FROM sync_state WHERE dataset_code = ?",
            (dataset_code,),
        ).fetchone()
        if existing is None or existing["checksum"] != checksum or existing["last_released"] != last_released:
            changed.append(int(row.get("period")))
        conn.execute(
            """INSERT INTO sync_state(dataset_code, type_code, freq_code, reporter_code, period,
                                      classification, total_records, checksum, first_released,
                                      last_released, seen_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(dataset_code) DO UPDATE SET
                 total_records=excluded.total_records, checksum=excluded.checksum,
                 first_released=excluded.first_released, last_released=excluded.last_released,
                 seen_at=excluded.seen_at""",
            (
                dataset_code, row.get("typeCode"), row.get("freqCode"),
                int(row.get("reporterCode")), int(row.get("period")),
                row.get("classificationCode"), row.get("totalRecords"), checksum,
                row.get("firstReleased"), row.get("lastReleased"), state.utcnow(),
            ),
        )
    periods = sorted({int(r.get("period")) for r in result.rows if r.get("period") is not None})
    return {"periods": periods, "changed": sorted(changed), "calls": 0 if result.from_cache else 1}


def live_updates(client: ComtradeClient) -> list[dict[str, Any]]:
    """Recently published datasets, newest first."""
    result = client.fetch(LIVE_ENDPOINT, {}, request_type="live_update",
                          priority="normal", force=True)
    return result.rows


# --------------------------------------------------------------------------
# Country packs
# --------------------------------------------------------------------------

def ingest_country_totals_and_partners(
    client: ComtradeClient, reporter: int, freq: str, periods: Sequence[str],
    *, priority: str = "normal", force: bool = False,
) -> list[IngestResult]:
    """One request family yields both reporter-World totals and per-partner
    totals, because the World aggregate arrives in the same response."""
    rows, calls, truncated = fetch_segments(
        client, freq,
        {"reporterCode": reporter, "cmdCode": "TOTAL", "flowCode": "X,M"},
        periods, priority=priority, force=force,
    )
    frame = etl.normalise_rows(rows)
    results: list[IngestResult] = []

    world = frame.filter(pl.col("partner_code") == 0)
    bilateral = frame.filter((pl.col("partner_code") > 0))

    replace = _replace_scope(freq, periods)

    report = etl.validate_facts("totals", world, scope=f"{reporter}/{freq}", expect_partner="world")
    _, total_rows = etl.merge_into_partition(
        "totals", world.drop("partner_code") if "partner_code" in world.columns else world,
        freq=freq, reporter=reporter, replace_scope=replace,
    )
    state.bump_dataset_version("totals", etl.scope_name(reporter, freq), total_rows)
    results.append(IngestResult("totals", etl.scope_name(reporter, freq), total_rows,
                                calls, truncated, report.issues))

    report = etl.validate_facts("partners", bilateral, scope=f"{reporter}/{freq}",
                                expect_partner="bilateral")
    _, partner_rows = etl.merge_into_partition(
        "partners", bilateral, freq=freq, reporter=reporter, replace_scope=replace,
    )
    reconciliation = _reconcile_partners(world, bilateral)
    state.bump_dataset_version("partners", etl.scope_name(reporter, freq), partner_rows,
                               coverage=reconciliation)
    results.append(IngestResult("partners", etl.scope_name(reporter, freq), partner_rows,
                                0, 0, report.issues, reconciliation))
    return results


def ingest_country_products(
    client: ComtradeClient, reporter: int, freq: str, periods: Sequence[str],
    *, level: int = 2, priority: str = "normal", force: bool = False,
) -> IngestResult:
    """Reporter-to-World product composition at HS2 or HS4."""
    dataset = "products_hs2" if level == 2 else "products_hs4"
    rows, calls, truncated = fetch_segments(
        client, freq,
        {"reporterCode": reporter, "cmdCode": f"AG{level}", "flowCode": "X,M", "partnerCode": 0},
        periods, priority=priority, force=force,
    )
    frame = etl.normalise_rows(rows).filter(pl.col("hs_level") == level)
    report = etl.validate_facts(dataset, frame, scope=f"{reporter}/{freq}", expect_partner="world")
    frame = frame.drop("partner_code") if "partner_code" in frame.columns else frame
    _, written = etl.merge_into_partition(
        dataset, frame, freq=freq, reporter=reporter, replace_scope=_replace_scope(freq, periods)
    )
    reconciliation = _reconcile_products(reporter, freq, periods, level)
    state.bump_dataset_version(dataset, etl.scope_name(reporter, freq), written,
                               coverage=reconciliation)
    return IngestResult(dataset, etl.scope_name(reporter, freq), written, calls,
                        truncated, report.issues, reconciliation)


def ingest_product_partners(
    client: ComtradeClient, reporter: int, freq: str, hs_code: str, periods: Sequence[str],
    *, priority: str = "interactive", force: bool = False,
) -> IngestResult:
    """Partner breakdown for one HS2 chapter. Lazy: only fetched on drilldown."""
    rows, calls, truncated = fetch_segments(
        client, freq,
        {"reporterCode": reporter, "cmdCode": hs_code, "flowCode": "X,M"},
        periods, priority=priority, force=force,
    )
    frame = etl.normalise_rows(rows).filter(
        (pl.col("hs_code") == hs_code) & (pl.col("partner_code") > 0)
    )
    report = etl.validate_facts("product_partner", frame, scope=f"{reporter}/{hs_code}",
                                expect_partner="bilateral")
    _, written = etl.merge_into_partition(
        "product_partner", frame, freq=freq, reporter=reporter, extra={"hs": hs_code},
        replace_scope=_replace_scope(freq, periods),
    )
    scope = etl.scope_name(reporter, freq, {"hs": hs_code})
    state.bump_dataset_version("product_partner", scope, written)
    return IngestResult("product_partner", scope, written, calls, truncated, report.issues)


def ingest_partner_products(
    client: ComtradeClient, reporter: int, freq: str, partner: int, periods: Sequence[str],
    *, priority: str = "interactive", force: bool = False,
) -> IngestResult:
    """HS2 composition of one bilateral relationship."""
    rows, calls, truncated = fetch_segments(
        client, freq,
        {"reporterCode": reporter, "cmdCode": "AG2", "flowCode": "X,M", "partnerCode": partner},
        periods, priority=priority, force=force,
    )
    frame = etl.normalise_rows(rows).filter(
        (pl.col("hs_level") == 2) & (pl.col("partner_code") == partner)
    )
    report = etl.validate_facts("partner_products", frame, scope=f"{reporter}/{partner}",
                                expect_partner="bilateral")
    _, written = etl.merge_into_partition(
        "partner_products", frame, freq=freq, reporter=reporter,
        extra={"partner": f"{partner:03d}"}, replace_scope=_replace_scope(freq, periods),
    )
    scope = etl.scope_name(reporter, freq, {"partner": f"{partner:03d}"})
    state.bump_dataset_version("partner_products", scope, written)
    return IngestResult("partner_products", scope, written, calls, truncated, report.issues)


def ingest_mirror(
    client: ComtradeClient, mirror_reporter: int, counterpart: int, freq: str,
    periods: Sequence[str], *, priority: str = "interactive", force: bool = False,
) -> IngestResult:
    """Fetch the counterpart's own reporting of the same relationship."""
    rows, calls, truncated = fetch_segments(
        client, freq,
        {"reporterCode": mirror_reporter, "cmdCode": "TOTAL", "flowCode": "X,M",
         "partnerCode": counterpart},
        periods, priority=priority, force=force,
    )
    frame = etl.normalise_rows(rows).filter(pl.col("partner_code") == counterpart)
    _, written = etl.merge_into_partition(
        "partners", frame, freq=freq, reporter=mirror_reporter,
        replace_scope=None,
    )
    scope = etl.scope_name(mirror_reporter, freq)
    state.bump_dataset_version("partners", scope, written)
    return IngestResult("partners", scope, written, calls, truncated)


def ingest_global_hs2(
    client: ComtradeClient, year: int, *, flows: Sequence[str] = ("X", "M"),
    priority: str = "backfill", force: bool = False,
) -> IngestResult:
    """The whole reported world HS2 matrix for one year.

    One call per flow: ``reporterCode`` is omitted, which the service reads as
    "every reporter" (about 165 reporters x 97 chapters = ~15k records, far
    inside the record cap)."""
    all_rows: list[dict[str, Any]] = []
    calls = 0
    truncated = 0
    for flow in flows:
        rows, made, trunc = fetch_segments(
            client, "A",
            {"cmdCode": "AG2", "flowCode": flow, "partnerCode": 0},
            [str(year)], priority=priority, force=force, request_type="global",
        )
        all_rows.extend(rows)
        calls += made
        truncated += trunc

    frame = etl.normalise_rows(all_rows).filter(pl.col("hs_level") == 2)
    if "partner_code" in frame.columns:
        frame = frame.filter(pl.col("partner_code") == 0).drop("partner_code")
    if "month" in frame.columns:
        frame = frame.drop("month")
    reporters = frame["reporter_code"].n_unique() if frame.height else 0
    _, written = etl.merge_into_partition(
        "global_hs2", frame, freq="", reporter=None, extra={"year": str(year)},
        replace_scope=[("year", [year])],
    )
    coverage = {
        "reporters_included": int(reporters),
        "coverage_note": "Reported coverage only: reporters that had not published "
                         "for this period are absent from the denominator.",
    }
    state.bump_dataset_version("global_hs2", f"year={year}", written, coverage=coverage)
    return IngestResult("global_hs2", f"year={year}", written, calls, truncated,
                        [], coverage)


# --------------------------------------------------------------------------
# Reconciliation helpers
# --------------------------------------------------------------------------

def _replace_scope(freq: str, periods: Sequence[str]) -> list[tuple[str, list[Any]]]:
    if freq == "A":
        return [("year", [int(p) for p in periods])]
    return [("year", sorted({int(p[:4]) for p in periods})),
            ("month", sorted({int(p[4:]) for p in periods}))]


def _reconcile_partners(world: pl.DataFrame, bilateral: pl.DataFrame) -> dict[str, Any]:
    """Sum of individual partners versus the reported World figure."""
    if world.height == 0 or bilateral.height == 0:
        return {}
    latest = int(world["year"].max())
    out: dict[str, Any] = {"reconciliation_year": latest}
    for flow in ("X", "M"):
        reported = world.filter((pl.col("year") == latest) & (pl.col("flow_code") == flow))
        summed = bilateral.filter((pl.col("year") == latest) & (pl.col("flow_code") == flow))
        reported_value = float(reported["primary_value"].sum()) if reported.height else None
        summed_value = float(summed["primary_value"].sum()) if summed.height else None
        out[f"partner_sum_vs_world_{flow}"] = etl.reconcile_components(summed_value, reported_value)
    return out


def _reconcile_products(reporter: int, freq: str, periods: Sequence[str], level: int) -> dict[str, Any]:
    """HS aggregate sum versus the reported TOTAL, recorded not enforced."""
    from . import store

    if freq != "A" or not periods:
        return {}
    year = max(int(p) for p in periods)
    totals = {row["year"]: row for row in store.totals_series(reporter, freq, start=year, end=year)}
    reference = totals.get(year)
    if reference is None:
        return {}
    ranking_x = store.product_ranking(reporter, freq, [str(year)], "X", level=level, top_n=10_000)
    ranking_m = store.product_ranking(reporter, freq, [str(year)], "M", level=level, top_n=10_000)
    return {
        "reconciliation_year": year,
        f"hs{level}_sum_vs_total_X": etl.reconcile_components(ranking_x["total"], reference["exports"]),
        f"hs{level}_sum_vs_total_M": etl.reconcile_components(ranking_m["total"], reference["imports"]),
    }


# --------------------------------------------------------------------------
# High-level packs
# --------------------------------------------------------------------------

def latest_complete_year(client: ComtradeClient, reporter: int,
                         priority: str = "normal") -> tuple[int, list[int]]:
    """Ask the source which annual datasets exist for this reporter."""
    availability = sync_availability(client, reporter, "A", priority=priority)
    periods = availability["periods"]
    if not periods:
        return date.today().year - 1, []
    current = date.today().year
    complete = [p for p in periods if p < current]
    return (max(complete) if complete else max(periods)), periods


def country_annual_pack(
    client: ComtradeClient, reporter: int, *, start_year: int | None = None,
    end_year: int | None = None, priority: str = "normal", force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[IngestResult]:
    settings = get_settings()
    start = start_year or settings.annual_history_start
    if end_year is None:
        end_year, available = latest_complete_year(client, reporter, priority=priority)
        if available:
            end_year = max(available)
    periods = [p for p in annual_periods(start, end_year)]
    results: list[IngestResult] = []

    if progress:
        progress("Fetching annual totals and partner breakdown")
    results.extend(ingest_country_totals_and_partners(
        client, reporter, "A", periods, priority=priority, force=force))

    if progress:
        progress("Fetching annual product composition")
    results.append(ingest_country_products(
        client, reporter, "A", periods, level=2, priority=priority, force=force))
    return results


def country_monthly_pack(
    client: ComtradeClient, reporter: int, *, months: int | None = None,
    priority: str = "normal", force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> list[IngestResult]:
    settings = get_settings()
    availability = sync_availability(client, reporter, "M", priority=priority)
    available = availability["periods"]
    count = months or settings.monthly_history_months
    if available:
        latest = str(max(available))
        periods = [p for p in monthly_periods(count, end=latest) if int(p) in set(available)]
    else:
        periods = monthly_periods(count)
    if not periods:
        return []

    results: list[IngestResult] = []
    if progress:
        progress("Fetching monthly totals and partner breakdown")
    results.extend(ingest_country_totals_and_partners(
        client, reporter, "M", periods, priority=priority, force=force))
    if progress:
        progress("Fetching monthly product composition")
    results.append(ingest_country_products(
        client, reporter, "M", periods, level=2, priority=priority, force=force))
    return results


def country_hs4_pack(
    client: ComtradeClient, reporter: int, *, start_year: int | None = None,
    end_year: int | None = None, priority: str = "interactive", force: bool = False,
) -> IngestResult:
    """HS4 for every chapter at once — one request family covers all drilldowns."""
    from . import store

    settings = get_settings()
    start = start_year or max(settings.annual_history_start, date.today().year - 11)
    if end_year is None:
        latest = store.latest_period(reporter, "A")
        end_year = (latest or {}).get("latest") or date.today().year - 1
    periods = annual_periods(start, end_year)
    return ingest_country_products(client, reporter, "A", periods, level=4,
                                   priority=priority, force=force)


# --------------------------------------------------------------------------
# Bulk backfill across many reporters
# --------------------------------------------------------------------------

# A request may carry several reporters. The binding constraint is the 100000
# record cap, so the batch size is derived from how many rows one reporter
# contributes. These are deliberately conservative; a batch that still comes
# back at the cap is subdivided automatically by fetch_segments.
ROWS_PER_REPORTER = {
    # partners x periods x flows
    ("totals_partners", "A"): 220 * 12 * 2,
    ("totals_partners", "M"): 200 * 12 * 2,
    # hs2 chapters x periods x flows
    ("products", "A"): 97 * 12 * 2,
    ("products", "M"): 97 * 12 * 2,
}


def reporters_per_request(kind: str, freq: str, periods: int, cap: int | None = None) -> int:
    settings = get_settings()
    cap = cap or settings.max_records_per_request
    per_period = ROWS_PER_REPORTER[(kind, freq)] / 12.0
    estimated = max(1.0, per_period * max(1, periods))
    # Aim at half the cap so an unusually dense reporter cannot push the batch
    # over it and force a re-fetch.
    return max(1, int((cap * 0.5) // estimated))


def bulk_totals_and_partners(
    client: ComtradeClient, reporters: Sequence[int], freq: str, periods: Sequence[str],
    *, priority: str = "normal", force: bool = False,
) -> list[IngestResult]:
    """Fetch reporter-World totals and per-partner totals for many reporters."""
    batch_size = reporters_per_request("totals_partners", freq, len(periods))
    results: list[IngestResult] = []
    for start in range(0, len(reporters), batch_size):
        group = list(reporters[start:start + batch_size])
        rows, calls, truncated = fetch_segments(
            client, freq,
            {"reporterCode": ",".join(str(r) for r in group),
             "cmdCode": "TOTAL", "flowCode": "X,M"},
            periods, priority=priority, force=force, request_type="bulk",
        )
        frame = etl.normalise_rows(rows)
        replace = _replace_scope(freq, periods)
        for reporter in group:
            slice_ = frame.filter(pl.col("reporter_code") == reporter)
            world = slice_.filter(pl.col("partner_code") == 0)
            bilateral = slice_.filter(pl.col("partner_code") > 0)
            if world.height == 0 and bilateral.height == 0:
                continue
            _, total_rows = etl.merge_into_partition(
                "totals", world.drop("partner_code"), freq=freq, reporter=reporter,
                replace_scope=replace,
            )
            state.bump_dataset_version("totals", etl.scope_name(reporter, freq), total_rows)
            _, partner_rows = etl.merge_into_partition(
                "partners", bilateral, freq=freq, reporter=reporter, replace_scope=replace,
            )
            state.bump_dataset_version("partners", etl.scope_name(reporter, freq), partner_rows,
                                       coverage=_reconcile_partners(world, bilateral))
            results.append(IngestResult("totals+partners", etl.scope_name(reporter, freq),
                                        total_rows + partner_rows, 0, 0))
        if results:
            results[-1] = IngestResult(results[-1].dataset, results[-1].scope, results[-1].rows,
                                       calls, truncated)
    return results


def bulk_products(
    client: ComtradeClient, reporters: Sequence[int], freq: str, periods: Sequence[str],
    *, level: int = 2, priority: str = "normal", force: bool = False,
) -> list[IngestResult]:
    """Fetch reporter-World HS composition for many reporters."""
    dataset = "products_hs2" if level == 2 else "products_hs4"
    batch_size = reporters_per_request("products", freq, len(periods))
    results: list[IngestResult] = []
    for start in range(0, len(reporters), batch_size):
        group = list(reporters[start:start + batch_size])
        rows, calls, truncated = fetch_segments(
            client, freq,
            {"reporterCode": ",".join(str(r) for r in group),
             "cmdCode": f"AG{level}", "flowCode": "X,M", "partnerCode": 0},
            periods, priority=priority, force=force, request_type="bulk",
        )
        frame = etl.normalise_rows(rows).filter(pl.col("hs_level") == level)
        replace = _replace_scope(freq, periods)
        for reporter in group:
            slice_ = frame.filter(pl.col("reporter_code") == reporter)
            if slice_.height == 0:
                continue
            if "partner_code" in slice_.columns:
                slice_ = slice_.drop("partner_code")
            _, written = etl.merge_into_partition(
                dataset, slice_, freq=freq, reporter=reporter, replace_scope=replace,
            )
            state.bump_dataset_version(dataset, etl.scope_name(reporter, freq), written)
            results.append(IngestResult(dataset, etl.scope_name(reporter, freq), written, 0, 0))
        if results:
            results[-1] = IngestResult(results[-1].dataset, results[-1].scope, results[-1].rows,
                                       calls, truncated)
    return results


def bulk_annual_backfill(
    client: ComtradeClient, reporters: Sequence[int], *, start_year: int, end_year: int,
    priority: str = "normal", force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    periods = annual_periods(start_year, end_year)
    made = 0
    for chunk_of_periods in chunk(periods, get_settings().max_periods_per_request):
        if progress:
            progress(f"Annual totals and partners {chunk_of_periods[0]}-{chunk_of_periods[-1]}")
        made += sum(r.calls for r in bulk_totals_and_partners(
            client, reporters, "A", chunk_of_periods, priority=priority, force=force))
        if progress:
            progress(f"Annual product composition {chunk_of_periods[0]}-{chunk_of_periods[-1]}")
        made += sum(r.calls for r in bulk_products(
            client, reporters, "A", chunk_of_periods, priority=priority, force=force))
    return {"reporters": len(reporters), "periods": len(periods), "calls": made}


def bulk_monthly_backfill(
    client: ComtradeClient, reporters: Sequence[int], *, months: int,
    priority: str = "normal", force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    periods = monthly_periods(months)
    made = 0
    for chunk_of_periods in chunk(periods, get_settings().max_periods_per_request):
        if progress:
            progress(f"Monthly totals and partners {chunk_of_periods[0]}-{chunk_of_periods[-1]}")
        made += sum(r.calls for r in bulk_totals_and_partners(
            client, reporters, "M", chunk_of_periods, priority=priority, force=force))
        if progress:
            progress(f"Monthly product composition {chunk_of_periods[0]}-{chunk_of_periods[-1]}")
        made += sum(r.calls for r in bulk_products(
            client, reporters, "M", chunk_of_periods, priority=priority, force=force))
    return {"reporters": len(reporters), "periods": len(periods), "calls": made}


def active_reporters(limit: int | None = None) -> list[int]:
    """Currently valid, non-aggregate reporting territories."""
    from .refs import load_reporters

    frame = load_reporters().filter(
        ~pl.col("is_group") & ~pl.col("expired").fill_null(False)
    )
    codes = sorted(int(c) for c in frame["reporter_code"].to_list())
    return codes[:limit] if limit else codes
