"""Normalisation of raw Comtrade rows into compact Parquet facts.

Design notes
------------
* Fact tables carry codes and numbers only; names live in ``refs/``.
* ``hs_code`` is stored as a dictionary-encoded string rather than an integer.
  Dictionary encoding makes it as compact as an integer on disk while making
  it impossible to lose a leading zero ("01" must never become 1).
* Partitioning is ``<dataset>/freq=<A|M>/reporter=<NNN>/part.parquet`` with
  ``year`` kept as a sorted column. A per-year partition would produce files
  of two rows for annual totals, which is the "millions of tiny files"
  failure mode; a single reporter file is a few tens of kilobytes and is what
  the dominant access pattern (one selected country) actually reads.
* Every write is atomic: temp file, fsync, rename, then version bump.
* A value that the source did not report is absent, never zero.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import polars as pl

from . import state
from .config import get_settings
from .logging_setup import get_logger

log = get_logger("trade.etl")

FLOW_EXPORT = "X"
FLOW_IMPORT = "M"

FACT_SCHEMA: dict[str, pl.DataType] = {
    "reporter_code": pl.Int32,
    "partner_code": pl.Int32,
    "year": pl.Int16,
    "month": pl.Int8,
    "flow_code": pl.Categorical,
    "hs_level": pl.Int8,
    "hs_code": pl.Utf8,
    "primary_value": pl.Float64,
    "net_weight": pl.Float64,
    "quantity": pl.Float64,
    "quantity_unit": pl.Utf8,
    "classification": pl.Utf8,
    "is_aggregate": pl.Boolean,
    "is_reported": pl.Boolean,
}


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    key_columns: tuple[str, ...]


DATASETS: dict[str, DatasetSpec] = {
    "totals": DatasetSpec("totals", ("reporter_code", "year", "month", "flow_code")),
    "products_hs2": DatasetSpec("products_hs2", ("reporter_code", "year", "month", "flow_code", "hs_code")),
    "products_hs4": DatasetSpec("products_hs4", ("reporter_code", "year", "month", "flow_code", "hs_code")),
    "partners": DatasetSpec("partners", ("reporter_code", "partner_code", "year", "month", "flow_code")),
    "product_partner": DatasetSpec(
        "product_partner",
        ("reporter_code", "partner_code", "year", "month", "flow_code", "hs_code"),
    ),
    "partner_products": DatasetSpec(
        "partner_products",
        ("reporter_code", "partner_code", "year", "month", "flow_code", "hs_code"),
    ),
    "global_hs2": DatasetSpec("global_hs2", ("reporter_code", "year", "flow_code", "hs_code")),
}


# --------------------------------------------------------------------------
# Atomic Parquet IO
# --------------------------------------------------------------------------

def atomic_write_parquet(frame: pl.DataFrame, destination: Path, compression: str = "zstd") -> Path:
    """Write ``frame`` so that a reader never observes a partial file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.tmp{os.getpid()}.{time.time_ns()}")
    try:
        frame.write_parquet(
            tmp,
            compression=compression,
            compression_level=9 if compression == "zstd" else None,
            statistics=True,
        )
        with open(tmp, "rb") as handle:
            os.fsync(handle.fileno())
        tmp.replace(destination)
        dir_fd = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return destination


def partition_path(dataset: str, *, freq: str, reporter: int | None = None,
                   extra: dict[str, str] | None = None) -> Path:
    settings = get_settings()
    path = settings.parquet_dir / dataset
    if freq:
        path = path / f"freq={freq}"
    if reporter is not None:
        path = path / f"reporter={reporter:03d}"
    for key, value in (extra or {}).items():
        path = path / f"{key}={value}"
    return path / "part.parquet"


# --------------------------------------------------------------------------
# Row normalisation
# --------------------------------------------------------------------------

def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _optional_measure(value: Any) -> float | None:
    """Comtrade uses 0.0 as a filler for "not reported" in weight/quantity.

    A genuine zero net weight is not meaningful for a positive trade value, so
    zero is treated as absent here. Trade *values* are never coerced this way.
    """
    number = _to_float(value)
    if number is None or number <= 0:
        return None
    return number


def normalise_rows(rows: Iterable[dict[str, Any]]) -> pl.DataFrame:
    """Turn raw Comtrade JSON records into the canonical fact frame."""
    records: list[dict[str, Any]] = []
    for row in rows:
        flow = str(row.get("flowCode") or "").strip().upper()
        if flow not in {"X", "M", "RX", "DX", "RM", "MIP", "XIP"}:
            continue
        value = _to_float(row.get("primaryValue"))
        if value is None:
            # No reported value: skip rather than inventing a zero.
            continue
        period = str(row.get("period") or "")
        ref_year = row.get("refYear")
        if ref_year is None and len(period) >= 4:
            ref_year = period[:4]
        try:
            year = int(ref_year)
        except (TypeError, ValueError):
            continue
        freq = str(row.get("freqCode") or "A").upper()
        month = 0
        if freq == "M":
            if len(period) == 6 and period.isdigit():
                month = int(period[4:])
            else:
                raw_month = row.get("refMonth")
                month = int(raw_month) if raw_month not in (None, 52) else 0
            if not 1 <= month <= 12:
                continue
        cmd = str(row.get("cmdCode") or "TOTAL").strip()
        hs_level = 0 if cmd == "TOTAL" else len(cmd)
        records.append(
            {
                "reporter_code": int(row.get("reporterCode") or 0),
                "partner_code": int(row.get("partnerCode") if row.get("partnerCode") is not None else -1),
                "year": year,
                "month": month,
                "flow_code": flow,
                "hs_level": hs_level,
                "hs_code": cmd,
                "primary_value": value,
                "net_weight": _optional_measure(row.get("netWgt")),
                "quantity": _optional_measure(row.get("qty")),
                "quantity_unit": (str(row.get("qtyUnitAbbr")).strip()
                                  if row.get("qtyUnitAbbr") not in (None, "", "N/A") else None),
                "classification": str(row.get("classificationCode") or "").strip() or None,
                "is_aggregate": bool(row.get("isAggregate")),
                "is_reported": bool(row.get("isReported")),
            }
        )
    if not records:
        return pl.DataFrame(schema=FACT_SCHEMA)
    frame = pl.DataFrame(records, schema_overrides={
        "reporter_code": pl.Int32, "partner_code": pl.Int32, "year": pl.Int16,
        "month": pl.Int8, "hs_level": pl.Int8, "primary_value": pl.Float64,
        "net_weight": pl.Float64, "quantity": pl.Float64,
    })
    return frame.with_columns(pl.col("flow_code").cast(pl.Categorical))


# --------------------------------------------------------------------------
# Merge + persist
# --------------------------------------------------------------------------

def merge_into_partition(
    dataset: str,
    frame: pl.DataFrame,
    *,
    freq: str,
    reporter: int | None = None,
    extra: dict[str, str] | None = None,
    replace_scope: Sequence[tuple[str, list[Any]]] | None = None,
) -> tuple[Path, int]:
    """Upsert ``frame`` into a partition file and return (path, row count).

    ``replace_scope`` names the coordinates the incoming frame is authoritative
    for, e.g. ``[("year", [2024, 2025])]``. Existing rows inside that scope are
    dropped before the merge, so a source revision that *removes* a record
    removes it locally too.
    """
    spec = DATASETS[dataset]
    path = partition_path(dataset, freq=freq, reporter=reporter, extra=extra)

    incoming = frame
    if incoming.height == 0 and not replace_scope:
        return path, 0

    if path.exists():
        existing = pl.read_parquet(path)
        if replace_scope:
            mask = pl.lit(True)
            for column, values in replace_scope:
                if column not in existing.columns:
                    continue
                mask = mask & pl.col(column).is_in(values)
            existing = existing.filter(~mask)
        combined = pl.concat([existing, incoming], how="diagonal_relaxed") if incoming.height else existing
    else:
        combined = incoming

    if combined.height:
        combined = combined.unique(subset=list(spec.key_columns), keep="last")
        sort_columns = [c for c in ("year", "month", "flow_code", "hs_code",
                                    "partner_code", "reporter_code") if c in combined.columns]
        combined = combined.sort(sort_columns)

    atomic_write_parquet(combined, path)
    return path, combined.height


def scope_name(reporter: int | None, freq: str, extra: dict[str, str] | None = None) -> str:
    parts = [f"freq={freq}"]
    if reporter is not None:
        parts.append(f"reporter={reporter:03d}")
    for key, value in (extra or {}).items():
        parts.append(f"{key}={value}")
    return "/".join(parts)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

@dataclass
class ValidationReport:
    dataset: str
    scope: str
    rows: int
    issues: list[str]
    reconciliation: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not any(issue.startswith("FATAL") for issue in self.issues)


def validate_facts(
    dataset: str,
    frame: pl.DataFrame,
    *,
    scope: str,
    expect_partner: str = "any",
) -> ValidationReport:
    """Structural checks. Reconciliation differences are recorded, never forced."""
    issues: list[str] = []
    if frame.height == 0:
        return ValidationReport(dataset, scope, 0, issues, {})

    spec = DATASETS[dataset]
    duplicates = frame.height - frame.unique(subset=list(spec.key_columns)).height
    if duplicates:
        issues.append(f"{duplicates} duplicate logical records collapsed")

    if frame.select(pl.col("reporter_code").le(0).any()).item():
        issues.append("FATAL invalid reporter code (<= 0)")

    if "month" in frame.columns:
        bad_month = frame.filter(~pl.col("month").is_between(0, 12)).height
        if bad_month:
            issues.append(f"FATAL {bad_month} rows with an impossible month")

    negative = frame.filter(pl.col("primary_value") < 0).height
    if negative:
        issues.append(f"{negative} rows with a negative trade value (kept as reported)")

    if "hs_code" in frame.columns:
        malformed = frame.filter(
            (pl.col("hs_code") != "TOTAL")
            & (~pl.col("hs_code").str.contains(r"^\d+$") | ~pl.col("hs_code").str.len_chars().is_in([2, 4, 6]))
        ).height
        if malformed:
            issues.append(f"{malformed} malformed commodity codes dropped from consideration")

    if "classification" in frame.columns:
        missing_class = frame.filter(pl.col("classification").is_null()).height
        if missing_class:
            issues.append(f"{missing_class} rows without a source classification")

    if expect_partner == "world" and "partner_code" in frame.columns:
        stray = frame.filter(pl.col("partner_code") != 0).height
        if stray:
            issues.append(f"FATAL {stray} non-World partner rows in a World-scoped dataset")
    if expect_partner == "bilateral" and "partner_code" in frame.columns:
        stray = frame.filter(pl.col("partner_code") == 0).height
        if stray:
            issues.append(f"FATAL {stray} World rows in a bilateral dataset (double-count risk)")

    return ValidationReport(dataset, scope, frame.height, issues, {})


def reconcile_components(component_total: float | None, reported_total: float | None) -> dict[str, Any]:
    """Difference between a sum of components and the reported aggregate."""
    if component_total is None or reported_total is None or reported_total == 0:
        return {"component_total": component_total, "reported_total": reported_total,
                "difference": None, "relative_difference": None}
    difference = component_total - reported_total
    return {
        "component_total": component_total,
        "reported_total": reported_total,
        "difference": difference,
        "relative_difference": difference / reported_total,
    }


# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------

def compact_dataset(dataset: str) -> dict[str, Any]:
    """Rewrite every partition file of a dataset, deduplicated and sorted."""
    settings = get_settings()
    root = settings.parquet_dir / dataset
    if not root.exists():
        return {"dataset": dataset, "files": 0, "bytes_before": 0, "bytes_after": 0}
    spec = DATASETS[dataset]
    before = after = files = 0
    for path in sorted(root.rglob("part.parquet")):
        size_before = path.stat().st_size
        frame = pl.read_parquet(path)
        deduped = frame.unique(subset=list(spec.key_columns), keep="last")
        sort_columns = [c for c in ("year", "month", "flow_code", "hs_code",
                                    "partner_code", "reporter_code") if c in deduped.columns]
        atomic_write_parquet(deduped.sort(sort_columns), path)
        before += size_before
        after += path.stat().st_size
        files += 1
    return {"dataset": dataset, "files": files, "bytes_before": before, "bytes_after": after}


def cleanup_temp_files(older_than_seconds: int = 3600) -> int:
    settings = get_settings()
    removed = 0
    cutoff = time.time() - older_than_seconds
    for root in (settings.parquet_dir, settings.refs_dir, settings.raw_dir, settings.tmp_dir):
        if not root.exists():
            continue
        for path in root.rglob(".*tmp*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


def disk_usage() -> dict[str, Any]:
    settings = get_settings()

    def tree_bytes(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    usage = shutil.disk_usage(settings.data_dir)
    return {
        "raw_bytes": tree_bytes(settings.raw_dir),
        "parquet_bytes": tree_bytes(settings.parquet_dir),
        "refs_bytes": tree_bytes(settings.refs_dir),
        "state_bytes": tree_bytes(settings.data_dir / "state"),
        "total_bytes": tree_bytes(settings.data_dir),
        "disk_total": usage.total,
        "disk_free": usage.free,
        "disk_used_percent": round(100 * (usage.total - usage.free) / usage.total, 2),
    }
