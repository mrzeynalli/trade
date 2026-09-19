"""SQLite control plane (WAL).

Holds every piece of mutable state that is *not* an analytical fact:
raw-response index, the API call ledger, the daily quota ledger, dataset
versions, the durable job queue, sync state and errors.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=10000;

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key       TEXT PRIMARY KEY,
    endpoint        TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    path            TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    content_length  INTEGER NOT NULL,
    record_count    INTEGER NOT NULL,
    truncated       INTEGER NOT NULL DEFAULT 0,
    source_published TEXT,
    fetched_at      TEXT NOT NULL,
    superseded_path TEXT,
    superseded_sha  TEXT
);

CREATE TABLE IF NOT EXISTS api_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT NOT NULL,
    request_type    TEXT NOT NULL,
    cache_key       TEXT NOT NULL,
    reporter        TEXT,
    partner         TEXT,
    frequency       TEXT,
    periods         TEXT,
    cmd_level       TEXT,
    cmd_code        TEXT,
    http_status     INTEGER,
    duration_ms     INTEGER,
    record_count    INTEGER,
    compressed_bytes INTEGER,
    cache_status    TEXT NOT NULL,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_calls_ts ON api_calls(ts_utc);

CREATE TABLE IF NOT EXISTS quota_ledger (
    day             TEXT PRIMARY KEY,
    calls_made      INTEGER NOT NULL DEFAULT 0,
    backfill_calls  INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    dataset_code    TEXT PRIMARY KEY,
    type_code       TEXT NOT NULL,
    freq_code       TEXT NOT NULL,
    reporter_code   INTEGER NOT NULL,
    period          INTEGER NOT NULL,
    classification  TEXT,
    total_records   INTEGER,
    checksum        TEXT,
    first_released  TEXT,
    last_released   TEXT,
    seen_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_reporter ON sync_state(reporter_code, freq_code);

CREATE TABLE IF NOT EXISTS dataset_versions (
    dataset         TEXT NOT NULL,
    scope           TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    rows            INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL,
    source_released TEXT,
    coverage_json   TEXT,
    PRIMARY KEY (dataset, scope)
);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key         TEXT NOT NULL,
    kind            TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 50,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INTEGER NOT NULL DEFAULT 0,
    progress        TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    error           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active
    ON jobs(job_key) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, priority, id);

CREATE TABLE IF NOT EXISTS cache_invalidations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    scope           TEXT NOT NULL,
    reason          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT NOT NULL,
    context         TEXT NOT NULL,
    message         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_heartbeat (
    worker_id       TEXT PRIMARY KEY,
    ts_utc          TEXT NOT NULL,
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_rate (
    client          TEXT NOT NULL,
    hour            TEXT NOT NULL,
    count           INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (client, hour)
);
"""

_local = threading.local()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seconds_since(stamp: str | None) -> float | None:
    """Age in seconds of an `utcnow()` timestamp, or None if unparseable.

    Timestamps written before this process started may be naive, so a missing
    timezone is read as UTC rather than raising.
    """
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def today() -> str:
    return date.today().isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    db_path = path or settings.state_db
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_conn() -> sqlite3.Connection:
    """Thread-local connection. SQLite objects are not shareable across threads."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def reset_thread_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None


@contextmanager
def transaction(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    conn = conn or get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --------------------------------------------------------------------------
# Quota ledger
# --------------------------------------------------------------------------

def quota_today(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    conn = conn or get_conn()
    row = conn.execute("SELECT * FROM quota_ledger WHERE day = ?", (today(),)).fetchone()
    if row is None:
        return {"calls_made": 0, "backfill_calls": 0}
    return {"calls_made": row["calls_made"], "backfill_calls": row["backfill_calls"]}


def quota_reserve(kind: str = "normal", conn: sqlite3.Connection | None = None) -> bool:
    """Atomically claim one call from today's budget.

    ``kind`` is one of ``interactive`` (may dip into the reserve),
    ``backfill`` (also limited by its own daily sub-budget) or ``normal``.
    Returns False when the request must not be made.
    """
    settings = get_settings()
    conn = conn or get_conn()
    soft_cap = settings.daily_call_budget
    normal_cap = max(0, soft_cap - settings.interactive_reserve)
    with transaction(conn):
        row = conn.execute(
            "SELECT calls_made, backfill_calls FROM quota_ledger WHERE day = ?", (today(),)
        ).fetchone()
        made = row["calls_made"] if row else 0
        backfill = row["backfill_calls"] if row else 0

        if made >= soft_cap:
            return False
        if kind != "interactive" and made >= normal_cap:
            return False
        if kind == "backfill" and backfill >= settings.global_backfill_daily_budget:
            return False

        conn.execute(
            """
            INSERT INTO quota_ledger(day, calls_made, backfill_calls, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                calls_made = calls_made + 1,
                backfill_calls = backfill_calls + excluded.backfill_calls,
                updated_at = excluded.updated_at
            """,
            (today(), 1 if kind == "backfill" else 0, utcnow()),
        )
    return True


def quota_release(kind: str = "normal", conn: sqlite3.Connection | None = None) -> None:
    """Give a reserved call back when the request was never actually sent."""
    conn = conn or get_conn()
    with transaction(conn):
        conn.execute(
            """UPDATE quota_ledger
               SET calls_made = MAX(0, calls_made - 1),
                   backfill_calls = MAX(0, backfill_calls - ?),
                   updated_at = ?
               WHERE day = ?""",
            (1 if kind == "backfill" else 0, utcnow(), today()),
        )


# --------------------------------------------------------------------------
# Dataset versions
# --------------------------------------------------------------------------

def bump_dataset_version(
    dataset: str,
    scope: str,
    rows: int,
    source_released: str | None = None,
    coverage: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    conn = conn or get_conn()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO dataset_versions(dataset, scope, version, rows, updated_at,
                                         source_released, coverage_json)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(dataset, scope) DO UPDATE SET
                version = dataset_versions.version + 1,
                rows = excluded.rows,
                updated_at = excluded.updated_at,
                source_released = COALESCE(excluded.source_released,
                                           dataset_versions.source_released),
                coverage_json = COALESCE(excluded.coverage_json,
                                         dataset_versions.coverage_json)
            """,
            (
                dataset,
                scope,
                rows,
                utcnow(),
                source_released,
                json.dumps(coverage) if coverage else None,
            ),
        )
        row = conn.execute(
            "SELECT version FROM dataset_versions WHERE dataset = ? AND scope = ?",
            (dataset, scope),
        ).fetchone()
    return int(row["version"])


def dataset_version(dataset: str, scope: str, conn: sqlite3.Connection | None = None) -> dict | None:
    conn = conn or get_conn()
    row = conn.execute(
        "SELECT * FROM dataset_versions WHERE dataset = ? AND scope = ?", (dataset, scope)
    ).fetchone()
    return dict(row) if row else None


def dataset_versions_for(scopes: list[tuple[str, str]], conn: sqlite3.Connection | None = None) -> str:
    """Compose a compact composite version token for ETag generation."""
    conn = conn or get_conn()
    parts: list[str] = []
    for dataset, scope in scopes:
        row = conn.execute(
            "SELECT version, updated_at FROM dataset_versions WHERE dataset=? AND scope=?",
            (dataset, scope),
        ).fetchone()
        parts.append(f"{dataset}:{scope}:{row['version'] if row else 0}")
    return "|".join(parts)


def record_invalidation(dataset: str, scope: str, reason: str,
                        conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    conn.execute(
        "INSERT INTO cache_invalidations(ts_utc, dataset, scope, reason) VALUES (?,?,?,?)",
        (utcnow(), dataset, scope, reason),
    )


def record_error(context: str, message: str, conn: sqlite3.Connection | None = None) -> None:
    from .config import redact

    conn = conn or get_conn()
    conn.execute(
        "INSERT INTO errors(ts_utc, context, message) VALUES (?,?,?)",
        (utcnow(), context, redact(message)[:4000]),
    )


def heartbeat(worker_id: str, status: str = "alive", conn: sqlite3.Connection | None = None) -> None:
    conn = conn or get_conn()
    conn.execute(
        """INSERT INTO worker_heartbeat(worker_id, ts_utc, status) VALUES (?,?,?)
           ON CONFLICT(worker_id) DO UPDATE SET ts_utc=excluded.ts_utc, status=excluded.status""",
        (worker_id, utcnow(), status),
    )
    # Retire heartbeats from workers that have not been seen for a day.
    conn.execute(
        "DELETE FROM worker_heartbeat WHERE worker_id != ? AND ts_utc < datetime('now', '-1 day')",
        (worker_id,),
    )


def worker_status(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Heartbeats, newest first. A restart leaves the previous worker's final
    row behind, so ordering matters for reporting the live one."""
    conn = conn or get_conn()
    rows = conn.execute(
        "SELECT * FROM worker_heartbeat ORDER BY ts_utc DESC, worker_id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def allow_job_creation(client: str, conn: sqlite3.Connection | None = None) -> bool:
    """Per-client hourly ceiling on job creation, so a visitor cannot drain quota."""
    settings = get_settings()
    conn = conn or get_conn()
    hour = time.strftime("%Y-%m-%dT%H", time.gmtime())
    with transaction(conn):
        row = conn.execute(
            "SELECT count FROM job_rate WHERE client=? AND hour=?", (client, hour)
        ).fetchone()
        current = row["count"] if row else 0
        if current >= settings.job_rate_limit_per_hour:
            return False
        conn.execute(
            """INSERT INTO job_rate(client, hour, count) VALUES (?,?,1)
               ON CONFLICT(client, hour) DO UPDATE SET count = count + 1""",
            (client, hour),
        )
        conn.execute("DELETE FROM job_rate WHERE hour < ?", (hour,))
    return True
