"""Reference dimensions.

Names are stored once, here, and joined at query time. Fact tables carry only
codes and numbers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import polars as pl

from . import state
from .comtrade import ComtradeClient
from .config import get_settings
from .etl import atomic_write_parquet
from .logging_setup import get_logger

log = get_logger("trade.refs")

# Codes that Comtrade lists as reporters/partners but that are aggregates,
# unknown areas or bunkers rather than reporting territories.
WORLD_CODE = 0
NON_COUNTRY_PARTNER_CODES = {0, 899}  # 0 = World, 899 = Areas, nes

_CODE_PREFIX = re.compile(r"^\s*(TOTAL|[0-9]{2,6})\s*-\s*")


def _clean_name(text: str) -> str:
    return _CODE_PREFIX.sub("", text or "").strip()


def refresh_reference_data(client: ComtradeClient | None = None) -> dict[str, int]:
    """Download and normalise the reference tables. No quota is consumed:
    these are static files, not metered API calls."""
    settings = get_settings()
    settings.ensure_dirs()
    owns = client is None
    client = client or ComtradeClient()
    counts: dict[str, int] = {}
    try:
        counts["reporters"] = _write_reporters(client, settings.refs_dir)
        counts["partners"] = _write_partners(client, settings.refs_dir)
        counts["hs"] = _write_hs(client, settings.refs_dir)
        counts["codes"] = _write_codes(client, settings.refs_dir)
    finally:
        if owns:
            client.close()
    state.bump_dataset_version("refs", "all", sum(counts.values()))
    log.info("reference data refreshed", extra=counts)
    return counts


def _write_reporters(client: ComtradeClient, out_dir: Path) -> int:
    payload = client.fetch_reference("Reporters.json")
    rows = payload.get("results", [])
    frame = pl.DataFrame(
        [
            {
                "reporter_code": int(r["reporterCode"]),
                "name": (r.get("reporterDesc") or r.get("text") or "").strip(),
                "iso2": (r.get("reporterCodeIsoAlpha2") or "").strip() or None,
                "iso3": (r.get("reporterCodeIsoAlpha3") or "").strip() or None,
                "is_group": bool(r.get("isGroup")),
                # Historical territories reuse the ISO code of their successor
                # (280 "Fed. Rep. of Germany (...1990)" is also DEU), so an
                # expiry date is what distinguishes them.
                "expired": bool(r.get("entryExpiredDate")),
                "valid_from": (r.get("entryEffectiveDate") or "")[:10] or None,
                "valid_to": (r.get("entryExpiredDate") or "")[:10] or None,
                "note": (r.get("reporterNote") or "").strip() or None,
            }
            for r in rows
            if r.get("reporterCode") is not None
        ],
        schema={
            "reporter_code": pl.Int32, "name": pl.Utf8, "iso2": pl.Utf8,
            "iso3": pl.Utf8, "is_group": pl.Boolean, "expired": pl.Boolean,
            "valid_from": pl.Utf8, "valid_to": pl.Utf8, "note": pl.Utf8,
        },
    ).unique(subset=["reporter_code"]).sort("name")
    atomic_write_parquet(frame, out_dir / "reporters.parquet")
    return frame.height


def _write_partners(client: ComtradeClient, out_dir: Path) -> int:
    payload = client.fetch_reference("partnerAreas.json")
    rows = payload.get("results", [])
    frame = pl.DataFrame(
        [
            {
                "partner_code": int(r["PartnerCode"]),
                "name": (r.get("PartnerDesc") or r.get("text") or "").strip(),
                "iso2": (r.get("PartnerCodeIsoAlpha2") or "").strip() or None,
                "iso3": (r.get("PartnerCodeIsoAlpha3") or "").strip() or None,
                "is_group": bool(r.get("isGroup")),
                "expired": bool(r.get("entryExpiredDate")),
            }
            for r in rows
            if r.get("PartnerCode") is not None
        ],
        schema={
            "partner_code": pl.Int32, "name": pl.Utf8, "iso2": pl.Utf8,
            "iso3": pl.Utf8, "is_group": pl.Boolean, "expired": pl.Boolean,
        },
    ).unique(subset=["partner_code"]).sort("name")
    atomic_write_parquet(frame, out_dir / "partners.parquet")
    return frame.height


def _write_hs(client: ComtradeClient, out_dir: Path) -> int:
    payload = client.fetch_reference("HS.json")
    rows = payload.get("results", [])
    records: list[dict[str, Any]] = []
    for r in rows:
        code = str(r.get("id") or "").strip()
        if not code:
            continue
        level = int(r.get("aggrLevel") or (0 if code == "TOTAL" else len(code)))
        records.append(
            {
                "hs_code": code,
                "level": level,
                "name": _clean_name(str(r.get("text") or "")),
                "parent": (str(r.get("parent") or "").strip() or None),
                "is_leaf": str(r.get("isLeaf") or "0") == "1",
                "standard_unit": (r.get("standardUnitAbbr") or "").strip() or None,
            }
        )
    frame = pl.DataFrame(
        records,
        schema={
            "hs_code": pl.Utf8, "level": pl.Int8, "name": pl.Utf8,
            "parent": pl.Utf8, "is_leaf": pl.Boolean, "standard_unit": pl.Utf8,
        },
    ).unique(subset=["hs_code"]).sort(["level", "hs_code"])
    atomic_write_parquet(frame, out_dir / "hs.parquet")
    return frame.height


def _write_codes(client: ComtradeClient, out_dir: Path) -> int:
    """Flow, customs and mode-of-transport code lists in one small table."""
    records: list[dict[str, Any]] = []
    for filename, kind, id_field, text_field in (
        ("tradeRegimes.json", "flow", "id", "text"),
        ("CustomsCodes.json", "customs", "id", "text"),
        ("ModeOfTransportCodes.json", "mot", "id", "text"),
    ):
        try:
            payload = client.fetch_reference(filename)
        except Exception as exc:  # a missing optional list must not fail the refresh
            state.record_error("refs", f"{filename}: {exc}")
            continue
        for r in payload.get("results", []):
            records.append(
                {
                    "kind": kind,
                    "code": str(r.get(id_field) or "").strip(),
                    "name": _clean_name(str(r.get(text_field) or "")),
                }
            )
    frame = pl.DataFrame(records, schema={"kind": pl.Utf8, "code": pl.Utf8, "name": pl.Utf8})
    atomic_write_parquet(frame, out_dir / "classifications.parquet")
    return frame.height


# --------------------------------------------------------------------------
# Lookups used by the API layer
# --------------------------------------------------------------------------

def load_reporters() -> pl.DataFrame:
    path = get_settings().refs_dir / "reporters.parquet"
    if not path.exists():
        return pl.DataFrame(schema={"reporter_code": pl.Int32, "name": pl.Utf8,
                                    "iso2": pl.Utf8, "iso3": pl.Utf8,
                                    "is_group": pl.Boolean, "expired": pl.Boolean,
                                    "valid_from": pl.Utf8, "valid_to": pl.Utf8,
                                    "note": pl.Utf8})
    return pl.read_parquet(path)


def load_partners() -> pl.DataFrame:
    path = get_settings().refs_dir / "partners.parquet"
    if not path.exists():
        return pl.DataFrame(schema={"partner_code": pl.Int32, "name": pl.Utf8,
                                    "iso2": pl.Utf8, "iso3": pl.Utf8,
                                    "is_group": pl.Boolean, "expired": pl.Boolean})
    return pl.read_parquet(path)


def load_hs() -> pl.DataFrame:
    path = get_settings().refs_dir / "hs.parquet"
    if not path.exists():
        return pl.DataFrame(schema={"hs_code": pl.Utf8, "level": pl.Int8, "name": pl.Utf8,
                                    "parent": pl.Utf8, "is_leaf": pl.Boolean,
                                    "standard_unit": pl.Utf8})
    return pl.read_parquet(path)


def _prefer_current(match: pl.DataFrame) -> dict | None:
    """Several entries can share an ISO code: a current territory and one or
    more historical ones. The current territory wins unless it is the only
    thing that does not exist."""
    if match.height == 0:
        return None
    if match.height > 1 and "expired" in match.columns:
        current = match.filter(~pl.col("expired").fill_null(False))
        if current.height:
            match = current
    return match.sort("reporter_code" if "reporter_code" in match.columns else "partner_code").row(
        0, named=True
    )


def resolve_reporter(token: str) -> dict | None:
    """Accept an ISO3 code, an ISO2 code or a numeric Comtrade code."""
    token = (token or "").strip().upper()
    if not token:
        return None
    frame = load_reporters()
    if frame.height == 0:
        return None
    if token.isdigit():
        # An explicit numeric code addresses exactly one entity, historical or not.
        match = frame.filter(pl.col("reporter_code") == int(token))
        return match.row(0, named=True) if match.height else None
    if len(token) == 3:
        match = frame.filter(pl.col("iso3") == token)
    elif len(token) == 2:
        match = frame.filter(pl.col("iso2") == token)
    else:
        match = frame.filter(pl.col("name").str.to_uppercase() == token)
    return _prefer_current(match)


def resolve_partner(token: str) -> dict | None:
    token = (token or "").strip().upper()
    if not token:
        return None
    frame = load_partners()
    if frame.height == 0:
        return None
    if token.isdigit():
        match = frame.filter(pl.col("partner_code") == int(token))
        return match.row(0, named=True) if match.height else None
    if len(token) == 3:
        match = frame.filter(pl.col("iso3") == token)
    elif len(token) == 2:
        match = frame.filter(pl.col("iso2") == token)
    else:
        match = frame.filter(pl.col("name").str.to_uppercase() == token)
    return _prefer_current(match)


def hs_name(code: str) -> str | None:
    frame = load_hs().filter(pl.col("hs_code") == code)
    return frame.row(0, named=True)["name"] if frame.height else None
