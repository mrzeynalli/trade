"""Background ingestion worker.

The only process permitted to contact Comtrade. Web request handlers enqueue
work and return immediately; this loop does the downloading, transforming and
aggregate rebuilding.
"""

from __future__ import annotations

import os
import signal
import socket
import time
from typing import Any

import orjson

from . import derive, ingest, jobs, refs, state
from .comtrade import ComtradeClient, ComtradeError, QuotaExhausted
from .config import get_settings
from .logging_setup import configure_logging, get_logger

log = get_logger("trade.worker")

_running = True


def _stop(signum: int, _frame: Any) -> None:
    global _running
    _running = False
    log.info("worker stopping", extra={"signal": signum})


def handle(job: dict[str, Any], client: ComtradeClient) -> dict[str, Any]:
    kind = job["kind"]
    payload = orjson.loads(job["payload_json"])
    job_id = job["id"]

    def progress(message: str) -> None:
        jobs.set_progress(job_id, message)

    if kind == "refs":
        return refs.refresh_reference_data(client)

    if kind == "country_annual":
        reporter = int(payload["reporter"])
        results = ingest.country_annual_pack(
            client, reporter,
            start_year=payload.get("start_year"), end_year=payload.get("end_year"),
            priority=payload.get("priority", "normal"), force=bool(payload.get("force")),
            progress=progress,
        )
        progress("Recomputing derived metrics")
        derive.rebuild_all(reporter)
        return {"results": [r.__dict__ for r in results]}

    if kind == "country_monthly":
        reporter = int(payload["reporter"])
        results = ingest.country_monthly_pack(
            client, reporter, months=payload.get("months"),
            priority=payload.get("priority", "normal"), force=bool(payload.get("force")),
            progress=progress,
        )
        return {"results": [r.__dict__ for r in results]}

    if kind == "country_hs4":
        reporter = int(payload["reporter"])
        progress("Fetching HS4 detail")
        result = ingest.country_hs4_pack(client, reporter, force=bool(payload.get("force")))
        return {"results": [result.__dict__]}

    if kind == "product_partners":
        reporter = int(payload["reporter"])
        progress(f"Fetching partners for HS {payload['hs_code']}")
        result = ingest.ingest_product_partners(
            client, reporter, payload.get("freq", "A"), str(payload["hs_code"]),
            payload["periods"], force=bool(payload.get("force")),
        )
        return {"results": [result.__dict__]}

    if kind == "partner_products":
        reporter = int(payload["reporter"])
        progress("Fetching bilateral product composition")
        result = ingest.ingest_partner_products(
            client, reporter, payload.get("freq", "A"), int(payload["partner"]),
            payload["periods"], force=bool(payload.get("force")),
        )
        return {"results": [result.__dict__]}

    if kind == "mirror":
        progress("Fetching counterpart reporting")
        result = ingest.ingest_mirror(
            client, int(payload["mirror_reporter"]), int(payload["counterpart"]),
            payload.get("freq", "A"), payload["periods"], force=bool(payload.get("force")),
        )
        return {"results": [result.__dict__]}

    if kind == "global_hs2":
        progress(f"Backfilling global HS2 matrix for {payload['year']}")
        result = ingest.ingest_global_hs2(client, int(payload["year"]),
                                          force=bool(payload.get("force")))
        return {"results": [result.__dict__]}

    if kind == "advanced":
        reporter = int(payload["reporter"])
        progress("Rebuilding derived metrics")
        return derive.rebuild_all(reporter)

    if kind in ("refresh_changed", "nightly_refresh"):
        return run_sync(client, progress)

    raise ValueError(f"Unknown job kind: {kind}")


def run_sync(client: ComtradeClient, progress: Any = None) -> dict[str, Any]:
    """Source-aware refresh.

    Ask what changed recently, intersect that with what we hold locally, and
    refetch only the affected reporter/period partitions.
    """
    from . import store

    settings = get_settings()
    conn = state.get_conn()
    if progress:
        progress("Reading recent source publications")

    try:
        updates = ingest.live_updates(client)
    except ComtradeError as exc:
        state.record_error("sync", str(exc))
        updates = []

    cached_annual = set(store.cached_reporters("A"))
    cached_monthly = set(store.cached_reporters("M"))
    queued: list[dict[str, Any]] = []

    for row in updates:
        try:
            reporter = int(row.get("reporterCode"))
            freq = str(row.get("freqCode") or "A").upper()
            period = int(row.get("period"))
        except (TypeError, ValueError):
            continue
        if str(row.get("releaseStatus") or "").lower() != "released":
            continue
        relevant = cached_annual if freq == "A" else cached_monthly
        if reporter not in relevant:
            continue

        seen = conn.execute(
            "SELECT last_released FROM sync_state WHERE reporter_code=? AND freq_code=? AND period=?",
            (reporter, freq, period),
        ).fetchone()
        if seen and seen["last_released"] == row.get("lastUpdated"):
            continue

        state.record_invalidation(
            "totals", f"freq={freq}/reporter={reporter:03d}",
            f"source published {freq} {period}",
        )
        if freq == "A":
            job = jobs.enqueue("country_annual", {
                "reporter": reporter, "start_year": period, "end_year": period,
                "force": True, "priority": "normal",
            }, priority=jobs.PRIORITY["refresh_changed"])
        else:
            job = jobs.enqueue("country_monthly", {
                "reporter": reporter, "months": 12, "force": True, "priority": "normal",
            }, priority=jobs.PRIORITY["refresh_changed"])
        queued.append({"reporter": reporter, "freq": freq, "period": period,
                       "job_id": job["id"], "deduplicated": job["deduplicated"]})

    # Recent periods are checked on a schedule even without a live-update hit,
    # because the live feed only carries the most recent publications.
    if progress:
        progress("Checking recent-period availability for cached countries")
    for reporter in sorted(cached_annual)[:20]:
        try:
            availability = ingest.sync_availability(client, reporter, "A")
        except (ComtradeError, QuotaExhausted) as exc:
            state.record_error("sync_availability", f"reporter {reporter}: {exc}")
            break
        for period in availability["changed"]:
            jobs.enqueue("country_annual", {
                "reporter": reporter, "start_year": period, "end_year": period,
                "force": True,
            }, priority=jobs.PRIORITY["refresh_changed"])
            queued.append({"reporter": reporter, "freq": "A", "period": period})

    etl_removed = 0
    try:
        from .etl import cleanup_temp_files

        etl_removed = cleanup_temp_files()
    except Exception:
        pass

    return {"updates_seen": len(updates), "refreshes_queued": len(queued),
            "temp_files_removed": etl_removed}


def run_once() -> bool:
    """Process at most one job. Returns True when a job was handled."""
    job = jobs.claim()
    if job is None:
        return False
    started = time.monotonic()
    with ComtradeClient() as client:
        try:
            result = handle(job, client)
            jobs.finish(job["id"], "done")
            log.info("job done", extra={
                "job_id": job["id"], "kind": job["kind"],
                "duration_ms": int((time.monotonic() - started) * 1000),
                "result": str(result)[:400],
            })
        except QuotaExhausted as exc:
            # Not a failure: put it back for tomorrow rather than burning attempts.
            jobs.finish(job["id"], "queued", str(exc))
            state.get_conn().execute(
                "UPDATE jobs SET status='queued', finished_at=NULL WHERE id=?", (job["id"],)
            )
            log.warning("job deferred: quota", extra={"job_id": job["id"]})
            time.sleep(30)
        except Exception as exc:  # noqa: BLE001 - a bad job must not kill the worker
            status = "failed" if job["attempts"] >= 3 else "queued"
            jobs.finish(job["id"], status, f"{type(exc).__name__}: {exc}")
            state.record_error(f"job:{job['kind']}", f"{type(exc).__name__}: {exc}")
            log.error("job error", extra={"job_id": job["id"], "kind": job["kind"],
                                          "status": status, "error": str(exc)[:400]})
    return True


def main() -> None:
    configure_logging()
    settings = get_settings()
    settings.ensure_dirs()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    orphans = jobs.reset_orphans()
    log.info("worker started", extra={"worker_id": worker_id, "requeued_orphans": orphans,
                                      "data_dir": str(settings.data_dir)})

    idle_since = time.monotonic()
    while _running:
        state.heartbeat(worker_id, "alive")
        try:
            worked = run_once()
        except Exception as exc:  # noqa: BLE001
            state.record_error("worker_loop", str(exc))
            log.error("worker loop error", extra={"error": str(exc)[:400]})
            worked = False
        if worked:
            idle_since = time.monotonic()
        else:
            time.sleep(settings.worker_poll_seconds)
    state.heartbeat(worker_id, "stopped")
    log.info("worker stopped", extra={"worker_id": worker_id,
                                      "idle_seconds": int(time.monotonic() - idle_since)})


if __name__ == "__main__":
    main()
