"""World Bank macroeconomic context.

Trade values on their own do not say how large a trade flow is *relative to the
economy that produced it*. GDP and population turn them into ratios a reader can
compare across countries: trade openness, exports per capita, balance as a share
of GDP.

The World Bank Indicators API is public, unauthenticated and unmetered, so this
never touches the Comtrade budget. One request covers every country, three
indicators and the whole year range.
"""

from __future__ import annotations

from typing import Any

import httpx
import polars as pl

from . import state
from .config import get_settings
from .etl import atomic_write_parquet
from .logging_setup import get_logger

log = get_logger("trade.worldbank")

BASE_URL = "https://api.worldbank.org/v2"

INDICATORS = {
    "NY.GDP.MKTP.CD": "gdp_usd",
    "SP.POP.TOTL": "population",
    "NY.GDP.PCAP.CD": "gdp_per_capita",
}

MACRO_SCHEMA = {
    "iso3": pl.Utf8,
    "year": pl.Int16,
    "gdp_usd": pl.Float64,
    "population": pl.Float64,
    "gdp_per_capita": pl.Float64,
}


def refresh_macro(start_year: int | None = None, end_year: int | None = None) -> int:
    """Download GDP, population and GDP per capita for every country."""
    settings = get_settings()
    settings.ensure_dirs()
    start = start_year or settings.annual_history_start
    from datetime import date

    end = end_year or date.today().year

    url = f"{BASE_URL}/country/all/indicator/{';'.join(INDICATORS)}"
    params = {
        "format": "json",
        "source": "2",
        "per_page": "30000",
        "date": f"{start}:{end}",
    }
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise RuntimeError("Unexpected World Bank response shape")

    records: dict[tuple[str, int], dict[str, Any]] = {}
    for row in payload[1]:
        iso3 = (row.get("countryiso3code") or "").strip().upper()
        indicator = (row.get("indicator") or {}).get("id")
        column = INDICATORS.get(indicator)
        if not iso3 or column is None:
            continue
        try:
            year = int(row.get("date"))
        except (TypeError, ValueError):
            continue
        value = row.get("value")
        if value is None:
            # A country that did not report an indicator for a year is absent,
            # exactly as with trade data. It is not zero.
            continue
        entry = records.setdefault((iso3, year), {"iso3": iso3, "year": year})
        entry[column] = float(value)

    frame = pl.DataFrame(list(records.values()), schema=MACRO_SCHEMA)
    frame = frame.sort(["iso3", "year"])
    atomic_write_parquet(frame, get_settings().refs_dir / "macro.parquet")
    state.bump_dataset_version("macro", "all", frame.height,
                               coverage={"source": "World Bank Indicators API",
                                         "indicators": list(INDICATORS.values()),
                                         "countries": frame["iso3"].n_unique()})
    log.info("macro indicators refreshed",
             extra={"rows": frame.height, "countries": frame["iso3"].n_unique()})
    return frame.height


def load_macro() -> pl.DataFrame:
    path = get_settings().refs_dir / "macro.parquet"
    if not path.exists():
        return pl.DataFrame(schema=MACRO_SCHEMA)
    return pl.read_parquet(path)


def macro_for(iso3: str | None, year: int | None = None) -> dict[str, Any] | None:
    """Latest available macro row for a country, at or before ``year``."""
    if not iso3:
        return None
    frame = load_macro().filter(pl.col("iso3") == iso3.upper())
    if year is not None:
        frame = frame.filter(pl.col("year") <= year)
    frame = frame.filter(pl.col("gdp_usd").is_not_null()).sort("year")
    if frame.height == 0:
        return None
    return frame.row(-1, named=True)


def macro_series(iso3: str | None) -> list[dict[str, Any]]:
    if not iso3:
        return []
    return load_macro().filter(pl.col("iso3") == iso3.upper()).sort("year").to_dicts()


def ratios(trade: dict[str, Any], macro: dict[str, Any] | None) -> dict[str, Any]:
    """Trade-to-economy ratios. Any missing input yields None, not a guess.

    The GDP year may lag the trade year; ``gdp_year`` states which was used so
    the reader can see the mismatch rather than assume there is none.
    """
    exports = trade.get("exports")
    imports = trade.get("imports")
    if macro is None:
        return {"available": False}

    gdp = macro.get("gdp_usd")
    population = macro.get("population")
    total_trade = None
    if exports is not None and imports is not None:
        total_trade = exports + imports

    def over_gdp(value: float | None) -> float | None:
        if value is None or not gdp or gdp <= 0:
            return None
        return value / gdp

    def per_capita(value: float | None) -> float | None:
        if value is None or not population or population <= 0:
            return None
        return value / population

    return {
        "available": True,
        "gdp_year": macro.get("year"),
        "gdp_usd": gdp,
        "population": population,
        "gdp_per_capita": macro.get("gdp_per_capita"),
        "trade_openness": over_gdp(total_trade),
        "exports_over_gdp": over_gdp(exports),
        "imports_over_gdp": over_gdp(imports),
        "balance_over_gdp": over_gdp(
            (exports - imports) if exports is not None and imports is not None else None
        ),
        "exports_per_capita": per_capita(exports),
        "imports_per_capita": per_capita(imports),
        "source": "World Bank",
    }
