"""Product and bilateral drilldowns, plus the bounded network view."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import analytics, refs, store
from ..api_common import (
    apply_http_cache, build_meta, envelope, preparing_response, ranking_periods,
    require_flow, require_frequency, require_hs_code, require_top_n,
    resolve_partner_or_404, resolve_reporter_or_404, series_periods,
)
from ..cache import cached
from ..state import dataset_versions_for
from .country import (
    _decorate_partners, _decorate_products, _label, _name_lookup_partners,
    _name_lookup_products, _series_window, _yoy,
)

router = APIRouter(prefix="/country", tags=["drilldown"])


def _period_list_for_job(reporter: int, freq: str) -> list[str]:
    latest = store.latest_period(reporter, freq)
    if not latest:
        return []
    if freq == "A":
        available = [int(y) for y in latest["available"]]
        return [str(y) for y in sorted(available)[-12:]]
    return sorted(latest["available"][:36])


@router.get("/{token}/product/{hs_code}")
def product_detail(token: str, hs_code: str, request: Request, response: Response,
                   freq: str = Query("A"), flow: str = Query("X")) -> Any:
    """Trend, share, change, HS4 breakdown and destinations for one category."""
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    flow = require_flow(flow)
    hs_code = require_hs_code(hs_code)
    code = int(reporter["reporter_code"])

    dataset = "products_hs2" if len(hs_code) == 2 else "products_hs4"
    if not store.has_dataset(dataset, code, freq):
        payload = preparing_response(request, "country_hs4", {"reporter": code},
                                     "Preparing detailed product data")
        response.status_code = 202
        return envelope(payload, build_meta(reporter, freq))

    scopes = [(dataset, f"freq={freq}/reporter={code:03d}"),
              ("products_hs4", f"freq={freq}/reporter={code:03d}"),
              ("totals", f"freq={freq}/reporter={code:03d}")]
    params = f"product:{code}:{freq}:{flow}:{hs_code}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        periods = ranking_periods(code, freq)
        series = store.product_series(code, freq, hs_code)
        totals = _series_window(code, freq, "all" if freq == "A" else "60")
        field = "exports" if flow == "X" else "imports"

        latest_value = series[-1][field] if series else None
        total_latest = totals[-1][field] if totals else None
        share = (latest_value / total_latest) if latest_value and total_latest else None

        children = {"items": [], "available": False}
        if len(hs_code) == 2 and store.has_dataset("products_hs4", code, freq):
            children = _decorate_products(
                store.product_children(code, freq, hs_code, periods, flow))

        partners = store.product_partner_ranking(code, freq, hs_code, periods, flow)
        partners_status = "ready"
        if not partners["available"] and len(hs_code) == 2:
            job_periods = _period_list_for_job(code, freq)
            if job_periods:
                preparing_response(request, "product_partners",
                                   {"reporter": code, "hs_code": hs_code, "freq": freq,
                                    "periods": job_periods},
                                   "Preparing partner detail for this category")
                partners_status = "preparing"
        else:
            partners = _decorate_partners(partners)

        weight_field = "export_weight" if flow == "X" else "import_weight"
        unit_values = [
            {"period": row["period"],
             "unit_value": analytics.unit_value(row[field], row[weight_field])}
            for row in series
        ]
        has_unit_values = any(u["unit_value"] is not None for u in unit_values)

        name = refs.hs_name(hs_code) or f"HS {hs_code}"
        classification_note = (
            "HS revisions change over time. Codes are shown as reported by the "
            "source for each period and are not converted between revisions."
        )
        return envelope(
            {
                "code": hs_code,
                "name": name,
                "level": len(hs_code),
                "flow": flow,
                "value": latest_value,
                "share_of_flow": share,
                "change": _yoy(series, field, freq),
                "series": series,
                "children": children,
                "partners": partners,
                "partners_status": partners_status,
                "unit_values": unit_values if has_unit_values else [],
                "composition_period": _label(periods, freq),
                "classification_note": classification_note,
            },
            build_meta(reporter, freq),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/{token}/product/{hs_code}/partners")
def product_partners(token: str, hs_code: str, request: Request, response: Response,
                     freq: str = Query("A"), flow: str = Query("X"),
                     top: int = Query(10)) -> Any:
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    flow = require_flow(flow)
    hs_code = require_hs_code(hs_code)
    top = require_top_n(top)
    code = int(reporter["reporter_code"])
    periods = ranking_periods(code, freq)

    payload = store.product_partner_ranking(code, freq, hs_code, periods, flow, top_n=top)
    if not payload["available"]:
        job_periods = _period_list_for_job(code, freq)
        if not job_periods:
            raise HTTPException(404, "No cached periods for this reporter")
        prep = preparing_response(request, "product_partners",
                                  {"reporter": code, "hs_code": hs_code, "freq": freq,
                                   "periods": job_periods},
                                  "Preparing partner detail for this category")
        response.status_code = 202
        return envelope(prep, build_meta(reporter, freq))

    scope = f"freq={freq}/reporter={code:03d}/hs={hs_code}"
    if apply_http_cache(request, response,
                        version_scopes=[("product_partner", scope)],
                        params=f"pp:{code}:{freq}:{flow}:{hs_code}:{top}"):
        return Response(status_code=304)
    return envelope(_decorate_partners(payload),
                    build_meta(reporter, freq,
                               extra={"composition_period": _label(periods, freq)}))


@router.get("/{token}/partner/{partner_token}")
def partner_detail(token: str, partner_token: str, request: Request, response: Response,
                   freq: str = Query("A"), range: str | None = Query(None),
                   top: int = Query(10)) -> Any:
    """Bilateral view: two-way flows, balance, shares and product composition."""
    reporter = resolve_reporter_or_404(token)
    partner = resolve_partner_or_404(partner_token)
    freq = require_frequency(freq)
    top = require_top_n(top)
    code = int(reporter["reporter_code"])
    partner_code = int(partner["partner_code"])

    if not store.has_dataset("partners", code, freq):
        payload = preparing_response(
            request, "country_annual" if freq == "A" else "country_monthly",
            {"reporter": code} if freq == "A" else {"reporter": code, "months": 36},
            f"Preparing trade data for {reporter['name']}")
        response.status_code = 202
        return envelope(payload, build_meta(reporter, freq))

    scopes = [("partners", f"freq={freq}/reporter={code:03d}"),
              ("partner_products", f"freq={freq}/reporter={code:03d}/partner={partner_code:03d}"),
              ("totals", f"freq={freq}/reporter={code:03d}")]
    params = f"partner:{code}:{freq}:{partner_code}:{range}:{top}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        series = store.partner_series(code, freq, partner_code)
        if freq == "A":
            start, end = series_periods(code, freq, range)
            if start is not None:
                series = [row for row in series if start <= row["year"] <= end]
        else:
            from ..api_common import monthly_series_periods

            series = series[-monthly_series_periods(range):]

        totals = _series_window(code, freq, "all" if freq == "A" else "60")
        periods = ranking_periods(code, freq)

        latest = series[-1] if series else {}
        totals_latest = next((t for t in reversed(totals)
                              if t["period"] == latest.get("period")), None)
        export_share = None
        import_share = None
        if totals_latest:
            if latest.get("exports") and totals_latest.get("exports"):
                export_share = latest["exports"] / totals_latest["exports"]
            if latest.get("imports") and totals_latest.get("imports"):
                import_share = latest["imports"] / totals_latest["imports"]

        export_products = store.partner_product_ranking(code, freq, partner_code,
                                                        periods, "X", top_n=top)
        import_products = store.partner_product_ranking(code, freq, partner_code,
                                                        periods, "M", top_n=top)
        products_status = "ready"
        if not export_products["available"] and not import_products["available"]:
            job_periods = _period_list_for_job(code, freq)
            if job_periods:
                preparing_response(request, "partner_products",
                                   {"reporter": code, "partner": partner_code, "freq": freq,
                                    "periods": job_periods},
                                   "Preparing bilateral product composition")
                products_status = "preparing"
        else:
            export_products = _decorate_products(export_products)
            import_products = _decorate_products(import_products)

        return envelope(
            {
                "partner": {"code": partner_code, "name": partner["name"],
                            "iso3": partner.get("iso3"), "iso2": partner.get("iso2")},
                "series": series,
                "exports": latest.get("exports"),
                "imports": latest.get("imports"),
                "balance": latest.get("balance"),
                "period": latest.get("period"),
                "export_share_of_total": export_share,
                "import_share_of_total": import_share,
                "export_change": _yoy(series, "exports", freq),
                "import_change": _yoy(series, "imports", freq),
                "export_products": export_products,
                "import_products": import_products,
                "products_status": products_status,
                "composition_period": _label(periods, freq),
            },
            build_meta(reporter, freq),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/{token}/partner/{partner_token}/products")
def partner_products(token: str, partner_token: str, request: Request, response: Response,
                     freq: str = Query("A"), flow: str = Query("X"),
                     top: int = Query(10)) -> Any:
    reporter = resolve_reporter_or_404(token)
    partner = resolve_partner_or_404(partner_token)
    freq = require_frequency(freq)
    flow = require_flow(flow)
    top = require_top_n(top)
    code = int(reporter["reporter_code"])
    partner_code = int(partner["partner_code"])
    periods = ranking_periods(code, freq)

    payload = store.partner_product_ranking(code, freq, partner_code, periods, flow, top_n=top)
    if not payload["available"]:
        job_periods = _period_list_for_job(code, freq)
        prep = preparing_response(request, "partner_products",
                                  {"reporter": code, "partner": partner_code, "freq": freq,
                                   "periods": job_periods},
                                  "Preparing bilateral product composition")
        response.status_code = 202
        return envelope(prep, build_meta(reporter, freq))
    return envelope(_decorate_products(payload),
                    build_meta(reporter, freq,
                               extra={"composition_period": _label(periods, freq)}))


@router.get("/{token}/network")
def network(token: str, request: Request, response: Response,
            freq: str = Query("A"), flow: str = Query("X"),
            products: int = Query(8, ge=3, le=12),
            partners_n: int = Query(10, ge=3, le=15)) -> Any:
    """Bounded Sankey: top products -> country -> top partners, everything else
    aggregated into an explicit "Other" node."""
    reporter = resolve_reporter_or_404(token)
    freq = require_frequency(freq)
    flow = require_flow(flow)
    code = int(reporter["reporter_code"])
    scopes = [("products_hs2", f"freq={freq}/reporter={code:03d}"),
              ("partners", f"freq={freq}/reporter={code:03d}")]
    params = f"network:{code}:{freq}:{flow}:{products}:{partners_n}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        periods = ranking_periods(code, freq)
        product_payload = _decorate_products(
            store.product_ranking(code, freq, periods, flow, level=2, top_n=products))
        partner_payload = _decorate_partners(
            store.partner_ranking(code, freq, periods, flow, top_n=partners_n))
        if not product_payload["items"] or not partner_payload["items"]:
            return envelope({"available": False, "nodes": [], "links": []},
                            build_meta(reporter, freq))

        country_node = reporter["name"]
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []

        for item in product_payload["items"]:
            label = f"{item['code']} {item['name']}"[:46]
            nodes.append({"name": label, "kind": "product", "code": item["code"]})
            links.append({"source": label, "target": country_node, "value": item["value"]})
        if product_payload.get("other") and product_payload["other"]["value"] > 0:
            nodes.append({"name": "Other products", "kind": "product-other"})
            links.append({"source": "Other products", "target": country_node,
                          "value": product_payload["other"]["value"]})

        nodes.append({"name": country_node, "kind": "country"})

        for item in partner_payload["items"]:
            label = item["name"][:46]
            nodes.append({"name": label, "kind": "partner", "code": item["code"]})
            links.append({"source": country_node, "target": label, "value": item["value"]})
        if partner_payload.get("other") and partner_payload["other"]["value"] > 0:
            nodes.append({"name": "Other partners", "kind": "partner-other"})
            links.append({"source": country_node, "target": "Other partners",
                          "value": partner_payload["other"]["value"]})

        return envelope(
            {"available": True, "nodes": nodes, "links": links, "flow": flow,
             "composition_period": _label(periods, freq)},
            build_meta(reporter, freq),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)
