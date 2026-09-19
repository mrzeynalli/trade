"""Tier-3 analytics: global position, similarity, complementarity, mirror trade,
monthly anomalies. Each degrades to "not enough data" rather than inventing a
number."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response

from .. import analytics, jobs, refs, store
from ..api_common import (
    apply_http_cache, build_meta, envelope, preparing_response, ranking_periods,
    require_frequency, resolve_partner_or_404, resolve_reporter_or_404,
)
from ..cache import cached
from ..state import dataset_versions_for
from .country import _name_lookup_partners, _name_lookup_products

router = APIRouter(tags=["advanced"])

NOT_ENOUGH = {"available": False, "reason": "Not enough data"}


@router.get("/country/{token}/advanced")
def advanced(token: str, request: Request, response: Response,
             year: int | None = Query(None), top: int = Query(10, ge=3, le=25)) -> Any:
    """Global market share, RCA and export similarity for the selected country.

    All three need the cached global HS2 matrix. Where a year of that matrix is
    missing the section reports that rather than guessing.
    """
    reporter = resolve_reporter_or_404(token)
    code = int(reporter["reporter_code"])
    available_years = store.global_years()

    if not available_years:
        payload = {"global_share": NOT_ENOUGH, "rca": NOT_ENOUGH, "similarity": NOT_ENOUGH,
                   "coverage": {"available": False}}
        return envelope(payload, build_meta(reporter, "A"))

    latest_local = store.latest_period(code, "A")
    target = year or (latest_local or {}).get("latest_complete") or max(available_years)
    if target not in available_years:
        target = max(y for y in available_years if y <= target) if any(
            y <= target for y in available_years) else max(available_years)

    scopes = [("global_hs2", f"year={target}"),
              ("products_hs2", f"freq=A/reporter={code:03d}")]
    params = f"advanced:{code}:{target}:{top}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params, max_age=600):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        world_products = store.global_product_totals(target, "X")
        country_products = store.global_reporter_products(target, code, "X")
        if not country_products:
            # The country is absent from the global matrix for this year.
            local = store.product_ranking(code, "A", [str(target)], "X", level=2, top_n=10_000)
            country_products = {item["key"]: item["value"] for item in local["items"]}

        world_total = sum(world_products.values())
        country_total = sum(country_products.values())
        names = _name_lookup_products(sorted(set(country_products) | set(world_products)))

        share_rows = []
        rca_rows = []
        for hs_code, value in sorted(country_products.items(), key=lambda kv: kv[1], reverse=True):
            world_value = world_products.get(hs_code)
            share = analytics.world_share(value, world_value)
            rca = analytics.balassa_rca(value, country_total, world_value, world_total)
            entry = {"code": hs_code, "name": names.get(hs_code, f"HS {hs_code}"),
                     "value": value, "world_value": world_value}
            if share is not None:
                share_rows.append({**entry, "share": share})
            if rca is not None:
                rca_rows.append({**entry, "rca": rca,
                                 "country_share": value / country_total if country_total else None,
                                 "world_share": world_value / world_total if world_total else None})

        share_rows.sort(key=lambda r: r["share"], reverse=True)
        rca_rows.sort(key=lambda r: r["rca"], reverse=True)

        similarity = _similarity(target, code, country_products, top)
        coverage = store.global_coverage(target)

        return envelope(
            {
                "year": target,
                "available_years": available_years,
                "global_share": {"available": bool(share_rows), "items": share_rows[:top],
                                 "note": "Denominator is reported world exports for the "
                                         "reporters that had published for this year."},
                "rca": {"available": bool(rca_rows), "items": rca_rows[:top],
                        "note": "Balassa index. Above 1 means the product is a larger share "
                                "of this country's exports than of reported world exports."},
                "similarity": similarity,
                "coverage": coverage,
            },
            build_meta(reporter, "A"),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


def _similarity(year: int, code: int, country_products: dict[str, float], top: int) -> dict[str, Any]:
    total = sum(country_products.values())
    if total <= 0:
        return NOT_ENOUGH
    own_shares = {k: v / total for k, v in country_products.items()}
    all_shares = store.global_reporter_shares(year, "X")
    if len(all_shares) < 5:
        return NOT_ENOUGH
    reporters = refs.load_reporters()
    names = {int(r["reporter_code"]): r for r in reporters.to_dicts()}
    rows = []
    for other, shares in all_shares.items():
        if other == code:
            continue
        entry = names.get(other)
        if entry is None or entry.get("is_group"):
            continue
        score = analytics.export_similarity(own_shares, shares)
        if score is None:
            continue
        rows.append({"code": other, "name": entry["name"], "iso3": entry.get("iso3"),
                     "similarity": score})
    rows.sort(key=lambda r: r["similarity"], reverse=True)
    return {
        "available": bool(rows), "items": rows[:top],
        "note": "Finger-Kreinin index over HS2 export shares. 100 means identical "
                "export baskets; 0 means no overlap.",
    }


@router.get("/pair/{token}/{partner_token}/mirror")
def mirror(token: str, partner_token: str, request: Request, response: Response,
           freq: str = Query("A")) -> Any:
    """Compare the reporter's exports to a partner with the partner's own
    reported imports from the reporter."""
    reporter = resolve_reporter_or_404(token)
    partner = resolve_partner_or_404(partner_token)
    freq = require_frequency(freq)
    code = int(reporter["reporter_code"])
    partner_code = int(partner["partner_code"])

    counterpart = refs.resolve_reporter(str(partner_code))
    if counterpart is None:
        return envelope(
            {"available": False,
             "reason": f"{partner['name']} does not report to Comtrade as a reporter."},
            build_meta(reporter, freq),
        )

    own = {row["period"]: row for row in store.partner_series(code, freq, partner_code)}
    mirrored = {row["period"]: row for row in store.partner_series(partner_code, freq, code)}

    if not mirrored:
        periods = sorted(own.keys())[-12:]
        if not periods:
            return envelope({"available": False, "reason": "No cached bilateral data"},
                            build_meta(reporter, freq))
        prep = preparing_response(request, "mirror",
                                  {"mirror_reporter": partner_code, "counterpart": code,
                                   "freq": freq, "periods": periods},
                                  f"Fetching {partner['name']}'s own reporting")
        response.status_code = 202
        return envelope({**prep, "available": False}, build_meta(reporter, freq))

    scopes = [("partners", f"freq={freq}/reporter={code:03d}"),
              ("partners", f"freq={freq}/reporter={partner_code:03d}")]
    params = f"mirror:{code}:{partner_code}:{freq}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        rows = []
        for period in sorted(set(own) | set(mirrored)):
            exports = own.get(period, {}).get("exports")
            counter_imports = mirrored.get(period, {}).get("imports")
            rows.append({"period": period,
                         **analytics.mirror_discrepancy(exports, counter_imports)})
        return envelope(
            {
                "available": True,
                "reporter": {"code": code, "name": reporter["name"]},
                "counterpart": {"code": partner_code, "name": partner["name"]},
                "series": rows,
                "note": "Reporter A's exports to B need not equal B's imports from A. "
                        "Common reasons include CIF versus FOB valuation, shipment "
                        "timing across a period boundary, re-exports, rules of origin, "
                        "partner attribution and later revisions. A difference is not "
                        "in itself evidence of misreporting.",
            },
            build_meta(reporter, freq),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/pair/{token}/{partner_token}/complementarity")
def complementarity(token: str, partner_token: str, request: Request, response: Response,
                    year: int | None = Query(None)) -> Any:
    """Trade complementarity between the reporter's export basket and the
    partner's import basket."""
    reporter = resolve_reporter_or_404(token)
    partner = resolve_partner_or_404(partner_token)
    code = int(reporter["reporter_code"])
    partner_code = int(partner["partner_code"])

    counterpart_cached = store.has_dataset("products_hs2", partner_code, "A")
    if not counterpart_cached:
        prep = preparing_response(request, "country_annual", {"reporter": partner_code},
                                  f"Preparing {partner['name']}'s product data")
        response.status_code = 202
        return envelope({**prep, "available": False}, build_meta(reporter, "A"))

    latest_a = store.latest_period(code, "A") or {}
    latest_b = store.latest_period(partner_code, "A") or {}
    candidates = sorted(set(latest_a.get("available", [])) & set(latest_b.get("available", [])))
    if not candidates:
        return envelope({"available": False, "reason": "No overlapping cached years"},
                        build_meta(reporter, "A"))
    target = year if year in candidates else candidates[-1]

    scopes = [("products_hs2", f"freq=A/reporter={code:03d}"),
              ("products_hs2", f"freq=A/reporter={partner_code:03d}")]
    params = f"tci:{code}:{partner_code}:{target}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        exports = {i["key"]: i["value"] for i in store.product_ranking(
            code, "A", [str(target)], "X", level=2, top_n=10_000)["items"]}
        imports = {i["key"]: i["value"] for i in store.product_ranking(
            partner_code, "A", [str(target)], "M", level=2, top_n=10_000)["items"]}
        index = analytics.trade_complementarity(exports, imports)
        return envelope(
            {
                "available": index is not None,
                "year": target,
                "index": index,
                "reporter": reporter["name"],
                "partner": partner["name"],
                "note": "TCI = 100 x (1 - 0.5 x sum|m_k - x_k|) over HS2 shares, where x is "
                        f"{reporter['name']}'s export mix and m is {partner['name']}'s import "
                        "mix. 100 means the baskets match exactly.",
            },
            build_meta(reporter, "A"),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/country/{token}/anomalies")
def anomalies(token: str, request: Request, response: Response,
              flow: str = Query("X")) -> Any:
    """Unusual monthly movements, measured on year-on-year growth so that trend
    and seasonality are already removed."""
    reporter = resolve_reporter_or_404(token)
    code = int(reporter["reporter_code"])
    from ..config import get_settings

    settings = get_settings()

    if not store.has_dataset("totals", code, "M"):
        return envelope({"available": False, "reason": "No monthly data cached"},
                        build_meta(reporter, "M"))

    scopes = [("totals", f"freq=M/reporter={code:03d}"),
              ("products_hs2", f"freq=M/reporter={code:03d}")]
    params = f"anomalies:{code}:{flow}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        field = "exports" if flow.upper() == "X" else "imports"
        series = store.totals_series(code, "M")
        periods = [row["period"] for row in series]
        values = [row[field] for row in series]
        total_anomalies = analytics.detect_monthly_anomalies(
            periods, values, min_months=settings.anomaly_min_months,
            threshold=settings.anomaly_z_threshold)

        product_anomalies: list[dict[str, Any]] = []
        if store.has_dataset("products_hs2", code, "M"):
            ranking = store.product_ranking(
                code, "M", sorted({p for p in periods})[-12:], flow.upper(),
                level=2, top_n=6)
            names = _name_lookup_products([i["key"] for i in ranking["items"]])
            for item in ranking["items"]:
                rows = store.product_series(code, "M", item["key"])
                found = analytics.detect_monthly_anomalies(
                    [r["period"] for r in rows], [r[field] for r in rows],
                    min_months=settings.anomaly_min_months,
                    threshold=settings.anomaly_z_threshold)
                for anomaly in found[:2]:
                    product_anomalies.append({
                        "code": item["key"], "name": names.get(item["key"], item["key"]),
                        "period": anomaly.period, "value": anomaly.value,
                        "yoy": anomaly.yoy, "robust_z": anomaly.robust_z,
                        "direction": anomaly.direction,
                    })
        product_anomalies.sort(key=lambda a: abs(a["robust_z"]), reverse=True)

        return envelope(
            {
                "available": bool(total_anomalies or product_anomalies),
                "months_observed": len([v for v in values if v is not None]),
                "min_months_required": settings.anomaly_min_months,
                "totals": [
                    {"period": a.period, "value": a.value, "yoy": a.yoy,
                     "robust_z": a.robust_z, "direction": a.direction}
                    for a in total_anomalies[:6]
                ],
                "products": product_anomalies[:8],
                "note": "Flags months whose year-on-year growth sits far from this "
                        "series' own historical distribution (median/MAD robust "
                        "z-score). It is a statistical marker, not an explanation.",
            },
            build_meta(reporter, "M"),
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)
