"""IMF International Trade in Goods (ITG) — recent-period coverage.

UN Comtrade is the spine of this product: it is the only source here that
carries partner and product detail, so every drilldown is Comtrade. What it is
not is fast. A reference year takes twelve to twenty-four months to fill in as
reporters publish, which is why the world view holds a coverage floor and shows
a year most countries have actually reported rather than the newest one.

The IMF's ITG dataset (the successor to Direction of Trade Statistics) covers
the same headline aggregates — goods exports FOB and imports CIF, in USD — with
a much shorter lag, because the IMF collects them from national statistical
offices directly rather than waiting for a full customs submission. It has no
partner or product breakdown at all, so it can never replace Comtrade; it
extends it at the recent end.

    2025 annual   Comtrade  98 reporters   ·  IMF  173 countries
    2026 monthly  Comtrade  35 reporters   ·  IMF   92 countries

Two rules govern how the two are used together, both of them about honesty
rather than convenience:

1. **A figure is never blended.** A period is sourced from Comtrade *or* from
   the IMF, whole. Summing a Comtrade reporter and an IMF country into one
   world total would double-count wherever both published and silently change
   the definition of the number.
2. **The source travels with the figure.** Every aggregate this module feeds
   carries the dataset it came from, so the interface can say so.

The API is keyed but unmetered in the way Comtrade is metered: it has no daily
call budget, so nothing here touches `call_log` or competes with an interactive
country fetch.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

import httpx
import polars as pl

from . import state
from .config import get_settings
from .etl import atomic_write_parquet
from .logging_setup import get_logger

log = get_logger("trade.imf")

BASE_URL = "https://api.imf.org/external/sdmx/2.1"
DATAFLOW = "IMF.STA,ITG"

# ITG keys are COUNTRY.INDICATOR.TYPE_OF_TRANSFORMATION.FREQUENCY, and the
# country dimension is ISO alpha-3 — the same key the rest of this application
# uses, so no crosswalk is needed. An empty country matches every country.
FLOWS = {
    "exports": ("XG", "FOB_USD"),
    "imports": ("MG", "CIF_USD"),
}

# Valuation differs between the two flows and between the two sources: exports
# are free-on-board, imports are cost-insurance-freight. That is the same
# convention Comtrade reports on, so the two remain comparable, but it means
# world imports exceed world exports by roughly the cost of freight.
VALUATION = {"exports": "FOB", "imports": "CIF"}

ITG_SCHEMA = {
    "iso3": pl.Utf8,
    "period": pl.Utf8,
    "year": pl.Int16,
    "month": pl.Int8,
    "freq": pl.Utf8,
    "exports": pl.Float64,
    "imports": pl.Float64,
}

_SERIES = re.compile(r"<Series ([^>]*)>(.*?)</Series>", re.S)
_OBS = re.compile(r'TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"')
_COUNTRY = re.compile(r'COUNTRY="([^"]+)"')
# 2025 for annual, 2026-M05 for monthly.
_PERIOD = re.compile(r"^(\d{4})(?:-M(\d{2}))?$")


def _path(name: str) -> Any:
    return get_settings().parquet_dir / "advanced" / "imf" / f"{name}.parquet"


def _headers() -> dict[str, str]:
    settings = get_settings()
    key = settings.imf_api_key or settings.imf_api_key_secondary
    if not key:
        raise RuntimeError(
            "No IMF subscription key configured. Set IMF_API_KEY in the environment."
        )
    return {"Ocp-Apim-Subscription-Key": key, "Accept": "application/xml"}


def _fetch(flow: str, freq: str, start: str) -> list[tuple[str, str, float]]:
    """One request covers every country for one flow. Returns (iso3, period, value)."""
    indicator, transformation = FLOWS[flow]
    url = f"{BASE_URL}/data/{DATAFLOW}/.{indicator}.{transformation}.{freq}"
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        response = client.get(url, params={"startPeriod": start}, headers=_headers())
        response.raise_for_status()
        body = response.text

    out: list[tuple[str, str, float]] = []
    for attributes, series_body in _SERIES.findall(body):
        match = _COUNTRY.search(attributes)
        if match is None:
            continue
        iso3 = match.group(1).upper()
        # ITG carries regional and world aggregates in the same dimension as
        # countries. They would double-count against their members, so only
        # three-letter country codes are kept.
        if len(iso3) != 3 or not iso3.isalpha():
            continue
        for period, raw in _OBS.findall(series_body):
            try:
                value = float(raw)
            except ValueError:
                continue
            out.append((iso3, period, value))
    return out


def _rows(freq: str, start: str) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for flow in FLOWS:
        for iso3, period, value in _fetch(flow, freq, start):
            parsed = _PERIOD.match(period)
            if parsed is None:
                continue
            year = int(parsed.group(1))
            month = int(parsed.group(2)) if parsed.group(2) else None
            entry = merged.setdefault(
                (iso3, period),
                {
                    "iso3": iso3,
                    # Stored in the same period vocabulary as the Comtrade
                    # cache — "2025" or "202605" — so the two can be compared
                    # without a format conversion at every call site.
                    "period": f"{year}{month:02d}" if month else str(year),
                    "year": year,
                    "month": month,
                    "freq": freq,
                    "exports": None,
                    "imports": None,
                },
            )
            entry[flow] = value
    return list(merged.values())


def refresh(start_year: int | None = None) -> dict[str, int]:
    """Download annual and monthly headline totals for every country.

    Four requests in total — two flows times two frequencies — because the
    country dimension is left open. Nothing here consumes Comtrade budget.
    """
    settings = get_settings()
    settings.ensure_dirs()
    start = start_year or (date.today().year - 6)

    annual = _rows("A", str(start))
    monthly = _rows("M", f"{start}-01")

    frame = pl.DataFrame(annual + monthly, schema=ITG_SCHEMA).sort(["iso3", "freq", "period"])
    if frame.height == 0:
        raise RuntimeError("IMF ITG returned no observations")

    _path("itg").parent.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(frame, _path("itg"))

    countries = frame["iso3"].n_unique()
    state.bump_dataset_version(
        "imf_itg", "all", frame.height,
        coverage={
            "source": "IMF International Trade in Goods (ITG)",
            "countries": countries,
            "annual_years": sorted({int(y) for y in frame.filter(pl.col("freq") == "A")["year"]}),
        },
    )
    log.info("IMF ITG refreshed",
             extra={"rows": frame.height, "countries": countries,
                    "annual": len(annual), "monthly": len(monthly)})
    return {"rows": frame.height, "countries": countries,
            "annual": len(annual), "monthly": len(monthly)}


def load() -> pl.DataFrame:
    path = _path("itg")
    if not path.exists():
        return pl.DataFrame(schema=ITG_SCHEMA)
    return pl.read_parquet(path)


def annual_coverage() -> dict[int, int]:
    """Reporting countries per year, for comparison against the Comtrade cache."""
    frame = load().filter((pl.col("freq") == "A") & pl.col("exports").is_not_null())
    if frame.height == 0:
        return {}
    grouped = frame.group_by("year").agg(pl.col("iso3").n_unique().alias("countries"))
    return {int(r["year"]): int(r["countries"]) for r in grouped.to_dicts()}


def world_totals(year: int) -> dict[str, Any] | None:
    """Reported world trade for a year, summed across IMF-covered countries."""
    frame = load().filter((pl.col("freq") == "A") & (pl.col("year") == year))
    frame = frame.filter(pl.col("exports").is_not_null() | pl.col("imports").is_not_null())
    if frame.height == 0:
        return None
    return {
        "year": year,
        "reporters": int(frame["iso3"].n_unique()),
        "exports": float(frame["exports"].sum()),
        "imports": float(frame["imports"].sum()),
    }


def countries_for(year: int) -> list[dict[str, Any]]:
    """Per-country annual totals, shaped like the Comtrade world aggregate."""
    frame = load().filter((pl.col("freq") == "A") & (pl.col("year") == year)).sort(
        "exports", descending=True, nulls_last=True)
    return frame.select(["iso3", "exports", "imports"]).to_dicts()


def latest_month(iso3: str | None = None) -> dict[str, Any] | None:
    """The most recent monthly observation held, overall or for one country."""
    frame = load().filter(pl.col("freq") == "M")
    if iso3:
        frame = frame.filter(pl.col("iso3") == iso3.upper())
    frame = frame.filter(pl.col("exports").is_not_null()).sort("period")
    if frame.height == 0:
        return None
    return frame.row(-1, named=True)


def monthly_country_count(period: str) -> int:
    """How many countries reported a given month."""
    frame = load().filter((pl.col("freq") == "M") & (pl.col("period") == period))
    return int(frame.filter(pl.col("exports").is_not_null())["iso3"].n_unique())


def monthly_series(iso3: str, limit: int = 36) -> list[dict[str, Any]]:
    frame = (
        load()
        .filter((pl.col("freq") == "M") & (pl.col("iso3") == iso3.upper()))
        .sort("period")
        .tail(limit)
    )
    return frame.to_dicts()


def valuation_note(flows: Iterable[str] = FLOWS) -> str:
    return " · ".join(f"{flow} {VALUATION[flow]}" for flow in flows)
