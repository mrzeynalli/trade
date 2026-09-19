"""Eurostat — the single market as a dimension, not a set of 27 reporters.

UN Comtrade sees the European Union as twenty-seven separate reporters, each
with its own bilateral partners. That is true, but it cannot answer the question
that actually matters about a member state's trade: how much of it stays inside
the single market, and how much crosses the Union's external border. Answering
it from Comtrade means summing twenty-six bilateral partners per country per
period and hoping the mirror gaps cancel.

Eurostat publishes that split natively, because it is how the data is collected:
intra-EU movements come from Intrastat declarations and extra-EU movements from
customs. This module reads `ext_st_27_2020msbec`, which carries, monthly and per
member state:

  * the intra-EU / extra-EU / world split of both flows, and
  * a Broad Economic Category breakdown — intermediate, capital, consumption —
    which is a compositional dimension the rest of this application has no
    source for at all.

It is also fast. Eurostat publishes roughly six weeks after month end, against
Comtrade's twelve to twenty-four months for an annual reference year, so the
European part of the record runs well ahead of the rest of it.

**Currency.** Eurostat reports in euro; everything else here is US dollars. The
two are never presented as one figure. What this module feeds the interface is
*shares* — intra-EU as a percentage of a country's trade, the BEC mix — which
are currency-invariant, plus absolute values that are labelled EUR wherever they
appear. No exchange rate is applied, because applying one would invent a
precision the source does not have.

The API is public, unauthenticated and unmetered, so this never touches the
Comtrade budget.
"""

from __future__ import annotations

from typing import Any, Iterable

import httpx
import polars as pl

from . import state
from .config import get_settings
from .etl import atomic_write_parquet
from .logging_setup import get_logger

log = get_logger("trade.eurostat")

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
DATASET = "ext_st_27_2020msbec"

# Partner codes are aggregates, not countries: EU27_2020 is "the other member
# states", EXT_EU27_2020 is everything outside the Union, WORLD is both.
PARTNERS = {"EU27_2020": "intra", "EXT_EU27_2020": "extra", "WORLD": "world"}
FLOWS = {"EXP": "exports", "IMP": "imports"}
# TOTAL plus the three Broad Economic Categories that partition it.
CATEGORIES = ("TOTAL", "INT", "CAP", "CONS")

EUROSTAT_SCHEMA = {
    "geo": pl.Utf8,
    "period": pl.Utf8,
    "year": pl.Int16,
    "month": pl.Int8,
    "category": pl.Utf8,
    "scope": pl.Utf8,
    "exports": pl.Float64,
    "imports": pl.Float64,
}

# Eurostat's geo dimension is ISO 3166-1 alpha-2 with two exceptions of its own.
GEO_TO_ISO3 = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "CY": "CYP", "CZ": "CZE",
    "DE": "DEU", "DK": "DNK", "EE": "EST", "EL": "GRC", "ES": "ESP",
    "FI": "FIN", "FR": "FRA", "HR": "HRV", "HU": "HUN", "IE": "IRL",
    "IT": "ITA", "LT": "LTU", "LU": "LUX", "LV": "LVA", "MT": "MLT",
    "NL": "NLD", "PL": "POL", "PT": "PRT", "RO": "ROU", "SE": "SWE",
    "SI": "SVN", "SK": "SVK",
}
ISO3_TO_GEO = {v: k for k, v in GEO_TO_ISO3.items()}


def _path(name: str) -> Any:
    return get_settings().parquet_dir / "advanced" / "eurostat" / f"{name}.parquet"


def _decode(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a JSON-stat 2.0 cube into records.

    Values are keyed by a single flat index over the dimension cross-product in
    `id` order, so each key is decoded back into one coordinate per dimension.
    """
    ids: list[str] = payload["id"]
    sizes: list[int] = payload["size"]
    # Position -> code, per dimension.
    codes: list[list[str]] = []
    for dim in ids:
        index = payload["dimension"][dim]["category"]["index"]
        ordered = [""] * len(index)
        for code, position in index.items():
            ordered[position] = code
        codes.append(ordered)

    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    out: list[dict[str, Any]] = []
    for flat, value in payload["value"].items():
        if value is None:
            continue
        remainder = int(flat)
        point: dict[str, str] = {}
        for position, dim in enumerate(ids):
            point[dim] = codes[position][remainder // strides[position] % sizes[position]]
        point["_value"] = value
        out.append(point)
    return out


def _fetch(months: int) -> list[dict[str, Any]]:
    params: list[tuple[str, str]] = [
        ("format", "JSON"), ("lang", "EN"),
        ("indic_et", "TRD_VAL"),
        ("lastTimePeriod", str(months)),
    ]
    params += [("stk_flow", code) for code in FLOWS]
    params += [("partner", code) for code in PARTNERS]
    params += [("bclas_bec", code) for code in CATEGORIES]

    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        response = client.get(f"{BASE_URL}/{DATASET}", params=params)
        response.raise_for_status()
        return _decode(response.json())


def refresh(months: int = 36) -> dict[str, int]:
    """Download the monthly intra/extra-EU split for every member state.

    One request covers 27 countries, three partner scopes, two flows and four
    product categories. Nothing here consumes Comtrade budget.
    """
    settings = get_settings()
    settings.ensure_dirs()

    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for point in _fetch(months):
        geo = point.get("geo", "")
        scope = PARTNERS.get(point.get("partner", ""))
        flow = FLOWS.get(point.get("stk_flow", ""))
        period = point.get("time", "")
        if not geo or scope is None or flow is None or "-" not in period:
            continue
        year, month = period.split("-")
        key = (geo, period, point.get("bclas_bec", "TOTAL"), scope)
        entry = merged.setdefault(key, {
            "geo": geo,
            # Same period vocabulary as the Comtrade cache: "202606".
            "period": f"{year}{month}",
            "year": int(year),
            "month": int(month),
            "category": point.get("bclas_bec", "TOTAL"),
            "scope": scope,
            "exports": None,
            "imports": None,
        })
        # Eurostat reports in millions of euro; stored in euro so the unit is
        # the same order of magnitude as every other value in the cache.
        entry[flow] = float(point["_value"]) * 1_000_000

    frame = pl.DataFrame(list(merged.values()), schema=EUROSTAT_SCHEMA).sort(
        ["geo", "category", "scope", "period"])
    if frame.height == 0:
        raise RuntimeError("Eurostat returned no observations")

    _path("intra_extra").parent.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(frame, _path("intra_extra"))

    countries = frame["geo"].n_unique()
    latest = frame["period"].max()
    state.bump_dataset_version(
        "eurostat", "all", frame.height,
        coverage={"source": "Eurostat ext_st_27_2020msbec",
                  "member_states": countries, "latest_period": latest},
    )
    log.info("Eurostat intra/extra split refreshed",
             extra={"rows": frame.height, "member_states": countries, "latest": latest})
    return {"rows": frame.height, "member_states": countries, "latest": latest}


def load() -> pl.DataFrame:
    path = _path("intra_extra")
    if not path.exists():
        return pl.DataFrame(schema=EUROSTAT_SCHEMA)
    return pl.read_parquet(path)


def latest_period() -> str | None:
    frame = load()
    return None if frame.height == 0 else str(frame["period"].max())


def is_member(iso3: str | None) -> bool:
    return bool(iso3) and iso3.upper() in ISO3_TO_GEO


def split_for(iso3: str, period: str | None = None,
              category: str = "TOTAL") -> dict[str, Any] | None:
    """One member state's intra/extra split for a month.

    Shares rather than euro totals are the point: they survive the currency
    difference between this source and the rest of the application.
    """
    geo = ISO3_TO_GEO.get((iso3 or "").upper())
    if geo is None:
        return None
    frame = load().filter((pl.col("geo") == geo) & (pl.col("category") == category))
    if frame.height == 0:
        return None
    target = period or str(frame["period"].max())
    rows = {r["scope"]: r for r in frame.filter(pl.col("period") == target).to_dicts()}
    world = rows.get("world")
    intra = rows.get("intra")
    extra = rows.get("extra")
    if world is None:
        return None

    def share(part: dict[str, Any] | None, flow: str) -> float | None:
        total = world.get(flow)
        if not part or not total:
            return None
        value = part.get(flow)
        return None if value is None else value / total

    return {
        "iso3": iso3.upper(),
        "period": target,
        "label": f"{target[:4]}-{target[4:]}",
        "category": category,
        "exports_eur": world.get("exports"),
        "imports_eur": world.get("imports"),
        "intra_export_share": share(intra, "exports"),
        "intra_import_share": share(intra, "imports"),
        "extra_export_share": share(extra, "exports"),
        "extra_import_share": share(extra, "imports"),
    }


def member_splits(period: str | None = None,
                  category: str = "TOTAL") -> list[dict[str, Any]]:
    """Every member state's split for one month, most intra-dependent first."""
    frame = load().filter(pl.col("category") == category)
    if frame.height == 0:
        return []
    target = period or str(frame["period"].max())
    out: list[dict[str, Any]] = []
    for geo, iso3 in GEO_TO_ISO3.items():
        row = split_for(iso3, target, category)
        if row and row["intra_export_share"] is not None:
            row["geo"] = geo
            out.append(row)
    out.sort(key=lambda r: r["intra_export_share"] or 0, reverse=True)
    return out


BEC_LABELS = {"INT": "Intermediate goods", "CAP": "Capital goods",
              "CONS": "Consumption goods"}


def composition_period(iso3: str) -> str | None:
    """The latest month with a Broad Economic Category breakdown.

    Eurostat publishes the headline total about a month ahead of the category
    split, so the newest period overall usually has no breakdown. Resolving the
    period from the categories themselves means the composition is a month
    older than the total and says so, rather than coming back empty.
    """
    geo = ISO3_TO_GEO.get((iso3 or "").upper())
    if geo is None:
        return None
    frame = load().filter(
        (pl.col("geo") == geo)
        & (pl.col("scope") == "world")
        & pl.col("category").is_in(list(BEC_LABELS))
        & pl.col("exports").is_not_null()
    )
    return None if frame.height == 0 else str(frame["period"].max())


def composition_for(iso3: str, period: str | None = None) -> list[dict[str, Any]]:
    """The Broad Economic Category mix of a member state's exports.

    The three categories do not sum to the total: Eurostat leaves goods it
    cannot classify — and motor spirit, which it reports separately — outside
    them. The shares are therefore of the whole, and the remainder is
    unclassified rather than missing.
    """
    geo = ISO3_TO_GEO.get((iso3 or "").upper())
    if geo is None:
        return []
    target = period or composition_period(iso3)
    if target is None:
        return []
    frame = load().filter((pl.col("geo") == geo) & (pl.col("scope") == "world"))
    rows = {r["category"]: r for r in frame.filter(pl.col("period") == target).to_dicts()}
    total = (rows.get("TOTAL") or {}).get("exports")
    out = []
    for code, label in BEC_LABELS.items():
        value = (rows.get(code) or {}).get("exports")
        if value is None:
            continue
        out.append({
            "code": code,
            "name": label,
            "period": target,
            "label": f"{target[:4]}-{target[4:]}",
            "value_eur": value,
            "share": (value / total) if total else None,
        })
    out.sort(key=lambda r: r["value_eur"], reverse=True)
    return out


def series_for(iso3: str, limit: int = 24,
               category: str = "TOTAL") -> list[dict[str, Any]]:
    """Monthly intra/extra export values for one member state."""
    geo = ISO3_TO_GEO.get((iso3 or "").upper())
    if geo is None:
        return []
    frame = load().filter((pl.col("geo") == geo) & (pl.col("category") == category))
    periods = sorted({str(p) for p in frame["period"]})[-limit:]
    out = []
    for period in periods:
        rows = {r["scope"]: r for r in frame.filter(pl.col("period") == period).to_dicts()}
        out.append({
            "period": period,
            "label": f"{period[:4]}-{period[4:]}",
            "intra": (rows.get("intra") or {}).get("exports"),
            "extra": (rows.get("extra") or {}).get("exports"),
        })
    return out


def member_iso3s() -> Iterable[str]:
    return GEO_TO_ISO3.values()
