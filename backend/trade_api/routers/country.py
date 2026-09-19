"""Country dashboard endpoints.

Every response is assembled from local Parquet. Nothing here can trigger a
synchronous Comtrade request: a cache miss enqueues a background job and
returns a "preparing" payload instead.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response

from .. import analytics, derive, insights, refs, store, worldbank
from ..api_common import (
    apply_http_cache, build_meta, envelope, monthly_series_periods, preparing_response,
    ranking_periods, require_flow, require_frequency, require_hs_code, require_top_n,
    resolve_partner_or_404, resolve_reporter_or_404, series_periods,
)
from ..cache import cached
from ..state import dataset_versions_for

router = APIRouter(prefix="/country", tags=["country"])


def _name_lookup_products(codes: list[str]) -> dict[str, str]:
    import polars as pl

    frame = refs.load_hs().filter(pl.col("hs_code").is_in(codes))
    return {r["hs_code"]: r["name"] for r in frame.to_dicts()}


def _name_lookup_partners(codes: list[int]) -> dict[int, dict[str, Any]]:
    import polars as pl

    frame = refs.load_partners().filter(pl.col("partner_code").is_in(codes))
    return {int(r["partner_code"]): r for r in frame.to_dicts()}


def _decorate_products(payload: dict[str, Any]) -> dict[str, Any]:
    names = _name_lookup_products([item["key"] for item in payload["items"]])
    for item in payload["items"]:
        item["code"] = item["key"]
        item["name"] = names.get(item["key"], f"HS {item['key']}")
        item["unit_value"] = analytics.unit_value(item["value"], item.get("weight"))
    return payload


def _decorate_partners(payload: dict[str, Any]) -> dict[str, Any]:
    names = _name_lookup_partners([item["key"] for item in payload["items"]])
    for item in payload["items"]:
        entry = names.get(item["key"], {})
        item["code"] = item["key"]
        item["name"] = entry.get("name", f"Partner {item['key']}")
        item["iso3"] = entry.get("iso3")
    return payload


def _series_window(reporter_code: int, freq: str, range_token: str | None) -> list[dict[str, Any]]:
    if freq == "A":
        start, end = series_periods(reporter_code, freq, range_token)
        return store.totals_series(reporter_code, freq, start=start, end=end)
    months = monthly_series_periods(range_token)
    series = store.totals_series(reporter_code, freq)
    return series[-months:] if months else series


def _yoy(series: list[dict[str, Any]], field: str, freq: str) -> float | None:
    """Year-on-year change for the latest point (12 months back when monthly)."""
    if len(series) < 2:
        return None
    step = 12 if freq == "M" else 1
    if len(series) <= step:
        return None
    current = series[-1].get(field)
    previous = series[-1 - step].get(field)
    return analytics.percent_change(current, previous)


@router.get("/{token}/summary")
def summary(token: str, request: Request, response: Response,
            freq: str = Query("A"), range: str | None = Query(None),
            window: str = Query("r12"), top: int = Query(10)) -> Any:
    """Everything the first screen needs, in one local read."""
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    top = require_top_n(top)
    code = int(reporter["reporter_code"])

    if not store.has_dataset("totals", code, freq):
        payload = preparing_response(
            request,
            "country_annual" if freq == "A" else "country_monthly",
            {"reporter": code} if freq == "A" else {"reporter": code, "months": 36},
            f"Preparing trade data for {reporter['name']}",
        )
        response.status_code = 202
        return envelope(payload, build_meta(reporter, freq))

    scopes = [("totals", f"freq={freq}/reporter={code:03d}"),
              ("partners", f"freq={freq}/reporter={code:03d}"),
              ("products_hs2", f"freq={freq}/reporter={code:03d}")]
    params = f"summary:{code}:{freq}:{range}:{window}:{top}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        series = _series_window(code, freq, range)
        # The rankings window is a real control: monthly composition can be read
        # over the trailing year or for the latest month alone.
        periods = ranking_periods(code, freq, window=window)
        latest = series[-1] if series else {}

        export_ranking = _decorate_products(
            store.product_ranking(code, freq, periods, "X", level=2, top_n=top))
        import_ranking = _decorate_products(
            store.product_ranking(code, freq, periods, "M", level=2, top_n=top))
        export_partners = _decorate_partners(
            store.partner_ranking(code, freq, periods, "X", top_n=top))
        import_partners = _decorate_partners(
            store.partner_ranking(code, freq, periods, "M", top_n=top))

        period_label = _label(periods, freq)
        kpis = {
            "period": latest.get("period"),
            "composition_period": period_label,
            "exports": latest.get("exports"),
            "imports": latest.get("imports"),
            "balance": latest.get("balance"),
            "export_change": _yoy(series, "exports", freq),
            "import_change": _yoy(series, "imports", freq),
            "top_export_destination": export_partners["items"][0] if export_partners["items"] else None,
            "top_import_origin": import_partners["items"][0] if import_partners["items"] else None,
        }
        meta = build_meta(reporter, freq, extra={
            "composition_period": period_label,
            "monthly_available": store.has_dataset("totals", code, "M"),
            "hs4_available": store.has_dataset("products_hs4", code, "A"),
        })
        return envelope(
            {
                "status": "ready",
                "kpis": kpis,
                "series": series,
                "export_products": export_ranking,
                "import_products": import_ranking,
                "export_partners": export_partners,
                "import_partners": import_partners,
            },
            meta,
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


def _label(periods: list[str], freq: str) -> str | None:
    if not periods:
        return None
    if freq == "A":
        return periods[0]
    if len(periods) == 1:
        return _month_label(periods[0])
    return f"{_month_label(periods[0])} – {_month_label(periods[-1])}"


def _month_label(period: str) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[int(period[4:]) - 1]} {period[:4]}"


@router.get("/{token}/totals")
def totals(token: str, request: Request, response: Response,
           freq: str = Query("A"), range: str | None = Query(None)) -> Any:
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    code = int(reporter["reporter_code"])
    scopes = [("totals", f"freq={freq}/reporter={code:03d}")]
    params = f"totals:{code}:{freq}:{range}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)
    return cached(f"{params}:{dataset_versions_for(scopes)}",
                  lambda: envelope(_series_window(code, freq, range), build_meta(reporter, freq)))


@router.get("/{token}/products")
def products(token: str, request: Request, response: Response,
             freq: str = Query("A"), flow: str = Query("X"), level: int = Query(2),
             year: int | None = Query(None), window: str = Query("r12"),
             top: int = Query(10), full: bool = Query(False)) -> Any:
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    flow = require_flow(flow)
    top = require_top_n(top)
    if level not in (2, 4):
        from fastapi import HTTPException

        raise HTTPException(400, "level must be 2 or 4")
    code = int(reporter["reporter_code"])
    dataset = "products_hs2" if level == 2 else "products_hs4"

    if level == 4 and not store.has_dataset(dataset, code, freq):
        payload = preparing_response(request, "country_hs4", {"reporter": code},
                                     "Preparing detailed product data")
        response.status_code = 202
        return envelope(payload, build_meta(reporter, freq))

    scopes = [(dataset, f"freq={freq}/reporter={code:03d}")]
    params = f"products:{code}:{freq}:{flow}:{level}:{year}:{window}:{top}:{full}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        periods = ranking_periods(code, freq, year=year, window=window)
        payload = _decorate_products(
            store.product_ranking(code, freq, periods, flow, level=level,
                                  top_n=10_000 if full else top))
        return envelope(payload, build_meta(reporter, freq,
                                            extra={"composition_period": _label(periods, freq)}))

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/{token}/partners")
def partners(token: str, request: Request, response: Response,
             freq: str = Query("A"), flow: str = Query("X"),
             year: int | None = Query(None), window: str = Query("r12"),
             top: int = Query(10), full: bool = Query(False)) -> Any:
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    flow = require_flow(flow)
    top = require_top_n(top)
    code = int(reporter["reporter_code"])
    scopes = [("partners", f"freq={freq}/reporter={code:03d}")]
    params = f"partners:{code}:{freq}:{flow}:{year}:{window}:{top}:{full}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        periods = ranking_periods(code, freq, year=year, window=window)
        payload = _decorate_partners(
            store.partner_ranking(code, freq, periods, flow, top_n=10_000 if full else top))
        return envelope(payload, build_meta(reporter, freq,
                                            extra={"composition_period": _label(periods, freq)}))

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/{token}/balance")
def balance(token: str, request: Request, response: Response,
            freq: str = Query("A"), range: str | None = Query(None),
            window: str = Query("r12"), top: int = Query(5)) -> Any:
    """Balance series plus the largest bilateral and product-level gaps."""
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    top = require_top_n(top)
    code = int(reporter["reporter_code"])
    scopes = [("totals", f"freq={freq}/reporter={code:03d}"),
              ("partners", f"freq={freq}/reporter={code:03d}"),
              ("products_hs2", f"freq={freq}/reporter={code:03d}")]
    params = f"balance:{code}:{freq}:{range}:{window}:{top}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        series = _series_window(code, freq, range)
        # The rankings window is a real control: monthly composition can be read
        # over the trailing year or for the latest month alone.
        periods = ranking_periods(code, freq, window=window)
        partner_x = store.partner_ranking(code, freq, periods, "X", top_n=10_000)
        partner_m = store.partner_ranking(code, freq, periods, "M", top_n=10_000)
        product_x = store.product_ranking(code, freq, periods, "X", level=2, top_n=10_000)
        product_m = store.product_ranking(code, freq, periods, "M", level=2, top_n=10_000)

        partner_balance = _pairwise_balance(partner_x, partner_m)
        product_balance = _pairwise_balance(product_x, product_m)
        _decorate_balance_partners(partner_balance)
        _decorate_balance_products(product_balance)

        return envelope(
            {
                "series": [{"period": p["period"], "balance": p["balance"],
                            "exports": p["exports"], "imports": p["imports"]} for p in series],
                "composition_period": _label(periods, freq),
                "partner_surpluses": partner_balance[:top],
                "partner_deficits": [b for b in reversed(partner_balance[-top:])
                                     if b["balance"] < 0],
                "product_surpluses": product_balance[:top],
                "product_deficits": [b for b in reversed(product_balance[-top:])
                                     if b["balance"] < 0],
            },
            build_meta(reporter, freq),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


def _pairwise_balance(exports: dict[str, Any], imports: dict[str, Any]) -> list[dict[str, Any]]:
    export_map = {item["key"]: item["value"] for item in exports["items"]}
    import_map = {item["key"]: item["value"] for item in imports["items"]}
    rows = []
    for key in set(export_map) | set(import_map):
        x = export_map.get(key)
        m = import_map.get(key)
        rows.append({"key": key, "exports": x, "imports": m,
                     "balance": (x or 0.0) - (m or 0.0),
                     "complete": x is not None and m is not None})
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows


def _decorate_balance_partners(rows: list[dict[str, Any]]) -> None:
    names = _name_lookup_partners([r["key"] for r in rows])
    for row in rows:
        entry = names.get(row["key"], {})
        row["code"] = row["key"]
        row["name"] = entry.get("name", f"Partner {row['key']}")
        row["iso3"] = entry.get("iso3")


def _decorate_balance_products(rows: list[dict[str, Any]]) -> None:
    names = _name_lookup_products([r["key"] for r in rows])
    for row in rows:
        row["code"] = row["key"]
        row["name"] = names.get(row["key"], f"HS {row['key']}")


@router.get("/{token}/insights")
def country_insights(token: str, request: Request, response: Response,
                     freq: str = Query("A")) -> Any:
    """Tier-2 analytics: concentration, dependency, growth and plain-language notes."""
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    code = int(reporter["reporter_code"])
    scopes = [("totals", f"freq={freq}/reporter={code:03d}"),
              ("concentration", f"freq=A/reporter={code:03d}"),
              ("products_hs2", f"freq={freq}/reporter={code:03d}"),
              ("partners", f"freq={freq}/reporter={code:03d}")]
    params = f"insights:{code}:{freq}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        name = reporter["name"]
        periods = ranking_periods(code, freq)
        period_label = _label(periods, freq)
        concentration = derive.read_concentration(code)
        if not concentration:
            derive.rebuild_concentration(code)
            concentration = derive.read_concentration(code)

        export_products = _decorate_products(
            store.product_ranking(code, freq, periods, "X", level=2, top_n=10))
        import_products = _decorate_products(
            store.product_ranking(code, freq, periods, "M", level=2, top_n=10))
        export_partners = _decorate_partners(
            store.partner_ranking(code, freq, periods, "X", top_n=10))
        import_partners = _decorate_partners(
            store.partner_ranking(code, freq, periods, "M", top_n=10))

        dependency = {
            "export_products": analytics.concentration_profile(
                [i["value"] for i in store.product_ranking(
                    code, freq, periods, "X", level=2, top_n=10_000)["items"]]),
            "import_products": analytics.concentration_profile(
                [i["value"] for i in store.product_ranking(
                    code, freq, periods, "M", level=2, top_n=10_000)["items"]]),
            "export_partners": analytics.concentration_profile(
                [i["value"] for i in store.partner_ranking(
                    code, freq, periods, "X", top_n=10_000)["items"]]),
            "import_partners": analytics.concentration_profile(
                [i["value"] for i in store.partner_ranking(
                    code, freq, periods, "M", top_n=10_000)["items"]]),
        }

        product_growth = derive.growth_table(code, freq, "X")
        import_growth = derive.growth_table(code, freq, "M")
        partner_growth = derive.partner_growth_table(code, freq, "X")
        for table in (product_growth, import_growth):
            for bucket in ("growing", "declining"):
                names = _name_lookup_products([e["key"] for e in table.get(bucket, [])])
                for entry in table.get(bucket, []):
                    entry["name"] = names.get(entry["key"], f"HS {entry['key']}")
                    entry["code"] = entry["key"]
        for bucket in ("growing", "declining"):
            names = _name_lookup_partners([e["key"] for e in partner_growth.get(bucket, [])])
            for entry in partner_growth.get(bucket, []):
                entry["name"] = names.get(entry["key"], {}).get("name", f"Partner {entry['key']}")
                entry["code"] = entry["key"]

        series = store.totals_series(code, "A")
        cagr_years = [row for row in series if row.get("exports") is not None]
        export_cagr = None
        if len(cagr_years) >= 6:
            span = min(10, len(cagr_years) - 1)
            export_cagr = {
                "value": analytics.cagr(cagr_years[-1 - span]["exports"],
                                        cagr_years[-1]["exports"], span),
                "from": cagr_years[-1 - span]["period"],
                "to": cagr_years[-1]["period"],
                "years": span,
            }

        export_hhi = [c for c in concentration if c["flow_code"] == "X" and c["dimension"] == "product"]
        sentences = insights.compile_insights([
            insights.product_concentration_sentence(
                name, export_products["items"][0]["name"], export_products["items"][0]["share"],
                "X", period_label) if export_products["items"] else None,
            insights.partner_sentence(
                name, export_partners["items"][0]["name"], export_partners["items"][0]["share"],
                "X", period_label) if export_partners["items"] else None,
            insights.dependency_sentence(dependency["export_partners"]["top3_share"], 3, "X", "partner"),
            insights.concentration_trend_sentence(
                name, export_hhi[0]["year"], export_hhi[0]["hhi"],
                export_hhi[-1]["year"], export_hhi[-1]["hhi"], "X") if len(export_hhi) >= 2 else None,
            insights.growth_contribution_sentence(
                product_growth["growing"][0]["name"], product_growth["growing"][0]["contribution"],
                "X", period_label) if product_growth.get("growing") else None,
            insights.balance_sentence(
                name, series[-1]["balance"], series[-1]["period"]) if series else None,
        ])

        return envelope(
            {
                "composition_period": period_label,
                "dependency": dependency,
                "concentration_history": concentration,
                "product_growth": product_growth,
                "import_growth": import_growth,
                "partner_growth": partner_growth,
                "export_cagr": export_cagr,
                "sentences": sentences,
                "top_export_products": export_products["items"][:5],
                "top_import_products": import_products["items"][:5],
                "top_export_partners": export_partners["items"][:5],
                "top_import_partners": import_partners["items"][:5],
            },
            build_meta(reporter, freq),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/{token}/macro")
def macro(token: str, request: Request, response: Response,
          year: int | None = Query(None)) -> Any:
    """Trade set against the size of the economy that produced it.

    GDP is published later than trade, so the year actually used is returned
    alongside the ratios rather than assumed to match.
    """
    reporter = resolve_reporter_or_404(token)
    code = int(reporter["reporter_code"])
    iso3 = reporter.get("iso3")

    scopes = [("totals", f"freq=A/reporter={code:03d}"), ("macro", "all")]
    params = f"macro:{code}:{year}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params, max_age=900):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        series = store.totals_series(code, "A")
        if not series:
            return envelope({"available": False, "reason": "No cached trade data"},
                            build_meta(reporter, "A"))
        latest = next((row for row in reversed(series)
                       if row["exports"] is not None and row["imports"] is not None), series[-1])
        target = year or latest["year"]
        point = next((row for row in series if row["year"] == target), latest)
        macro_row = worldbank.macro_for(iso3, target)
        ratios = worldbank.ratios(point, macro_row)

        history = []
        macro_by_year = {int(m["year"]): m for m in worldbank.macro_series(iso3)}
        for row in series:
            entry = macro_by_year.get(row["year"])
            if not entry or not entry.get("gdp_usd") or row["exports"] is None or row["imports"] is None:
                history.append({"year": row["year"], "openness": None, "gdp_usd": None})
                continue
            history.append({
                "year": row["year"],
                "openness": (row["exports"] + row["imports"]) / entry["gdp_usd"],
                "exports_over_gdp": row["exports"] / entry["gdp_usd"],
                "imports_over_gdp": row["imports"] / entry["gdp_usd"],
                "gdp_usd": entry["gdp_usd"],
            })

        return envelope(
            {
                **ratios,
                "trade_year": point["year"],
                "exports": point["exports"],
                "imports": point["imports"],
                "history": history,
                "note": "GDP and population come from the World Bank. Trade and GDP are "
                        "published on different schedules, so the GDP year is stated "
                        "separately and may lag the trade year.",
            },
            build_meta(reporter, "A", extra={"macro_source": "World Bank"}),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)
