"""Shared request helpers: validation, period selection, response envelopes."""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from fastapi import HTTPException, Request, Response

from . import jobs, refs, state, store
from .config import get_settings

FREQUENCIES = {"A", "M"}
FLOWS = {"X", "M"}
ANNUAL_RANGES = {"5": 5, "10": 10, "15": 15, "all": 100}
MONTHLY_RANGES = {"12": 12, "24": 24, "36": 36, "60": 60}
MAX_TOP_N = 50


def require_frequency(freq: str) -> str:
    freq = (freq or "A").upper()
    if freq not in FREQUENCIES:
        raise HTTPException(400, "frequency must be A or M")
    return freq


def require_flow(flow: str) -> str:
    flow = (flow or "X").upper()
    if flow not in FLOWS:
        raise HTTPException(400, "flow must be X or M")
    return flow


def require_top_n(value: int) -> int:
    if not 1 <= value <= MAX_TOP_N:
        raise HTTPException(400, f"top must be between 1 and {MAX_TOP_N}")
    return value


def require_hs_code(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) not in (2, 4, 6):
        raise HTTPException(400, "hs code must be 2, 4 or 6 digits")
    return code


def resolve_reporter_or_404(token: str) -> dict[str, Any]:
    reporter = refs.resolve_reporter(token)
    if reporter is None:
        raise HTTPException(404, "Unknown reporter")
    return reporter


def resolve_partner_or_404(token: str) -> dict[str, Any]:
    partner = refs.resolve_partner(token)
    if partner is None:
        raise HTTPException(404, "Unknown partner")
    if int(partner["partner_code"]) == 0:
        raise HTTPException(400, "World is an aggregate, not a bilateral partner")
    return partner


# --------------------------------------------------------------------------
# Period selection
# --------------------------------------------------------------------------

def series_periods(reporter: int, freq: str, range_token: str | None) -> tuple[int | None, int | None]:
    """Year bounds for a time series request."""
    latest = store.latest_period(reporter, freq)
    if not latest:
        return None, None
    if freq == "A":
        span = ANNUAL_RANGES.get((range_token or "15"), 15)
        end = int(latest["latest"])
        return max(get_settings().annual_history_start, end - span + 1), end
    return None, None


def ranking_periods(reporter: int, freq: str, *, year: int | None = None,
                    window: str = "r12") -> list[str]:
    """Which periods a composition/ranking chart should aggregate.

    Annual defaults to the latest *complete* year. Monthly defaults to a
    rolling twelve months, because one month is noisy.
    """
    latest = store.latest_period(reporter, freq)
    if not latest:
        return []
    if freq == "A":
        if year is not None:
            return [str(year)] if year in latest["available"] else []
        reference = latest.get("latest_complete") or latest["latest"]
        return [str(reference)]
    available = latest["available"]  # newest first
    if window == "latest":
        return available[:1]
    count = MONTHLY_RANGES.get(window.lstrip("r"), 12) if window.startswith("r") else 12
    return sorted(available[:count])


def monthly_series_periods(range_token: str | None) -> int:
    return MONTHLY_RANGES.get((range_token or "36"), 36)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------

def build_meta(
    reporter: dict[str, Any], freq: str, *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    code = int(reporter["reporter_code"])
    annual = store.latest_period(code, "A")
    monthly = store.latest_period(code, "M")
    coverage = store.period_coverage(code, freq)
    version = state.dataset_version("totals", f"freq={freq}/reporter={code:03d}")
    quota = state.quota_today()
    settings = get_settings()

    meta = {
        "source": "UN Comtrade",
        "frequency": "annual" if freq == "A" else "monthly",
        "classification": "HS (as reported)",
        "measure": "Trade value (current USD)",
        "reporter": {
            "code": code,
            "name": reporter["name"],
            "iso3": reporter.get("iso3"),
            "iso2": reporter.get("iso2"),
        },
        "latest_complete_annual": (annual or {}).get("latest_complete"),
        "latest_annual": (annual or {}).get("latest"),
        "latest_monthly": (monthly or {}).get("latest"),
        "latest_complete_period": (annual or {}).get("latest_complete") if freq == "A"
        else (monthly or {}).get("latest"),
        "partial": bool((annual or {}).get("partial")) if freq == "A" else False,
        "last_source_update": coverage.get("source_last_released"),
        "local_cache_updated_at": (version or {}).get("updated_at"),
        "dataset_version": (version or {}).get("version", 0),
        "stale": False,
        "quota": {
            "calls_today": quota["calls_made"],
            "daily_budget": settings.daily_call_budget,
        },
    }
    if extra:
        meta.update(extra)
    return meta


def envelope(data: Any, meta: dict[str, Any]) -> dict[str, Any]:
    return {"data": data, "meta": meta}


def apply_http_cache(request: Request, response: Response, *,
                     version_scopes: Sequence[tuple[str, str]], params: str,
                     max_age: int = 120) -> bool:
    """Set ETag/Cache-Control and report whether a 304 should be returned."""
    token = state.dataset_versions_for(list(version_scopes))
    etag = '"' + hashlib.sha256(f"{params}|{token}".encode()).hexdigest()[:32] + '"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"public, max-age={max_age}, stale-while-revalidate=600"
    response.headers["Vary"] = "Accept-Encoding"
    if request.headers.get("if-none-match") == etag:
        return True
    return False


# --------------------------------------------------------------------------
# Lazy ingestion
# --------------------------------------------------------------------------

def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


# How long a failed job suppresses a re-queue for the same key.
#
# Without this the client polls a "preparing" response every couple of seconds,
# each poll finds no *active* job because the last one failed, enqueues another,
# and that one fails identically — a loop that never terminates and never tells
# the reader why. A cooldown reports the failure instead, while still letting a
# genuine retry a minute later through.
FAILED_JOB_COOLDOWN_SECONDS = 180


def _failure_reason(error: str | None) -> tuple[str, bool]:
    """A reader-facing sentence for a job error, and whether it is temporary.

    The overwhelmingly common failure is the daily Comtrade quota running out,
    which is not a fault and does resolve on its own — saying so is far more
    use than "preparation failed".
    """
    text = error or ""
    if "call volume quota" in text or "429" in text or "Daily Comtrade call budget" in text:
        return ("The daily UN Comtrade request quota is used up, so this "
                "country pair could not be fetched. It replenishes within the "
                "day; everything already cached is unaffected.", True)
    if "403" in text:
        return ("UN Comtrade refused the request for this country pair.", False)
    return ("This country pair could not be fetched from UN Comtrade.", False)


def preparing_response(request: Request, kind: str, payload: dict[str, Any],
                       message: str) -> dict[str, Any]:
    """Enqueue a de-duplicated ingestion job and describe it to the UI."""
    existing = jobs.find_active(kind, payload)
    if existing is not None:
        return {"status": "preparing", "message": message,
                "job": {"id": existing["id"], "status": existing["status"],
                        "progress": existing["progress"]}}

    # A recently failed job is reported, not silently retried behind a spinner.
    latest = jobs.find_latest(kind, payload)
    if latest is not None and latest.get("status") == "failed":
        finished = latest.get("finished_at")
        age = state.seconds_since(finished) if finished else None
        if age is not None and age < FAILED_JOB_COOLDOWN_SECONDS:
            reason, temporary = _failure_reason(latest.get("error"))
            return {
                "status": "unavailable",
                "message": reason,
                "temporary": temporary,
                "retry_after": int(FAILED_JOB_COOLDOWN_SECONDS - age),
                "job": {"id": latest["id"], "status": "failed",
                        "progress": latest.get("progress")},
            }

    if not state.allow_job_creation(client_key(request)):
        raise HTTPException(429, "Too many data preparation requests from this client")

    job = jobs.enqueue(kind, payload)
    return {"status": "preparing", "message": message,
            "job": {"id": job["id"], "status": job["status"], "progress": job.get("progress")}}
