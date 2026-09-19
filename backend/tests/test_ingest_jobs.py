"""Batching, deterministic subdivision, job de-duplication and source-aware sync."""

from __future__ import annotations

import httpx
import pytest
import respx

from conftest import comtrade_rows, payload
from trade_api import ingest, jobs, state, store
from trade_api.comtrade import ComtradeClient

DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
AVAIL_URL = "https://comtradeapi.un.org/data/v1/getDa/C/A/HS"


class TestPeriodBatching:
    def test_annual_periods(self):
        assert ingest.annual_periods(2020, 2023) == ["2020", "2021", "2022", "2023"]

    def test_monthly_periods_walk_backwards_across_a_year_boundary(self):
        assert ingest.monthly_periods(3, end="202502") == ["202412", "202501", "202502"]

    def test_chunking_respects_the_twelve_period_limit(self):
        periods = ingest.annual_periods(2010, 2025)  # 16 years
        chunks = ingest.chunk(periods, 12)
        assert [len(c) for c in chunks] == [12, 4]

    @respx.mock
    def test_sixteen_years_cost_two_calls_not_sixteen(self):
        route = respx.get(DATA_URL).mock(
            return_value=httpx.Response(200, json=payload([comtrade_rows()]))
        )
        with ComtradeClient() as client:
            rows, calls, truncated = ingest.fetch_segments(
                client, "A", {"reporterCode": 31, "cmdCode": "TOTAL", "flowCode": "X,M"},
                ingest.annual_periods(2010, 2025),
            )
        assert route.call_count == 2
        assert calls == 2
        assert truncated == 0


class TestTruncationSubdivision:
    @respx.mock
    def test_a_truncated_batch_is_split_by_period(self):
        # The test cap is 10 records. The first response comes back at the cap,
        # so the client must split the period range and refetch.
        responses = [httpx.Response(200, json=payload([comtrade_rows()] * 10, count=10))]
        responses += [httpx.Response(200, json=payload([comtrade_rows()] * 2))] * 8
        route = respx.get(DATA_URL).mock(side_effect=responses)
        with ComtradeClient() as client:
            rows, calls, truncated = ingest.fetch_segments(
                client, "A", {"reporterCode": 31, "cmdCode": "TOTAL", "flowCode": "X,M"},
                ["2020", "2021", "2022", "2023"],
            )
        assert truncated == 1
        assert route.call_count == 3  # one truncated + two halves
        assert len(rows) == 4

    def test_subdivision_order_is_periods_then_flows_then_commodities(self):
        # More than one period: split the periods.
        children = ingest._subdivide(["2020", "2021"], {"flowCode": "X,M", "cmdCode": "AG2"})
        assert [c[0] for c in children] == [["2020"], ["2021"]]

        # One period, two flows: split the flows.
        children = ingest._subdivide(["2020"], {"flowCode": "X,M", "cmdCode": "TOTAL"})
        assert sorted(c[1]["flowCode"] for c in children) == ["M", "X"]

    def test_subdivision_gives_up_deterministically(self):
        assert ingest._subdivide(["2020"], {"flowCode": "X", "cmdCode": "TOTAL"}) is None

    def test_explicit_commodity_lists_are_halved(self):
        children = ingest._subdivide(["2020"], {"flowCode": "X", "cmdCode": "01,02,03,04"})
        assert [c[1]["cmdCode"] for c in children] == ["01,02", "03,04"]

    def test_reporter_lists_are_halved_as_a_last_resort(self):
        children = ingest._subdivide(
            ["2020"], {"flowCode": "X", "cmdCode": "TOTAL", "reporterCode": "31,36,40,44"}
        )
        assert [c[1]["reporterCode"] for c in children] == ["31,36", "40,44"]


class TestWorldSeparation:
    @respx.mock
    def test_world_and_partner_rows_land_in_separate_datasets(self):
        rows = [
            comtrade_rows(partnerCode=0, primaryValue=100.0),
            comtrade_rows(partnerCode=380, primaryValue=60.0),
            comtrade_rows(partnerCode=792, primaryValue=40.0),
        ]
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, json=payload(rows)))
        with ComtradeClient() as client:
            results = ingest.ingest_country_totals_and_partners(client, 31, "A", ["2024"])

        by_dataset = {r.dataset: r for r in results}
        assert by_dataset["totals"].rows == 1
        assert by_dataset["partners"].rows == 2

        import polars as pl
        from trade_api.etl import partition_path

        partners = pl.read_parquet(partition_path("partners", freq="A", reporter=31))
        assert 0 not in partners["partner_code"].to_list(), "World must never enter the partner table"

    @respx.mock
    def test_partner_sum_versus_world_is_recorded(self):
        rows = [
            comtrade_rows(partnerCode=0, primaryValue=100.0),
            comtrade_rows(partnerCode=380, primaryValue=60.0),
            comtrade_rows(partnerCode=792, primaryValue=45.0),  # deliberately over
        ]
        respx.get(DATA_URL).mock(return_value=httpx.Response(200, json=payload(rows)))
        with ComtradeClient() as client:
            results = ingest.ingest_country_totals_and_partners(client, 31, "A", ["2024"])
        partners = next(r for r in results if r.dataset == "partners")
        check = partners.reconciliation["partner_sum_vs_world_X"]
        assert check["difference"] == pytest.approx(5.0)
        assert check["relative_difference"] == pytest.approx(0.05)
        # The data itself is not rescaled to force agreement.
        assert check["component_total"] == pytest.approx(105.0)


class TestAvailabilitySync:
    @respx.mock
    def test_first_sync_records_every_dataset(self):
        respx.get(AVAIL_URL).mock(return_value=httpx.Response(200, json=payload([
            {"datasetCode": "d2023", "typeCode": "C", "freqCode": "A", "period": 2023,
             "reporterCode": 31, "classificationCode": "H6", "totalRecords": 10,
             "datasetChecksum": "abc", "firstReleased": "2024-01-01", "lastReleased": "2024-01-01"},
            {"datasetCode": "d2024", "typeCode": "C", "freqCode": "A", "period": 2024,
             "reporterCode": 31, "classificationCode": "H6", "totalRecords": 20,
             "datasetChecksum": "def", "firstReleased": "2025-01-01", "lastReleased": "2025-01-01"},
        ])))
        with ComtradeClient() as client:
            result = ingest.sync_availability(client, 31, "A")
        assert result["periods"] == [2023, 2024]
        assert result["changed"] == [2023, 2024]

    @respx.mock
    def test_unchanged_checksums_report_no_change(self):
        body = payload([
            {"datasetCode": "d2024", "typeCode": "C", "freqCode": "A", "period": 2024,
             "reporterCode": 31, "classificationCode": "H6", "totalRecords": 20,
             "datasetChecksum": "def", "firstReleased": "2025-01-01", "lastReleased": "2025-01-01"},
        ])
        respx.get(AVAIL_URL).mock(return_value=httpx.Response(200, json=body))
        with ComtradeClient() as client:
            ingest.sync_availability(client, 31, "A")
            second = ingest.sync_availability(client, 31, "A")
        assert second["changed"] == []

    @respx.mock
    def test_a_new_checksum_marks_the_period_changed(self):
        first = payload([
            {"datasetCode": "d2024", "typeCode": "C", "freqCode": "A", "period": 2024,
             "reporterCode": 31, "classificationCode": "H6", "totalRecords": 20,
             "datasetChecksum": "def", "firstReleased": "2025-01-01", "lastReleased": "2025-01-01"},
        ])
        revised = payload([
            {"datasetCode": "d2024", "typeCode": "C", "freqCode": "A", "period": 2024,
             "reporterCode": 31, "classificationCode": "H6", "totalRecords": 21,
             "datasetChecksum": "xyz", "firstReleased": "2025-01-01", "lastReleased": "2026-02-02"},
        ])
        route = respx.get(AVAIL_URL).mock(side_effect=[
            httpx.Response(200, json=first), httpx.Response(200, json=revised)
        ])
        with ComtradeClient() as client:
            ingest.sync_availability(client, 31, "A")
            second = ingest.sync_availability(client, 31, "A")
        assert route.call_count == 2
        assert second["changed"] == [2024]


class TestJobQueue:
    def test_identical_requests_produce_one_job(self):
        first = jobs.enqueue("country_annual", {"reporter": 31})
        second = jobs.enqueue("country_annual", {"reporter": 31})
        assert second["deduplicated"] is True
        assert second["id"] == first["id"]

    def test_twenty_simultaneous_visitors_produce_one_job(self):
        created = {jobs.enqueue("country_annual", {"reporter": 31})["id"] for _ in range(20)}
        assert len(created) == 1

    def test_different_payloads_produce_different_jobs(self):
        a = jobs.enqueue("country_annual", {"reporter": 31})
        b = jobs.enqueue("country_annual", {"reporter": 36})
        assert a["id"] != b["id"]

    def test_payload_key_order_does_not_matter(self):
        a = jobs.make_key("x", {"reporter": 31, "freq": "A"})
        b = jobs.make_key("x", {"freq": "A", "reporter": 31})
        assert a == b

    def test_claim_takes_the_highest_priority_first(self):
        jobs.enqueue("global_hs2", {"year": 2024})       # priority 60
        jobs.enqueue("country_annual", {"reporter": 31})  # priority 10
        claimed = jobs.claim()
        assert claimed["kind"] == "country_annual"

    def test_a_completed_job_frees_the_key(self):
        first = jobs.enqueue("country_annual", {"reporter": 31})
        jobs.finish(first["id"], "done")
        second = jobs.enqueue("country_annual", {"reporter": 31})
        assert second["deduplicated"] is False
        assert second["id"] != first["id"]

    def test_orphaned_running_jobs_are_requeued(self):
        jobs.enqueue("country_annual", {"reporter": 31})
        jobs.claim()
        assert jobs.summary().get("running") == 1
        assert jobs.reset_orphans() == 1
        assert jobs.summary().get("queued") == 1

    def test_failed_jobs_can_be_requeued(self):
        job = jobs.enqueue("country_annual", {"reporter": 31})
        jobs.finish(job["id"], "failed", "boom")
        assert jobs.retry_failed() == 1
        assert jobs.summary().get("queued") == 1


class TestAbuseProtection:
    def test_a_client_cannot_create_unlimited_jobs(self, settings):
        allowed = [state.allow_job_creation("1.2.3.4") for _ in range(settings.job_rate_limit_per_hour + 3)]
        assert allowed[:settings.job_rate_limit_per_hour] == [True] * settings.job_rate_limit_per_hour
        assert allowed[settings.job_rate_limit_per_hour:] == [False, False, False]

    def test_the_limit_is_per_client(self, settings):
        for _ in range(settings.job_rate_limit_per_hour):
            state.allow_job_creation("1.2.3.4")
        assert state.allow_job_creation("5.6.7.8") is True


class TestFailedJobsDoNotLoop:
    """A failed preparation job must be reported, not silently re-queued.

    `find_active` deliberately ignores terminal jobs. That is right for
    de-duplication, but it used to mean a failed job was invisible to
    `preparing_response`: the caller enqueued a replacement, the replacement
    failed identically, and the browser polled a spinner every 2.5 seconds
    forever — creating a job each time.
    """

    def _request(self):
        from starlette.datastructures import Headers
        from starlette.requests import Request

        return Request({
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": Headers({}).raw,
            "client": ("198.51.100.7", 1234),
            "query_string": b"",
        })

    def test_a_recent_failure_is_reported_rather_than_requeued(self):
        from trade_api.api_common import preparing_response

        kind, payload_body = "partner_products", {"reporter": 31, "partner": 380}
        job = jobs.enqueue(kind, payload_body)
        jobs.claim()
        jobs.finish(job["id"], "failed",
                    'ComtradeError: HTTP 403: {"message": "Out of call volume quota."}')

        before = len(jobs.recent(limit=100))
        result = preparing_response(self._request(), kind, payload_body, "Preparing")

        assert result["status"] == "unavailable"
        assert result["temporary"] is True
        assert "quota" in result["message"].lower()
        # Critically: no new job was created by asking again.
        assert len(jobs.recent(limit=100)) == before

    def test_an_unrelated_key_still_enqueues(self):
        from trade_api.api_common import preparing_response

        result = preparing_response(
            self._request(), "partner_products", {"reporter": 31, "partner": 999}, "Preparing")
        assert result["status"] == "preparing"

    def test_find_latest_sees_terminal_jobs_that_find_active_hides(self):
        kind, payload_body = "country_annual", {"reporter": 4242}
        job = jobs.enqueue(kind, payload_body)
        jobs.claim()
        jobs.finish(job["id"], "failed", "boom")

        assert jobs.find_active(kind, payload_body) is None
        latest = jobs.find_latest(kind, payload_body)
        assert latest is not None and latest["status"] == "failed"
