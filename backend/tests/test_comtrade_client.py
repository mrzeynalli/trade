"""Comtrade client behaviour: authentication, secrecy, budget, retries,
truncation and cache identity."""

from __future__ import annotations

import httpx
import pytest
import respx

from conftest import comtrade_rows, payload
from trade_api import state
from trade_api.comtrade import ComtradeClient, ComtradeError, QuotaExhausted, RateLimiter
from trade_api.config import get_settings, redact
from trade_api.keys import canonical_key, canonical_string, normalise_params

DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"


class TestAuthentication:
    @respx.mock
    def test_key_travels_in_a_header_never_in_the_query(self):
        route = respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()]))
        )
        with ComtradeClient() as client:
            client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})

        request = route.calls[0].request
        assert request.headers["Ocp-Apim-Subscription-Key"] == "test-key-0123456789abcdef"
        assert "test-key" not in str(request.url)
        assert "subscription" not in str(request.url).lower()

    @respx.mock
    def test_missing_key_fails_before_any_request(self, monkeypatch):
        from trade_api import config

        monkeypatch.setenv("COMTRADE_API_KEY", "")
        config.get_settings.cache_clear()
        route = respx.get(DATA_URL).mock(return_value=httpx.Response(200, json=payload([])))
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError, match="not configured"):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert not route.called


class TestRedaction:
    def test_redact_removes_every_configured_key(self):
        text = "GET https://x/?subscription-key=test-key-0123456789abcdef failed"
        assert "test-key-0123456789abcdef" not in redact(text)
        assert "***REDACTED***" in redact(text)

    @respx.mock
    def test_error_messages_never_carry_the_key(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(401, text="Access denied for key test-key-0123456789abcdef")
        )
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError) as excinfo:
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert "test-key-0123456789abcdef" not in str(excinfo.value)

    @respx.mock
    def test_call_ledger_never_stores_the_key(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(400, text="bad request key=test-key-0123456789abcdef")
        )
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        rows = state.get_conn().execute("SELECT error FROM api_calls").fetchall()
        assert rows
        assert all("test-key-0123456789abcdef" not in (r["error"] or "") for r in rows)


class TestRateLimiter:
    def test_spacing_is_enforced(self):
        import time

        limiter = RateLimiter(0.05)
        limiter.acquire()
        started = time.monotonic()
        limiter.acquire()
        assert time.monotonic() - started >= 0.045


class TestQuota:
    def test_budget_is_consumed_and_capped(self):
        settings = get_settings()
        normal_cap = settings.daily_call_budget - settings.interactive_reserve
        for _ in range(normal_cap):
            assert state.quota_reserve("normal") is True
        # The reserve is closed to normal work but open to interactive work.
        assert state.quota_reserve("normal") is False
        assert state.quota_reserve("interactive") is True

    def test_backfill_has_its_own_sub_budget(self):
        settings = get_settings()
        for _ in range(settings.global_backfill_daily_budget):
            assert state.quota_reserve("backfill") is True
        assert state.quota_reserve("backfill") is False
        assert state.quota_reserve("normal") is True

    def test_release_returns_an_unused_reservation(self):
        state.quota_reserve("normal")
        before = state.quota_today()["calls_made"]
        state.quota_release("normal")
        assert state.quota_today()["calls_made"] == before - 1

    @respx.mock
    def test_exhausted_budget_serves_stale_cache_rather_than_failing(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, json=payload([comtrade_rows()])))
        params = {"reporterCode": 31, "cmdCode": "TOTAL"}
        with ComtradeClient() as client:
            client.fetch("/data/v1/get/C/A/HS", params)
            # Drain the budget completely.
            settings = get_settings()
            for _ in range(settings.daily_call_budget):
                state.quota_reserve("interactive")
            stale = client.fetch("/data/v1/get/C/A/HS", params, force=True)
        assert stale.from_cache is True
        assert stale.rows

    @respx.mock
    def test_exhausted_budget_without_cache_raises(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, json=payload([])))
        settings = get_settings()
        for _ in range(settings.daily_call_budget):
            state.quota_reserve("interactive")
        with ComtradeClient() as client:
            with pytest.raises(QuotaExhausted):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 999})


class TestCanonicalKeys:
    def test_parameter_order_does_not_change_the_key(self):
        a = canonical_key("/data/v1/get/C/A/HS", {"reporterCode": 31, "period": "2024"})
        b = canonical_key("/data/v1/get/C/A/HS", {"period": "2024", "reporterCode": 31})
        assert a == b

    def test_list_parameter_order_does_not_change_the_key(self):
        a = canonical_key("/data/v1/get/C/A/HS", {"period": "2024,2023"})
        b = canonical_key("/data/v1/get/C/A/HS", {"period": "2023,2024"})
        assert a == b

    def test_different_scope_produces_a_different_key(self):
        a = canonical_key("/data/v1/get/C/A/HS", {"reporterCode": 31})
        b = canonical_key("/data/v1/get/C/A/HS", {"reporterCode": 36})
        assert a != b

    def test_empty_values_are_dropped(self):
        assert normalise_params({"a": 1, "b": None, "c": ""}) == {"a": "1"}

    def test_canonical_string_is_readable_and_sorted(self):
        text = canonical_string("/data/v1/get/C/A/HS", {"period": "2024", "reporterCode": 31})
        assert text == "data/v1/get/C/A/HS?period=2024&reporterCode=31"


class TestCaching:
    @respx.mock
    def test_second_identical_request_makes_no_remote_call(self):
        route = respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()]))
        )
        with ComtradeClient() as client:
            first = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
            second = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert route.call_count == 1
        assert first.from_cache is False
        assert second.from_cache is True
        assert second.rows == first.rows

    @respx.mock
    def test_raw_response_is_stored_compressed(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()] * 5))
        )
        with ComtradeClient() as client:
            result = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert result.path is not None
        assert result.path.suffix == ".zst"
        assert result.path.exists()
        row = state.get_conn().execute("SELECT * FROM api_cache").fetchone()
        assert row["record_count"] == 5
        assert len(row["sha256"]) == 64

    @respx.mock
    def test_force_refetches_and_keeps_one_previous_version(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows(primaryValue=1.0)]))
        )
        with ComtradeClient() as client:
            client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
            respx.get(DATA_URL).mock(
                return_value=httpx.Response(200, json=payload([comtrade_rows(primaryValue=2.0)]))
            )
            client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31}, force=True)
        row = state.get_conn().execute("SELECT * FROM api_cache").fetchone()
        assert row["superseded_path"] is not None


class TestRetries:
    @respx.mock
    def test_retries_on_429_then_succeeds(self):
        route = respx.get(DATA_URL).mock(
            side_effect=[
                httpx.Response(429, text="Rate limit is exceeded.", headers={"Retry-After": "0"}),
                httpx.Response(200, json=payload([comtrade_rows()])),
            ]
        )
        with ComtradeClient() as client:
            result = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert route.call_count == 2
        assert result.count == 1

    @respx.mock
    def test_retries_on_503_then_gives_up(self):
        route = respx.get(DATA_URL).mock(return_value=httpx.Response(503, text="unavailable"))
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        # max_retries = 2 in the test environment, so three attempts in total.
        assert route.call_count == 3

    @respx.mock
    def test_does_not_retry_a_client_error(self):
        route = respx.get(DATA_URL).mock(return_value=httpx.Response(400, text="bad parameter"))
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert route.call_count == 1

    @respx.mock
    def test_retries_a_timeout(self):
        route = respx.get(DATA_URL).mock(
            side_effect=[
                httpx.ReadTimeout("timed out"),
                httpx.Response(200, json=payload([comtrade_rows()])),
            ]
        )
        with ComtradeClient() as client:
            result = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert route.call_count == 2
        assert result.count == 1


class TestResponseHandling:
    @respx.mock
    def test_truncation_at_the_record_cap_is_detected(self):
        # The test environment caps at 10 records; the service returns count == cap
        # with no error flag, which is how real truncation looks.
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()] * 10, count=10))
        )
        with ComtradeClient() as client:
            result = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert result.truncated is True

    @respx.mock
    def test_a_normal_response_is_not_marked_truncated(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()] * 3))
        )
        with ComtradeClient() as client:
            result = client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        assert result.truncated is False

    @respx.mock
    def test_api_level_error_field_raises(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(
                200, json={"count": -1, "data": [], "error": "Maximum number of periods is 12 "}
            )
        )
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError, match="Maximum number of periods"):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})

    @respx.mock
    def test_malformed_json_raises(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, text="<html>nope</html>"))
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError, match="Malformed JSON"):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})

    @respx.mock
    def test_unexpected_schema_raises(self):
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, json={"data": "not-a-list"}))
        with ComtradeClient() as client:
            with pytest.raises(ComtradeError, match="schema"):
                client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})


class TestLedger:
    @respx.mock
    def test_every_call_is_recorded_with_its_details(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()] * 4))
        )
        with ComtradeClient() as client:
            client.fetch("/data/v1/get/C/A/HS",
                         {"reporterCode": 31, "period": "2024", "cmdCode": "AG2",
                          "flowCode": "X,M", "_freq": "A"})
        row = state.get_conn().execute("SELECT * FROM api_calls ORDER BY id DESC LIMIT 1").fetchone()
        assert row["reporter"] == "31"
        assert row["periods"] == "2024"
        assert row["cmd_level"] == "AG2"
        assert row["frequency"] == "A"
        assert row["http_status"] == 200
        assert row["record_count"] == 4
        assert row["cache_status"] == "miss"
        assert row["compressed_bytes"] > 0
        assert row["duration_ms"] >= 0

    @respx.mock
    def test_cache_hits_are_recorded_as_hits(self):
        respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()]))
        )
        with ComtradeClient() as client:
            client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
            client.fetch("/data/v1/get/C/A/HS", {"reporterCode": 31})
        statuses = [
            r["cache_status"]
            for r in state.get_conn().execute("SELECT cache_status FROM api_calls ORDER BY id")
        ]
        assert statuses == ["miss", "hit"]
