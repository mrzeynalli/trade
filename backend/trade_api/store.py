"""Analytical read layer.

DuckDB scans the ZSTD Parquet partitions; column and partition pruning keep the
scans to the few columns and the single reporter a request actually needs.
Nothing in this module ever contacts Comtrade.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Sequence

import duckdb

from . import state
from .config import get_settings
from .etl import partition_path

_local = threading.local()


def connection() -> duckdb.DuckDBPyConnection:
    """One in-memory DuckDB per thread. Parquet files are the storage."""
    conn = getattr(_local, "duck", None)
    if conn is None:
        conn = duckdb.connect(":memory:")
        conn.execute("SET threads TO 2")
        conn.execute("SET enable_object_cache = true")
        _local.duck = conn
    return conn


def _query(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    cursor = connection().execute(sql, list(params))
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------

def has_dataset(dataset: str, reporter: int, freq: str, extra: dict[str, str] | None = None) -> bool:
    return _exists(partition_path(dataset, freq=freq, reporter=reporter, extra=extra))


def cached_reporters(freq: str = "A") -> list[int]:
    root = get_settings().parquet_dir / "totals" / f"freq={freq}"
    if not root.exists():
        return []
    codes = []
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith("reporter="):
            if _exists(child / "part.parquet"):
                codes.append(int(child.name.split("=", 1)[1]))
    return sorted(codes)


def period_coverage(reporter: int, freq: str) -> dict[str, Any]:
    """What the local cache actually holds, and what the source says exists."""
    path = partition_path("totals", freq=freq, reporter=reporter)
    local: dict[str, Any] = {"first": None, "last": None, "periods": 0}
    if _exists(path):
        rows = _query(
            """
            SELECT MIN(year) AS min_year, MAX(year) AS max_year,
                   COUNT(DISTINCT (CAST(year AS INTEGER) * 100 + CAST(month AS INTEGER))) AS periods
            FROM read_parquet(?)
            """,
            [str(path)],
        )
        if rows and rows[0]["periods"]:
            local = {"first": rows[0]["min_year"], "last": rows[0]["max_year"],
                     "periods": rows[0]["periods"]}

    conn = state.get_conn()
    source = conn.execute(
        """SELECT MAX(period) AS latest, MAX(last_released) AS released, COUNT(*) AS datasets
           FROM sync_state WHERE reporter_code = ? AND freq_code = ?""",
        (reporter, freq),
    ).fetchone()
    return {
        "local": local,
        "source_latest_period": source["latest"] if source else None,
        "source_last_released": source["released"] if source else None,
        "source_datasets": source["datasets"] if source else 0,
    }


def latest_period(reporter: int, freq: str) -> dict[str, Any] | None:
    """Latest period present locally, plus whether it looks complete.

    An annual year is treated as complete when the source has released it and
    the calendar year is over. A monthly period is complete by construction.
    """
    path = partition_path("totals", freq=freq, reporter=reporter)
    if not _exists(path):
        return None
    if freq == "A":
        rows = _query(
            "SELECT DISTINCT year FROM read_parquet(?) ORDER BY year DESC", [str(path)]
        )
        if not rows:
            return None
        years = [int(r["year"]) for r in rows]
        from datetime import date

        current_year = date.today().year
        complete = [y for y in years if y < current_year]
        return {
            "latest": years[0],
            "latest_complete": complete[0] if complete else None,
            "partial": years[0] >= current_year,
            "available": years,
        }
    rows = _query(
        "SELECT DISTINCT year, month FROM read_parquet(?) ORDER BY year DESC, month DESC",
        [str(path)],
    )
    if not rows:
        return None
    periods = [f"{int(r['year'])}{int(r['month']):02d}" for r in rows]
    return {"latest": periods[0], "latest_complete": periods[0], "partial": False,
            "available": periods}


# --------------------------------------------------------------------------
# Core series
# --------------------------------------------------------------------------

def totals_series(reporter: int, freq: str, *, start: int | None = None,
                  end: int | None = None) -> list[dict[str, Any]]:
    """Exports, imports and balance per period. Absent periods stay absent."""
    path = partition_path("totals", freq=freq, reporter=reporter)
    if not _exists(path):
        return []
    clauses, params = ["TRUE"], [str(path)]
    if start is not None:
        clauses.append("year >= ?")
        params.append(start)
    if end is not None:
        clauses.append("year <= ?")
        params.append(end)
    rows = _query(
        f"""
        SELECT year, month,
               MAX(CASE WHEN flow_code = 'X' THEN primary_value END) AS exports,
               MAX(CASE WHEN flow_code = 'M' THEN primary_value END) AS imports,
               MAX(CASE WHEN flow_code = 'X' THEN net_weight END) AS export_weight,
               MAX(CASE WHEN flow_code = 'M' THEN net_weight END) AS import_weight
        FROM read_parquet(?)
        WHERE {' AND '.join(clauses)}
        GROUP BY year, month
        ORDER BY year, month
        """,
        params,
    )
    out = []
    for row in rows:
        exports, imports = row["exports"], row["imports"]
        out.append(
            {
                "period": _period_label(freq, row["year"], row["month"]),
                "year": int(row["year"]),
                "month": int(row["month"]) or None,
                "exports": exports,
                "imports": imports,
                "balance": (exports - imports) if exports is not None and imports is not None else None,
                "export_weight": row["export_weight"],
                "import_weight": row["import_weight"],
            }
        )
    return out


def _period_label(freq: str, year: Any, month: Any) -> str:
    return f"{int(year)}" if freq == "A" else f"{int(year)}{int(month):02d}"


def _period_filter(freq: str, periods: Sequence[str]) -> tuple[str, list[Any]]:
    if freq == "A":
        return "year IN (" + ",".join("?" * len(periods)) + ")", [int(p) for p in periods]
    pairs = [(int(p[:4]), int(p[4:])) for p in periods]
    clause = " OR ".join(["(year = ? AND month = ?)"] * len(pairs))
    flat: list[Any] = []
    for year, month in pairs:
        flat.extend([year, month])
    return f"({clause})", flat


# --------------------------------------------------------------------------
# Rankings
# --------------------------------------------------------------------------

def product_ranking(
    reporter: int, freq: str, periods: Sequence[str], flow: str, *,
    level: int = 2, top_n: int = 10,
) -> dict[str, Any]:
    """Top-N HS categories plus an explicit ``Other`` remainder."""
    dataset = "products_hs2" if level == 2 else "products_hs4"
    path = partition_path(dataset, freq=freq, reporter=reporter)
    if not _exists(path) or not periods:
        return {"items": [], "other": None, "total": None, "available": False}

    clause, params = _period_filter(freq, periods)
    rows = _query(
        f"""
        SELECT hs_code, SUM(primary_value) AS value,
               SUM(net_weight) AS weight
        FROM read_parquet(?)
        WHERE flow_code = ? AND hs_level = ? AND {clause}
        GROUP BY hs_code
        HAVING SUM(primary_value) IS NOT NULL
        ORDER BY value DESC
        """,
        [str(path), flow, level, *params],
    )
    return _rank_payload(rows, "hs_code", top_n)


def partner_ranking(
    reporter: int, freq: str, periods: Sequence[str], flow: str, *, top_n: int = 10,
) -> dict[str, Any]:
    path = partition_path("partners", freq=freq, reporter=reporter)
    if not _exists(path) or not periods:
        return {"items": [], "other": None, "total": None, "available": False}
    clause, params = _period_filter(freq, periods)
    rows = _query(
        f"""
        SELECT partner_code, SUM(primary_value) AS value, SUM(net_weight) AS weight
        FROM read_parquet(?)
        WHERE flow_code = ? AND {clause}
        GROUP BY partner_code
        ORDER BY value DESC
        """,
        [str(path), flow, *params],
    )
    return _rank_payload(rows, "partner_code", top_n)


def _rank_payload(rows: list[dict[str, Any]], key: str, top_n: int) -> dict[str, Any]:
    total = sum(float(r["value"]) for r in rows if r["value"] is not None)
    head = rows[:top_n]
    covered = sum(float(r["value"]) for r in head if r["value"] is not None)
    remainder = total - covered
    return {
        "items": [
            {
                "key": r[key] if isinstance(r[key], str) else int(r[key]),
                "value": float(r["value"]),
                "share": (float(r["value"]) / total) if total > 0 else None,
                "weight": float(r["weight"]) if r["weight"] is not None else None,
            }
            for r in head
        ],
        "other": {"value": remainder, "share": (remainder / total) if total > 0 else None,
                  "count": max(0, len(rows) - len(head))} if len(rows) > len(head) else None,
        "total": total if rows else None,
        "count": len(rows),
        "available": bool(rows),
    }


def full_ranking(reporter: int, freq: str, periods: Sequence[str], flow: str,
                 kind: str, level: int = 2) -> list[dict[str, Any]]:
    """Every category, for the "view all" table."""
    if kind == "partners":
        payload = partner_ranking(reporter, freq, periods, flow, top_n=10_000)
    else:
        payload = product_ranking(reporter, freq, periods, flow, level=level, top_n=10_000)
    return payload["items"]


# --------------------------------------------------------------------------
# Series by product / partner
# --------------------------------------------------------------------------

def product_series(reporter: int, freq: str, hs_code: str, flow: str | None = None) -> list[dict[str, Any]]:
    dataset = "products_hs2" if len(hs_code) == 2 else "products_hs4"
    path = partition_path(dataset, freq=freq, reporter=reporter)
    if not _exists(path):
        return []
    rows = _query(
        """
        SELECT year, month,
               MAX(CASE WHEN flow_code = 'X' THEN primary_value END) AS exports,
               MAX(CASE WHEN flow_code = 'M' THEN primary_value END) AS imports,
               MAX(CASE WHEN flow_code = 'X' THEN net_weight END) AS export_weight,
               MAX(CASE WHEN flow_code = 'M' THEN net_weight END) AS import_weight
        FROM read_parquet(?)
        WHERE hs_code = ?
        GROUP BY year, month ORDER BY year, month
        """,
        [str(path), hs_code],
    )
    return [
        {
            "period": _period_label(freq, r["year"], r["month"]),
            "year": int(r["year"]), "month": int(r["month"]) or None,
            "exports": r["exports"], "imports": r["imports"],
            "export_weight": r["export_weight"], "import_weight": r["import_weight"],
        }
        for r in rows
    ]


def product_children(reporter: int, freq: str, parent_hs2: str,
                     periods: Sequence[str], flow: str, top_n: int = 12) -> dict[str, Any]:
    """HS4 breakdown inside an HS2 chapter."""
    path = partition_path("products_hs4", freq=freq, reporter=reporter)
    if not _exists(path) or not periods:
        return {"items": [], "other": None, "total": None, "available": False}
    clause, params = _period_filter(freq, periods)
    rows = _query(
        f"""
        SELECT hs_code, SUM(primary_value) AS value, SUM(net_weight) AS weight
        FROM read_parquet(?)
        WHERE flow_code = ? AND hs_level = 4 AND starts_with(hs_code, ?) AND {clause}
        GROUP BY hs_code ORDER BY value DESC
        """,
        [str(path), flow, parent_hs2, *params],
    )
    return _rank_payload(rows, "hs_code", top_n)


def product_partner_ranking(reporter: int, freq: str, hs_code: str,
                            periods: Sequence[str], flow: str, top_n: int = 10) -> dict[str, Any]:
    path = partition_path("product_partner", freq=freq, reporter=reporter,
                          extra={"hs": hs_code})
    if not _exists(path) or not periods:
        return {"items": [], "other": None, "total": None, "available": False}
    clause, params = _period_filter(freq, periods)
    rows = _query(
        f"""
        SELECT partner_code, SUM(primary_value) AS value, SUM(net_weight) AS weight
        FROM read_parquet(?)
        WHERE flow_code = ? AND hs_code = ? AND {clause}
        GROUP BY partner_code ORDER BY value DESC
        """,
        [str(path), flow, hs_code, *params],
    )
    return _rank_payload(rows, "partner_code", top_n)


def partner_series(reporter: int, freq: str, partner: int) -> list[dict[str, Any]]:
    path = partition_path("partners", freq=freq, reporter=reporter)
    if not _exists(path):
        return []
    rows = _query(
        """
        SELECT year, month,
               MAX(CASE WHEN flow_code = 'X' THEN primary_value END) AS exports,
               MAX(CASE WHEN flow_code = 'M' THEN primary_value END) AS imports
        FROM read_parquet(?)
        WHERE partner_code = ?
        GROUP BY year, month ORDER BY year, month
        """,
        [str(path), partner],
    )
    return [
        {
            "period": _period_label(freq, r["year"], r["month"]),
            "year": int(r["year"]), "month": int(r["month"]) or None,
            "exports": r["exports"], "imports": r["imports"],
            "balance": (r["exports"] - r["imports"])
            if r["exports"] is not None and r["imports"] is not None else None,
        }
        for r in rows
    ]


def partner_product_ranking(reporter: int, freq: str, partner: int,
                            periods: Sequence[str], flow: str, top_n: int = 10) -> dict[str, Any]:
    path = partition_path("partner_products", freq=freq, reporter=reporter,
                          extra={"partner": f"{partner:03d}"})
    if not _exists(path) or not periods:
        return {"items": [], "other": None, "total": None, "available": False}
    clause, params = _period_filter(freq, periods)
    rows = _query(
        f"""
        SELECT hs_code, SUM(primary_value) AS value, SUM(net_weight) AS weight
        FROM read_parquet(?)
        WHERE flow_code = ? AND hs_level = 2 AND {clause}
        GROUP BY hs_code ORDER BY value DESC
        """,
        [str(path), flow, *params],
    )
    return _rank_payload(rows, "hs_code", top_n)


# --------------------------------------------------------------------------
# Global matrix
# --------------------------------------------------------------------------

def global_year_path(year: int) -> Path:
    return partition_path("global_hs2", freq="", reporter=None, extra={"year": str(year)})


def global_years() -> list[int]:
    root = get_settings().parquet_dir / "global_hs2"
    if not root.exists():
        return []
    years = []
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith("year=") and _exists(child / "part.parquet"):
            years.append(int(child.name.split("=", 1)[1]))
    return sorted(years)


def global_product_totals(year: int, flow: str = "X") -> dict[str, float]:
    path = global_year_path(year)
    if not _exists(path):
        return {}
    rows = _query(
        "SELECT hs_code, SUM(primary_value) AS value FROM read_parquet(?) "
        "WHERE flow_code = ? GROUP BY hs_code",
        [str(path), flow],
    )
    return {r["hs_code"]: float(r["value"]) for r in rows if r["value"] is not None}


def global_reporter_products(year: int, reporter: int, flow: str = "X") -> dict[str, float]:
    path = global_year_path(year)
    if not _exists(path):
        return {}
    rows = _query(
        "SELECT hs_code, SUM(primary_value) AS value FROM read_parquet(?) "
        "WHERE flow_code = ? AND reporter_code = ? GROUP BY hs_code",
        [str(path), flow, reporter],
    )
    return {r["hs_code"]: float(r["value"]) for r in rows if r["value"] is not None}


def global_coverage(year: int) -> dict[str, Any]:
    path = global_year_path(year)
    if not _exists(path):
        return {"reporters": 0, "available": False}
    rows = _query(
        "SELECT COUNT(DISTINCT reporter_code) AS reporters, SUM(primary_value) AS total "
        "FROM read_parquet(?) WHERE flow_code = 'X'",
        [str(path)],
    )
    version = state.dataset_version("global_hs2", f"year={year}")
    coverage = {}
    if version and version.get("coverage_json"):
        import orjson

        coverage = orjson.loads(version["coverage_json"])
    return {
        "reporters": int(rows[0]["reporters"]) if rows else 0,
        "world_export_total": float(rows[0]["total"]) if rows and rows[0]["total"] else None,
        "available": True,
        **coverage,
    }


def global_reporter_shares(year: int, flow: str = "X") -> dict[int, dict[str, float]]:
    """Product-share vector per reporter, used for export-similarity search."""
    path = global_year_path(year)
    if not _exists(path):
        return {}
    rows = _query(
        "SELECT reporter_code, hs_code, SUM(primary_value) AS value FROM read_parquet(?) "
        "WHERE flow_code = ? GROUP BY reporter_code, hs_code",
        [str(path), flow],
    )
    totals: dict[int, float] = {}
    for row in rows:
        totals[int(row["reporter_code"])] = totals.get(int(row["reporter_code"]), 0.0) + float(row["value"] or 0)
    out: dict[int, dict[str, float]] = {}
    for row in rows:
        reporter = int(row["reporter_code"])
        total = totals.get(reporter, 0.0)
        if total <= 0:
            continue
        out.setdefault(reporter, {})[row["hs_code"]] = float(row["value"] or 0) / total
    return out
