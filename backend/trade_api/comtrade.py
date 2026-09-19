"""UN Comtrade v1 client.

Responsibilities:
  * authenticate with the subscription key in a request header (never a query
    string, so the key cannot leak through an intermediary's access log);
  * enforce a minimum inter-request interval and the daily call budget;
  * retry idempotent GETs on 429/5xx with capped exponential backoff + jitter;
  * store every response compressed with Zstandard and index it in SQLite;
  * detect the service's silent 100000-record truncation;
  * make it impossible for a subscription key to reach a log or an exception.

Verified service behaviour (2026-09-04):
  * a request with more than 12 periods is rejected: "Maximum number of periods is 12";
  * a result larger than 100000 records is returned truncated with no error flag;
  * ``reporterCode`` may be omitted to mean "every reporter";
  * the rate limiter replies 429 with "Try again in N seconds".
"""

from __future__ import annotations

import hashlib
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import httpx
import orjson
import zstandard

from . import state
from .config import Settings, get_settings, redact
from .keys import canonical_key, canonical_string, normalise_params
from .logging_setup import get_logger

log = get_logger("trade.comtrade")

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ComtradeError(RuntimeError):
    """A Comtrade request failed. The message is always redacted."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(redact(message))
        self.status = status
        self.retryable = retryable


class QuotaExhausted(ComtradeError):
    def __init__(self, message: str = "Daily Comtrade call budget exhausted"):
        super().__init__(message, status=None, retryable=False)


@dataclass
class FetchResult:
    cache_key: str
    rows: list[dict[str, Any]]
    count: int
    truncated: bool
    from_cache: bool
    fetched_at: str
    path: Path | None = None
    source_published: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class RateLimiter:
    """Process-wide minimum spacing between outbound requests."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


class ComtradeClient:
    def __init__(self, settings: Settings | None = None, conn: sqlite3.Connection | None = None):
        self.settings = settings or get_settings()
        self._conn = conn
        self.limiter = RateLimiter(self.settings.min_request_interval_seconds)
        self.settings.ensure_dirs()
        self._client: httpx.Client | None = None

    # -- plumbing --------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn or state.get_conn()

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.settings.comtrade_base_url,
                timeout=httpx.Timeout(
                    self.settings.total_timeout_seconds,
                    connect=self.settings.connect_timeout_seconds,
                    read=self.settings.read_timeout_seconds,
                ),
                headers={"Accept": "application/json", "User-Agent": "analytics-trade/1.0"},
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "ComtradeClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _auth_headers(self) -> dict[str, str]:
        key = self.settings.comtrade_api_key or self.settings.comtrade_api_key_secondary
        return {"Ocp-Apim-Subscription-Key": key} if key else {}

    # -- raw cache -------------------------------------------------------
    def _raw_path(self, cache_key: str) -> Path:
        return self.settings.raw_dir / cache_key[:2] / cache_key[2:4] / f"{cache_key}.json.zst"

    def read_cached(self, cache_key: str) -> FetchResult | None:
        row = self.conn.execute(
            "SELECT * FROM api_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        path = Path(row["path"])
        if not path.exists():
            return None
        try:
            payload = _read_zst_json(path)
        except Exception as exc:  # corrupted cache entry; treat as a miss
            state.record_error("raw_cache_read", f"{path}: {exc}", self.conn)
            return None
        return FetchResult(
            cache_key=cache_key,
            rows=payload.get("data") or [],
            count=int(row["record_count"]),
            truncated=bool(row["truncated"]),
            from_cache=True,
            fetched_at=row["fetched_at"],
            path=path,
            source_published=row["source_published"],
        )

    def _store_raw(
        self,
        cache_key: str,
        endpoint: str,
        params: Mapping[str, Any],
        payload: dict[str, Any],
        record_count: int,
        truncated: bool,
    ) -> tuple[Path, int, str]:
        blob = orjson.dumps(payload)
        digest = hashlib.sha256(blob).hexdigest()
        path = self._raw_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)

        previous = self.conn.execute(
            "SELECT path, sha256 FROM api_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()

        superseded_path = None
        superseded_sha = None
        if previous is not None and previous["sha256"] != digest:
            # Retain exactly one prior version, and only when content changed.
            old = Path(previous["path"])
            if old.exists():
                keep = old.with_suffix(".prev.zst")
                if self.settings.raw_retention_versions >= 2:
                    old.replace(keep)
                    superseded_path, superseded_sha = str(keep), previous["sha256"]
                else:
                    old.unlink(missing_ok=True)
        elif previous is not None:
            superseded_path = previous["superseded_path"] if "superseded_path" in previous.keys() else None
            superseded_sha = previous["superseded_sha"] if "superseded_sha" in previous.keys() else None

        compressor = zstandard.ZstdCompressor(level=10)
        tmp = path.with_name(path.name + f".tmp{time.time_ns()}")
        with open(tmp, "wb") as handle:
            handle.write(compressor.compress(blob))
        tmp.replace(path)
        compressed = path.stat().st_size

        self.conn.execute(
            """
            INSERT INTO api_cache(cache_key, endpoint, params_json, path, sha256,
                                  content_length, record_count, truncated,
                                  source_published, fetched_at,
                                  superseded_path, superseded_sha)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
                path=excluded.path, sha256=excluded.sha256,
                content_length=excluded.content_length,
                record_count=excluded.record_count, truncated=excluded.truncated,
                source_published=excluded.source_published,
                fetched_at=excluded.fetched_at,
                superseded_path=excluded.superseded_path,
                superseded_sha=excluded.superseded_sha
            """,
            (
                cache_key, endpoint, orjson.dumps(normalise_params(params)).decode(),
                str(path), digest, len(blob), record_count, int(truncated),
                payload.get("_source_published"), state.utcnow(),
                superseded_path, superseded_sha,
            ),
        )
        return path, compressed, digest

    # -- ledger ----------------------------------------------------------
    def _log_call(
        self, *, request_type: str, cache_key: str, params: Mapping[str, Any],
        status: int | None, duration_ms: int, record_count: int,
        compressed_bytes: int, cache_status: str, retries: int, error: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO api_calls(ts_utc, request_type, cache_key, reporter, partner,
                                     frequency, periods, cmd_level, cmd_code, http_status,
                                     duration_ms, record_count, compressed_bytes,
                                     cache_status, retry_count, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                state.utcnow(), request_type, cache_key,
                str(params.get("reporterCode", "")) or None,
                str(params.get("partnerCode", "")) or None,
                params.get("_freq") or params.get("freqCode"),
                str(params.get("period", "")) or None,
                _cmd_level(params.get("cmdCode")),
                str(params.get("cmdCode", "")) or None,
                status, duration_ms, record_count, compressed_bytes,
                cache_status, retries, redact(error)[:1000] if error else None,
            ),
        )

    # -- public fetch ----------------------------------------------------
    def fetch(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        *,
        request_type: str = "data",
        priority: str = "normal",
        force: bool = False,
        allow_stale: bool = True,
    ) -> FetchResult:
        """Fetch ``endpoint`` with ``params``, serving the local raw cache first.

        ``priority`` selects the quota lane: ``interactive`` may use the
        reserve, ``backfill`` is additionally capped by its own sub-budget.
        """
        cache_key = canonical_key(endpoint, params)

        if not force:
            cached = self.read_cached(cache_key)
            if cached is not None:
                self._log_call(
                    request_type=request_type, cache_key=cache_key, params=params,
                    status=None, duration_ms=0, record_count=cached.count,
                    compressed_bytes=0, cache_status="hit", retries=0,
                )
                return cached

        if self.settings.use_fixture_data:
            fixture = self._load_fixture(cache_key, endpoint, params)
            if fixture is not None:
                return fixture
            raise ComtradeError(
                f"No fixture for {canonical_string(endpoint, params)} (USE_FIXTURE_DATA=true)"
            )

        if not (self.settings.comtrade_api_key or self.settings.comtrade_api_key_secondary):
            raise ComtradeError("COMTRADE_API_KEY is not configured")

        if not state.quota_reserve(priority, self.conn):
            stale = self.read_cached(cache_key) if allow_stale else None
            if stale is not None:
                return stale
            raise QuotaExhausted()

        try:
            return self._request_with_retries(endpoint, params, cache_key, request_type)
        except Exception:
            raise

    def _request_with_retries(
        self, endpoint: str, params: Mapping[str, Any], cache_key: str, request_type: str
    ) -> FetchResult:
        query = {k: v for k, v in normalise_params(params).items() if not k.startswith("_")}
        attempt = 0
        last_error: str = ""
        while attempt <= self.settings.max_retries:
            self.limiter.acquire()
            started = time.monotonic()
            status: int | None = None
            try:
                response = self.client.get(endpoint, params=query, headers=self._auth_headers())
                status = response.status_code
                duration_ms = int((time.monotonic() - started) * 1000)

                if status == 200:
                    return self._handle_ok(
                        response, endpoint, params, cache_key, request_type, duration_ms, attempt
                    )

                body = redact(response.text[:400])
                last_error = f"HTTP {status}: {body}"
                if status in RETRY_STATUS and attempt < self.settings.max_retries:
                    self._sleep_for_retry(response, attempt)
                    attempt += 1
                    continue

                self._log_call(
                    request_type=request_type, cache_key=cache_key, params=params, status=status,
                    duration_ms=duration_ms, record_count=0, compressed_bytes=0,
                    cache_status="miss", retries=attempt, error=last_error,
                )
                raise ComtradeError(last_error, status=status, retryable=status in RETRY_STATUS)

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                last_error = f"{type(exc).__name__}: {redact(str(exc))}"
                if attempt < self.settings.max_retries:
                    self._sleep_for_retry(None, attempt)
                    attempt += 1
                    continue
                self._log_call(
                    request_type=request_type, cache_key=cache_key, params=params, status=None,
                    duration_ms=duration_ms, record_count=0, compressed_bytes=0,
                    cache_status="miss", retries=attempt, error=last_error,
                )
                raise ComtradeError(last_error, retryable=True) from None

        raise ComtradeError(last_error or "Request failed", retryable=True)

    def _handle_ok(
        self, response: httpx.Response, endpoint: str, params: Mapping[str, Any],
        cache_key: str, request_type: str, duration_ms: int, attempt: int,
    ) -> FetchResult:
        try:
            payload = orjson.loads(response.content)
        except orjson.JSONDecodeError as exc:
            raise ComtradeError(f"Malformed JSON from Comtrade: {exc}") from None

        if not isinstance(payload, dict):
            raise ComtradeError("Unexpected Comtrade response schema (expected an object)")

        error_text = (payload.get("error") or "").strip() if isinstance(payload.get("error"), str) else ""
        if error_text:
            self._log_call(
                request_type=request_type, cache_key=cache_key, params=params, status=200,
                duration_ms=duration_ms, record_count=0, compressed_bytes=0,
                cache_status="miss", retries=attempt, error=error_text,
            )
            raise ComtradeError(f"Comtrade error: {error_text}", status=200)

        rows = payload.get("data")
        if rows is None:
            rows = payload.get("results")
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ComtradeError("Unexpected Comtrade response schema (data is not a list)")

        count = int(payload.get("count", len(rows)) or len(rows))
        truncated = count >= self.settings.max_records_per_request

        path, compressed, _digest = self._store_raw(
            cache_key, endpoint, params, payload, len(rows), truncated
        )
        self._log_call(
            request_type=request_type, cache_key=cache_key, params=params, status=200,
            duration_ms=duration_ms, record_count=len(rows), compressed_bytes=compressed,
            cache_status="miss", retries=attempt,
            error="truncated at record cap" if truncated else None,
        )
        log.info(
            "comtrade fetch",
            extra={
                "endpoint": endpoint, "records": len(rows), "truncated": truncated,
                "duration_ms": duration_ms, "retries": attempt,
                "request": canonical_string(endpoint, {k: v for k, v in params.items()
                                                       if not k.startswith("_")}),
            },
        )
        return FetchResult(
            cache_key=cache_key, rows=rows, count=len(rows), truncated=truncated,
            from_cache=False, fetched_at=state.utcnow(), path=path,
        )

    def _sleep_for_retry(self, response: httpx.Response | None, attempt: int) -> None:
        delay = min(
            self.settings.retry_base_delay_seconds * (2 ** attempt),
            self.settings.retry_max_delay_seconds,
        )
        if response is not None:
            header = response.headers.get("Retry-After")
            if header:
                try:
                    delay = max(delay, min(float(header), self.settings.retry_max_delay_seconds))
                except ValueError:
                    pass
        time.sleep(delay + random.uniform(0, delay * 0.25))

    # -- fixtures --------------------------------------------------------
    def _load_fixture(self, cache_key: str, endpoint: str, params: Mapping[str, Any]) -> FetchResult | None:
        base = self.settings.fixture_dir
        if base is None:
            return None
        candidate = Path(base) / f"{cache_key}.json"
        if not candidate.exists():
            return None
        payload = orjson.loads(candidate.read_bytes())
        rows = payload.get("data") or []
        count = int(payload.get("count", len(rows)))
        truncated = count >= self.settings.max_records_per_request
        self._store_raw(cache_key, endpoint, params, payload, len(rows), truncated)
        return FetchResult(
            cache_key=cache_key, rows=rows, count=len(rows), truncated=truncated,
            from_cache=False, fetched_at=state.utcnow(),
        )

    # -- reference files (unauthenticated, no quota) -----------------------
    def fetch_reference(self, filename: str) -> Any:
        url = f"{self.settings.comtrade_reference_path}/{filename}"
        self.limiter.acquire()
        response = self.client.get(url)
        response.raise_for_status()
        return orjson.loads(response.content)


def _cmd_level(cmd: Any) -> str | None:
    if cmd is None:
        return None
    text = str(cmd)
    if text.startswith("AG"):
        return text
    if text == "TOTAL":
        return "TOTAL"
    return f"EXPLICIT{len(text.split(',')[0])}"


def _read_zst_json(path: Path) -> dict[str, Any]:
    decompressor = zstandard.ZstdDecompressor()
    with open(path, "rb") as handle:
        return orjson.loads(decompressor.decompress(handle.read(), max_output_size=1 << 31))
