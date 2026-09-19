"""Durable job queue on SQLite.

A logical unit of work has exactly one active row: the partial unique index on
``job_key`` means twenty simultaneous visitors on the same country produce one
job, not twenty.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

import orjson

from . import state
from .logging_setup import get_logger

log = get_logger("trade.jobs")

# Lower runs first. Mirrors the documented priority order.
PRIORITY = {
    "country_annual": 10,      # a user is waiting on a country summary
    "country_monthly": 15,
    "product_partners": 20,    # a user opened a drilldown
    "partner_products": 20,
    "country_hs4": 25,
    "mirror": 25,
    "refresh_changed": 30,     # source says a dataset we hold was revised
    "nightly_refresh": 40,
    "refs": 40,
    "advanced": 50,
    "global_hs2": 60,          # background global backfill, lowest
}

TERMINAL = {"done", "failed", "cancelled"}


def make_key(kind: str, payload: dict[str, Any]) -> str:
    blob = orjson.dumps({"kind": kind, **payload}, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(blob).hexdigest()[:32]


def enqueue(kind: str, payload: dict[str, Any], *, priority: int | None = None,
            conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Create the job, or return the existing active one with the same key."""
    conn = conn or state.get_conn()
    key = make_key(kind, payload)
    existing = conn.execute(
        "SELECT * FROM jobs WHERE job_key = ? AND status IN ('queued','running') "
        "ORDER BY id DESC LIMIT 1",
        (key,),
    ).fetchone()
    if existing is not None:
        return {**dict(existing), "deduplicated": True}

    cursor = conn.execute(
        """INSERT INTO jobs(job_key, kind, payload_json, priority, status, created_at)
           VALUES (?,?,?,?, 'queued', ?)""",
        (key, kind, orjson.dumps(payload).decode(),
         priority if priority is not None else PRIORITY.get(kind, 50), state.utcnow()),
    )
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    log.info("job enqueued", extra={"job_id": row["id"], "kind": kind, "job_key": key})
    return {**dict(row), "deduplicated": False}


def claim(conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Atomically take the highest-priority queued job."""
    conn = conn or state.get_conn()
    with state.transaction(conn):
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY priority ASC, id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
            (state.utcnow(), row["id"]),
        )
    return dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())


def set_progress(job_id: int, message: str, conn: sqlite3.Connection | None = None) -> None:
    conn = conn or state.get_conn()
    conn.execute("UPDATE jobs SET progress = ? WHERE id = ?", (message[:500], job_id))


def finish(job_id: int, status: str, error: str | None = None,
           conn: sqlite3.Connection | None = None) -> None:
    from .config import redact

    conn = conn or state.get_conn()
    conn.execute(
        "UPDATE jobs SET status=?, finished_at=?, error=? WHERE id=?",
        (status, state.utcnow(), redact(error)[:2000] if error else None, job_id),
    )


def get(job_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    conn = conn or state.get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def find_active(kind: str, payload: dict[str, Any],
                conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    conn = conn or state.get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_key = ? AND status IN ('queued','running') "
        "ORDER BY id DESC LIMIT 1",
        (make_key(kind, payload),),
    ).fetchone()
    return dict(row) if row else None


def find_latest(kind: str, payload: dict[str, Any],
                conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """The most recent job for a key, whatever its status.

    `find_active` deliberately ignores terminal jobs, which is right for
    de-duplication but wrong for deciding what to tell a caller: a job that has
    failed is invisible to it, so the caller re-queues, the new job fails the
    same way, and the client polls forever.
    """
    conn = conn or state.get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_key = ? ORDER BY id DESC LIMIT 1",
        (make_key(kind, payload),),
    ).fetchone()
    return dict(row) if row else None


def summary(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    conn = conn or state.get_conn()
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def recent(limit: int = 20, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    conn = conn or state.get_conn()
    rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def retry_failed(conn: sqlite3.Connection | None = None) -> int:
    conn = conn or state.get_conn()
    with state.transaction(conn):
        rows = conn.execute("SELECT id, job_key FROM jobs WHERE status = 'failed'").fetchall()
        requeued = 0
        for row in rows:
            active = conn.execute(
                "SELECT 1 FROM jobs WHERE job_key = ? AND status IN ('queued','running')",
                (row["job_key"],),
            ).fetchone()
            if active:
                continue
            conn.execute(
                "UPDATE jobs SET status='queued', error=NULL, started_at=NULL, finished_at=NULL "
                "WHERE id=?",
                (row["id"],),
            )
            requeued += 1
    return requeued


def reset_orphans(conn: sqlite3.Connection | None = None) -> int:
    """Requeue jobs left 'running' by a killed worker."""
    conn = conn or state.get_conn()
    cursor = conn.execute(
        "UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'"
    )
    return cursor.rowcount or 0
