"""HTTP surface tests.

The most important assertion in this file is that serving a page makes no
outbound request to UN Comtrade.
"""

from __future__ import annotations

import httpx
import polars as pl
import pytest
import respx
from fastapi.testclient import TestClient

from conftest import comtrade_rows, payload
from trade_api import etl, jobs, state


@pytest.fixture
def seeded(settings):
    """A small but realistic local cache: one reporter, three years."""
    reporters = pl.DataFrame(
        {
            "reporter_code": [31, 380], "name": ["Azerbaijan", "Italy"],
            "iso2": ["AZ", "IT"], "iso3": ["AZE", "ITA"],
            "is_group": [False, False], "expired": [False, False],
            "valid_from": ["1900-01-01", "1900-01-01"], "valid_to": [None, None],
            "note": [None, None],
        },
        schema={"reporter_code": pl.Int32, "name": pl.Utf8, "iso2": pl.Utf8, "iso3": pl.Utf8,
                "is_group": pl.Boolean, "expired": pl.Boolean, "valid_from": pl.Utf8,
                "valid_to": pl.Utf8, "note": pl.Utf8},
    )
    etl.atomic_write_parquet(reporters, settings.refs_dir / "reporters.parquet")

    partners = pl.DataFrame(
        {"partner_code": [0, 380, 792], "name": ["World", "Italy", "Türkiye"],
         "iso2": [None, "IT", "TR"], "iso3": [None, "ITA", "TUR"],
         "is_group": [True, False, False], "expired": [False, False, False]},
        schema={"partner_code": pl.Int32, "name": pl.Utf8, "iso2": pl.Utf8, "iso3": pl.Utf8,
                "is_group": pl.Boolean, "expired": pl.Boolean},
    )
    etl.atomic_write_parquet(partners, settings.refs_dir / "partners.parquet")

    hs = pl.DataFrame(
        {"hs_code": ["TOTAL", "27", "08", "84"],
         "level": [0, 2, 2, 2],
         "name": ["Total", "Mineral fuels", "Edible fruit and nuts", "Machinery"],
         "parent": ["#", "TOTAL", "TOTAL", "TOTAL"],
         "is_leaf": [False, False, False, False],
         "standard_unit": [None, None, None, None]},
        schema={"hs_code": pl.Utf8, "level": pl.Int8, "name": pl.Utf8, "parent": pl.Utf8,
                "is_leaf": pl.Boolean, "standard_unit": pl.Utf8},
    )
    etl.atomic_write_parquet(hs, settings.refs_dir / "hs.parquet")

    rows = []
    for year, exports, imports in ((2022, 100.0, 60.0), (2023, 120.0, 70.0), (2024, 150.0, 90.0)):
        for flow, total in (("X", exports), ("M", imports)):
            rows.append(comtrade_rows(refYear=year, period=str(year), flowCode=flow,
                                      partnerCode=0, primaryValue=total))
            rows.append(comtrade_rows(refYear=year, period=str(year), flowCode=flow,
                                      partnerCode=380, primaryValue=total * 0.6))
            rows.append(comtrade_rows(refYear=year, period=str(year), flowCode=flow,
                                      partnerCode=792, primaryValue=total * 0.4))
    frame = etl.normalise_rows(rows)
    etl.merge_into_partition("totals", frame.filter(pl.col("partner_code") == 0).drop("partner_code"),
                             freq="A", reporter=31)
    etl.merge_into_partition("partners", frame.filter(pl.col("partner_code") > 0),
                             freq="A", reporter=31)

    product_rows = []
    for year, exports, imports in ((2022, 100.0, 60.0), (2023, 120.0, 70.0), (2024, 150.0, 90.0)):
        for flow, total in (("X", exports), ("M", imports)):
            for code, weight in (("27", 0.7), ("08", 0.2), ("84", 0.1)):
                product_rows.append(comtrade_rows(refYear=year, period=str(year), flowCode=flow,
                                                  partnerCode=0, cmdCode=code,
                                                  primaryValue=total * weight, netWgt=total * 100))
    products = etl.normalise_rows(product_rows).drop("partner_code")
    etl.merge_into_partition("products_hs2", products, freq="A", reporter=31)

    for dataset in ("totals", "partners", "products_hs2"):
        state.bump_dataset_version(dataset, "freq=A/reporter=031", 10)
    return settings


@pytest.fixture
def client(seeded):
    from trade_api.app import create_app

    return TestClient(create_app())


class TestNoRemoteCallsOnPageView:
    @respx.mock(assert_all_mocked=False, assert_all_called=False)
    def test_serving_a_country_makes_zero_comtrade_requests(self, client, respx_mock):
        blocked = respx_mock.route(host="comtradeapi.un.org").mock(
            return_value=httpx.Response(500, text="a page view must never reach here")
        )
        for path in (
            "/trade/api/country/AZE/summary",
            "/trade/api/country/AZE/totals",
            "/trade/api/country/AZE/products",
            "/trade/api/country/AZE/partners",
            "/trade/api/country/AZE/balance",
            "/trade/api/country/AZE/insights",
            "/trade/api/country/AZE/network",
            "/trade/api/meta/countries",
            "/trade/api/meta/products",
        ):
            assert client.get(path).status_code == 200, path
        assert blocked.call_count == 0

    @respx.mock(assert_all_mocked=False, assert_all_called=False)
    def test_a_refresh_makes_zero_comtrade_requests(self, client, respx_mock):
        blocked = respx_mock.route(host="comtradeapi.un.org").mock(
            return_value=httpx.Response(500)
        )
        for _ in range(5):
            assert client.get("/trade/api/country/AZE/summary").status_code == 200
        assert blocked.call_count == 0

    def test_an_uncached_country_enqueues_a_job_instead_of_fetching(self, client):
        response = client.get("/trade/api/country/ITA/summary")
        assert response.status_code == 202
        body = response.json()
        assert body["data"]["status"] == "preparing"
        assert body["data"]["job"]["id"] > 0
        assert jobs.summary().get("queued") == 1

    def test_repeated_requests_for_an_uncached_country_reuse_one_job(self, client):
        for _ in range(6):
            client.get("/trade/api/country/ITA/summary")
        assert jobs.summary().get("queued") == 1


class TestSummary:
    def test_shape_and_values(self, client):
        body = client.get("/trade/api/country/AZE/summary").json()
        data, meta = body["data"], body["meta"]
        assert data["status"] == "ready"
        assert data["kpis"]["exports"] == pytest.approx(150.0)
        assert data["kpis"]["imports"] == pytest.approx(90.0)
        assert data["kpis"]["balance"] == pytest.approx(60.0)
        assert data["kpis"]["export_change"] == pytest.approx(0.25)
        assert len(data["series"]) == 3
        assert meta["source"] == "UN Comtrade"
        assert meta["reporter"]["iso3"] == "AZE"
        assert meta["measure"] == "Trade value (current USD)"

    def test_top_partner_is_named_and_shared(self, client):
        data = client.get("/trade/api/country/AZE/summary").json()["data"]
        top = data["kpis"]["top_export_destination"]
        assert top["name"] == "Italy"
        assert top["share"] == pytest.approx(0.6)

    def test_products_carry_names_codes_and_shares(self, client):
        data = client.get("/trade/api/country/AZE/summary").json()["data"]
        first = data["export_products"]["items"][0]
        assert first["code"] == "27"
        assert first["name"] == "Mineral fuels"
        assert first["share"] == pytest.approx(0.7)

    def test_payload_stays_small(self, client):
        response = client.get("/trade/api/country/AZE/summary")
        assert len(response.content) < 60_000


class TestOtherBucket:
    def test_other_is_the_remainder_not_discarded(self, client):
        body = client.get("/trade/api/country/AZE/products?top=1").json()["data"]
        assert body["items"][0]["value"] == pytest.approx(105.0)
        assert body["other"]["value"] == pytest.approx(45.0)
        assert body["items"][0]["value"] + body["other"]["value"] == pytest.approx(body["total"])


class TestFrequency:
    def test_monthly_without_cache_offers_preparation(self, client):
        response = client.get("/trade/api/country/AZE/summary?freq=M")
        assert response.status_code == 202
        assert response.json()["data"]["status"] == "preparing"

    def test_invalid_frequency_is_rejected(self, client):
        assert client.get("/trade/api/country/AZE/summary?freq=Z").status_code == 400

    def test_invalid_flow_is_rejected(self, client):
        assert client.get("/trade/api/country/AZE/products?flow=Q").status_code == 400

    def test_out_of_range_top_is_rejected(self, client):
        assert client.get("/trade/api/country/AZE/products?top=9999").status_code == 400

    def test_unknown_reporter_is_a_404(self, client):
        assert client.get("/trade/api/country/ZZZ/summary").status_code == 404

    def test_malformed_hs_code_is_rejected(self, client):
        assert client.get("/trade/api/country/AZE/product/27X").status_code == 400
        assert client.get("/trade/api/country/AZE/product/123").status_code == 400


class TestHttpCaching:
    def test_etag_is_issued_and_honoured(self, client):
        first = client.get("/trade/api/country/AZE/summary")
        etag = first.headers["ETag"]
        assert etag
        second = client.get("/trade/api/country/AZE/summary", headers={"If-None-Match": etag})
        assert second.status_code == 304

    def test_etag_changes_when_the_dataset_version_changes(self, client):
        etag = client.get("/trade/api/country/AZE/summary").headers["ETag"]
        state.bump_dataset_version("totals", "freq=A/reporter=031", 11)
        assert client.get("/trade/api/country/AZE/summary").headers["ETag"] != etag

    def test_cache_control_is_set(self, client):
        headers = client.get("/trade/api/country/AZE/summary").headers
        assert "max-age" in headers["Cache-Control"]

    def test_reference_data_is_cached_for_a_day(self, client):
        headers = client.get("/trade/api/meta/countries").headers
        assert "max-age=86400" in headers["Cache-Control"]


class TestDrilldowns:
    def test_product_detail(self, client):
        body = client.get("/trade/api/country/AZE/product/27").json()["data"]
        assert body["code"] == "27"
        assert body["name"] == "Mineral fuels"
        assert body["value"] == pytest.approx(105.0)
        assert body["share_of_flow"] == pytest.approx(0.7)
        assert len(body["series"]) == 3

    def test_product_unit_value_proxy_is_present_when_weight_exists(self, client):
        body = client.get("/trade/api/country/AZE/product/27").json()["data"]
        assert body["unit_values"]
        assert body["unit_values"][-1]["unit_value"] is not None

    def test_partner_detail_shares_and_balance(self, client):
        body = client.get("/trade/api/country/AZE/partner/380").json()["data"]
        assert body["partner"]["name"] == "Italy"
        assert body["exports"] == pytest.approx(90.0)
        assert body["imports"] == pytest.approx(54.0)
        assert body["balance"] == pytest.approx(36.0)
        assert body["export_share_of_total"] == pytest.approx(0.6)

    def test_world_cannot_be_used_as_a_bilateral_partner(self, client):
        assert client.get("/trade/api/country/AZE/partner/0").status_code == 400

    def test_network_is_bounded_and_has_an_other_node(self, client):
        body = client.get("/trade/api/country/AZE/network").json()["data"]
        assert body["available"] is True
        assert len(body["nodes"]) <= 12 + 15 + 3
        assert any(node["kind"] == "country" for node in body["nodes"])


class TestInsights:
    def test_dependency_and_sentences(self, client):
        body = client.get("/trade/api/country/AZE/insights").json()["data"]
        assert body["dependency"]["export_products"]["hhi"] == pytest.approx(0.54)
        assert body["dependency"]["export_partners"]["top1_share"] == pytest.approx(0.6)
        assert any("Mineral fuels" in s for s in body["sentences"])

    def test_sentences_avoid_causal_language(self, client):
        body = client.get("/trade/api/country/AZE/insights").json()["data"]
        for sentence in body["sentences"]:
            lowered = sentence.lower()
            assert "because" not in lowered
            assert "caused by" not in lowered

    def test_balance_rankings(self, client):
        body = client.get("/trade/api/country/AZE/balance").json()["data"]
        assert body["partner_surpluses"][0]["name"] in {"Italy", "Türkiye"}
        assert body["series"][-1]["balance"] == pytest.approx(60.0)


class TestAdvancedDegradation:
    def test_advanced_reports_missing_global_matrix_rather_than_guessing(self, client):
        body = client.get("/trade/api/country/AZE/advanced").json()["data"]
        assert body["global_share"]["available"] is False
        assert body["rca"]["available"] is False
        assert "reason" in body["global_share"]

    def test_anomalies_need_monthly_data(self, client):
        body = client.get("/trade/api/country/AZE/anomalies").json()["data"]
        assert body["available"] is False


class TestFrontendAndHealth:
    def test_spa_is_served_under_the_base_path(self, client):
        response = client.get("/trade")
        assert response.status_code in (200, 503)

    def test_deep_links_resolve_to_the_spa(self, client):
        assert client.get("/trade/country/AZE").status_code in (200, 503)
        assert client.get("/trade/methodology").status_code in (200, 503)

    def test_unknown_api_route_is_json_404(self, client):
        response = client.get("/trade/api/does-not-exist")
        assert response.status_code == 404

    def test_health_reports_its_checks(self, client):
        body = client.get("/trade/api/health").json()["data"]
        assert body["status"] == "ok"
        assert body["checks"]["sqlite"] == "ok"
        assert body["checks"]["duckdb"] == "ok"
        assert "quota" in body["checks"]

    def test_security_headers_are_present(self, client):
        headers = client.get("/trade/api/health").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "X-Request-Id" in headers

    def test_no_api_key_appears_in_any_response(self, client):
        for path in ("/trade/api/health", "/trade/api/country/AZE/summary",
                     "/trade/api/meta/countries"):
            assert "test-key-0123456789abcdef" not in client.get(path).text


class TestJobStatus:
    def test_job_status_is_readable(self, client):
        client.get("/trade/api/country/ITA/summary")
        job_id = jobs.recent(1)[0]["id"]
        body = client.get(f"/trade/api/job/{job_id}").json()["data"]
        assert body["id"] == job_id
        assert body["status"] in {"queued", "running", "done"}

    def test_unknown_job_is_a_404(self, client):
        assert client.get("/trade/api/job/999999").status_code == 404
