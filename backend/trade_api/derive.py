"""Precomputed derived tables.

Concentration and growth attribution need a full pass over a reporter's
history, so they are computed once after ingestion and stored beside the facts
rather than recomputed on every request.
"""

from __future__ import annotations

from typing import Any, Sequence

import polars as pl

from . import analytics, etl, state, store
from .etl import atomic_write_parquet
from .config import get_settings
from .logging_setup import get_logger

log = get_logger("trade.derive")

CONCENTRATION_SCHEMA = {
    "reporter_code": pl.Int32,
    "year": pl.Int16,
    "flow_code": pl.Utf8,
    "dimension": pl.Utf8,          # "product" | "partner"
    "hhi": pl.Float64,
    "effective_number": pl.Float64,
    "top1_share": pl.Float64,
    "top3_share": pl.Float64,
    "top5_share": pl.Float64,
    "categories": pl.Int32,
}


def _advanced_path(name: str, reporter: int) -> Any:
    return get_settings().parquet_dir / "advanced" / name / f"reporter={reporter:03d}" / "part.parquet"


def rebuild_concentration(reporter: int) -> int:
    """HHI, effective number and top-N dependency shares per year and flow."""
    latest = store.latest_period(reporter, "A")
    if not latest:
        return 0
    rows: list[dict[str, Any]] = []
    for year in latest["available"]:
        for flow in ("X", "M"):
            products = store.product_ranking(reporter, "A", [str(year)], flow, level=2, top_n=10_000)
            partners = store.partner_ranking(reporter, "A", [str(year)], flow, top_n=10_000)
            for dimension, payload in (("product", products), ("partner", partners)):
                values = [item["value"] for item in payload["items"]]
                if not values:
                    continue
                profile = analytics.concentration_profile(values)
                rows.append(
                    {
                        "reporter_code": reporter, "year": year, "flow_code": flow,
                        "dimension": dimension, "hhi": profile["hhi"],
                        "effective_number": profile["effective_number"],
                        "top1_share": profile["top1_share"], "top3_share": profile["top3_share"],
                        "top5_share": profile["top5_share"], "categories": profile["categories"],
                    }
                )
    frame = pl.DataFrame(rows, schema=CONCENTRATION_SCHEMA)
    etl.atomic_write_parquet(frame, _advanced_path("concentration", reporter))
    state.bump_dataset_version("concentration", etl.scope_name(reporter, "A"), frame.height)
    return frame.height


def read_concentration(reporter: int) -> list[dict[str, Any]]:
    path = _advanced_path("concentration", reporter)
    if not path.exists():
        return []
    return pl.read_parquet(path).sort(["year", "flow_code", "dimension"]).to_dicts()


def growth_table(reporter: int, freq: str, flow: str, *, level: int = 2,
                 current: Sequence[str] | None = None,
                 previous: Sequence[str] | None = None) -> dict[str, Any]:
    """Fastest-growing and largest-declining product categories."""
    settings = get_settings()
    latest = store.latest_period(reporter, freq)
    if not latest:
        return {"available": False, "growing": [], "declining": [], "period": None}
    if current is None or previous is None:
        available = latest["available"]
        if freq == "A":
            reference = latest.get("latest_complete") or latest["latest"]
            index = available.index(reference) if reference in available else 0
            if index + 1 >= len(available):
                return {"available": False, "growing": [], "declining": [], "period": str(reference)}
            current = [str(reference)]
            previous = [str(available[index + 1])]
        else:
            if len(available) < 24:
                return {"available": False, "growing": [], "declining": [], "period": None}
            current = sorted(available[:12])
            previous = sorted(available[12:24])

    now = store.product_ranking(reporter, freq, current, flow, level=level, top_n=10_000)
    before = store.product_ranking(reporter, freq, previous, flow, level=level, top_n=10_000)
    if not now["items"] and not before["items"]:
        return {"available": False, "growing": [], "declining": [], "period": None}

    entries = analytics.growth_ranking(
        {item["key"]: item["value"] for item in now["items"]},
        {item["key"]: item["value"] for item in before["items"]},
        min_baseline_absolute=settings.growth_min_baseline_usd,
        min_baseline_share=settings.growth_min_baseline_share,
    )
    serialise = lambda e: {
        "key": e.key, "current": e.current, "previous": e.previous,
        "absolute_change": e.absolute_change, "percent_change": e.percent_change,
        "contribution": e.contribution,
    }
    return {
        "available": bool(entries),
        "current_period": list(current),
        "previous_period": list(previous),
        "growing": [serialise(e) for e in entries[:5]],
        "declining": [serialise(e) for e in reversed(entries[-5:]) if e.absolute_change < 0],
    }


def partner_growth_table(reporter: int, freq: str, flow: str) -> dict[str, Any]:
    settings = get_settings()
    latest = store.latest_period(reporter, freq)
    if not latest:
        return {"available": False, "growing": [], "declining": []}
    available = latest["available"]
    if freq == "A":
        reference = latest.get("latest_complete") or latest["latest"]
        index = available.index(reference) if reference in available else 0
        if index + 1 >= len(available):
            return {"available": False, "growing": [], "declining": []}
        current, previous = [str(reference)], [str(available[index + 1])]
    else:
        if len(available) < 24:
            return {"available": False, "growing": [], "declining": []}
        current, previous = sorted(available[:12]), sorted(available[12:24])

    now = store.partner_ranking(reporter, freq, current, flow, top_n=10_000)
    before = store.partner_ranking(reporter, freq, previous, flow, top_n=10_000)
    entries = analytics.growth_ranking(
        {item["key"]: item["value"] for item in now["items"]},
        {item["key"]: item["value"] for item in before["items"]},
        min_baseline_absolute=settings.growth_min_baseline_usd,
        min_baseline_share=settings.growth_min_baseline_share,
    )
    serialise = lambda e: {
        "key": e.key, "current": e.current, "previous": e.previous,
        "absolute_change": e.absolute_change, "percent_change": e.percent_change,
        "contribution": e.contribution,
    }
    return {
        "available": bool(entries),
        "current_period": current, "previous_period": previous,
        "growing": [serialise(e) for e in entries[:5]],
        "declining": [serialise(e) for e in reversed(entries[-5:]) if e.absolute_change < 0],
    }


def rebuild_all(reporter: int) -> dict[str, int]:
    return {"concentration": rebuild_concentration(reporter)}


# --------------------------------------------------------------------------
# World overview
# --------------------------------------------------------------------------

WORLD_TOTALS_SCHEMA = {
    "year": pl.Int16,
    "reporters": pl.Int32,
    "exports": pl.Float64,
    "imports": pl.Float64,
}

WORLD_COUNTRY_SCHEMA = {
    "year": pl.Int16,
    "reporter_code": pl.Int32,
    "iso3": pl.Utf8,
    "name": pl.Utf8,
    "exports": pl.Float64,
    "imports": pl.Float64,
    "balance": pl.Float64,
    "export_share": pl.Float64,
    "import_share": pl.Float64,
    "export_yoy": pl.Float64,
}


def _world_path(name: str) -> Any:
    return get_settings().parquet_dir / "advanced" / "world" / f"{name}.parquet"


def rebuild_world_overview() -> dict[str, int]:
    """Aggregate every cached reporter into a world view.

    The total is the sum of what reporters actually published, so it is
    *reported* world trade. The reporter count travels with it so the figure is
    never mistaken for a complete world total.
    """
    from . import refs

    reporters = refs.load_reporters()
    lookup = {
        int(r["reporter_code"]): r
        for r in reporters.filter(
            ~pl.col("is_group") & ~pl.col("expired").fill_null(False)
        ).to_dicts()
    }

    rows: list[dict[str, Any]] = []
    for code in store.cached_reporters("A"):
        entry = lookup.get(code)
        if entry is None:
            continue  # aggregates and historical territories must not be summed
        for point in store.totals_series(code, "A"):
            rows.append(
                {
                    "year": point["year"],
                    "reporter_code": code,
                    "iso3": entry.get("iso3"),
                    "name": entry["name"],
                    "exports": point["exports"],
                    "imports": point["imports"],
                }
            )

    if not rows:
        return {"years": 0, "countries": 0}

    frame = pl.DataFrame(rows, schema_overrides={"year": pl.Int16, "reporter_code": pl.Int32})

    totals = (
        frame.group_by("year")
        .agg(
            pl.col("reporter_code").n_unique().alias("reporters"),
            pl.col("exports").sum().alias("exports"),
            pl.col("imports").sum().alias("imports"),
        )
        .sort("year")
        .cast({"reporters": pl.Int32})
    )
    atomic_write_parquet(totals.select(list(WORLD_TOTALS_SCHEMA)), _world_path("totals"))

    year_export_total = dict(zip(totals["year"].to_list(), totals["exports"].to_list()))
    year_import_total = dict(zip(totals["year"].to_list(), totals["imports"].to_list()))
    frame = frame.with_columns(
        (pl.col("exports") - pl.col("imports")).alias("balance"),
        pl.col("year").replace_strict(year_export_total, default=None).alias("_world_exports"),
        pl.col("year").replace_strict(year_import_total, default=None).alias("_world_imports"),
    ).with_columns(
        pl.when(pl.col("_world_exports") > 0)
        .then(pl.col("exports") / pl.col("_world_exports"))
        .otherwise(None)
        .alias("export_share"),
        pl.when(pl.col("_world_imports") > 0)
        .then(pl.col("imports") / pl.col("_world_imports"))
        .otherwise(None)
        .alias("import_share"),
    ).drop("_world_exports", "_world_imports")

    frame = frame.sort(["reporter_code", "year"]).with_columns(
        pl.col("exports").shift(1).over("reporter_code").alias("_previous")
    ).with_columns(
        pl.when(pl.col("_previous") > 0)
        .then((pl.col("exports") - pl.col("_previous")) / pl.col("_previous"))
        .otherwise(None)
        .alias("export_yoy")
    ).drop("_previous")

    countries = frame.select(list(WORLD_COUNTRY_SCHEMA)).sort(["year", "exports"], descending=[False, True])
    atomic_write_parquet(countries, _world_path("countries"))

    state.bump_dataset_version("world", "all", countries.height)
    log.info("world overview rebuilt",
             extra={"years": totals.height, "countries": countries["reporter_code"].n_unique()})
    return {"years": totals.height, "countries": int(countries["reporter_code"].n_unique())}


def read_world_totals() -> list[dict[str, Any]]:
    path = _world_path("totals")
    if not path.exists():
        return []
    return pl.read_parquet(path).sort("year").to_dicts()


def read_world_countries(year: int | None = None) -> list[dict[str, Any]]:
    path = _world_path("countries")
    if not path.exists():
        return []
    frame = pl.read_parquet(path)
    if year is not None:
        frame = frame.filter(pl.col("year") == year)
    return frame.sort("exports", descending=True).to_dicts()


def world_years() -> list[int]:
    return [int(row["year"]) for row in read_world_totals()]
