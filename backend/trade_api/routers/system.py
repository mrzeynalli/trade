"""Job status and health."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from .. import etl, jobs, state, store
from ..cache import get_cache
from ..config import get_settings

router = APIRouter(tags=["system"])


@router.get("/job/{job_id}")
def job_status(job_id: int) -> Any:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return {
        "data": {
            "id": job["id"],
            "kind": job["kind"],
            "status": job["status"],
            "progress": job["progress"],
            "attempts": job["attempts"],
            "created_at": job["created_at"],
            "finished_at": job["finished_at"],
            # The error string has already passed through redaction on write.
            "error": job["error"],
        },
        "meta": {"source": "local"},
    }


@router.get("/health")
def health(response: Response) -> Any:
    """Internal health. Comtrade availability is deliberately not a dependency:
    the site is healthy whenever it can serve its local cache."""
    settings = get_settings()
    checks: dict[str, Any] = {}
    healthy = True

    try:
        conn = state.get_conn()
        conn.execute("SELECT 1").fetchone()
        checks["sqlite"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["sqlite"] = f"error: {type(exc).__name__}"
        healthy = False

    checks["data_dir"] = "ok" if settings.data_dir.exists() else "missing"
    if checks["data_dir"] != "ok":
        healthy = False

    try:
        reporters = store.cached_reporters("A")
        if reporters:
            store.totals_series(reporters[0], "A")
        checks["duckdb"] = "ok"
        checks["cached_countries"] = len(reporters)
    except Exception as exc:  # noqa: BLE001
        checks["duckdb"] = f"error: {type(exc).__name__}"
        healthy = False

    beats = state.worker_status()
    checks["worker"] = beats[0]["ts_utc"] if beats else "never"
    checks["worker_status"] = beats[0]["status"] if beats else "unknown"

    usage = shutil.disk_usage(settings.data_dir)
    free_percent = round(100 * usage.free / usage.total, 2)
    checks["disk_free_percent"] = free_percent
    if free_percent < (100 - settings.disk_warn_percent):
        checks["disk"] = "low"

    checks["quota"] = state.quota_today()
    checks["jobs"] = jobs.summary()
    checks["response_cache"] = get_cache().stats()

    if not healthy:
        response.status_code = 503
    return {"data": {"status": "ok" if healthy else "degraded", "checks": checks},
            "meta": {"source": "local"}}
