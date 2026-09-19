"""World overview — the landing page.

Answers "what does world trade look like right now" before the reader has
picked a country. Everything is read from the precomputed world aggregate plus
the cached global HS2 matrix; nothing here can reach Comtrade.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response

from .. import analytics, derive, eurostat, imf, refs, store, worldbank
from ..api_common import apply_http_cache, envelope
from ..cache import cached
from ..state import dataset_versions_for
from .country import _name_lookup_products

router = APIRouter(prefix="/world", tags=["world"])

# Rankings of "fastest growing" are only meaningful among countries large
# enough that a percentage is not noise.
GROWTH_MIN_EXPORTS = 5_000_000_000.0

# A year is treated as usable for the world view once its reporter coverage
# reaches this fraction of the best-covered year in the cache.
COVERAGE_FLOOR = 0.75


def _iso3_lookup() -> tuple[dict[str, str], dict[str, int]]:
    """ISO3 to current reporter name and code.

    Comtrade keeps historical entities in the reporter list — "Belgium-Luxembourg
    (...1998)" carries the same ISO3 as Belgium — so an unfiltered pass over the
    list silently replaces a live country with a dissolved one. Groups and
    expired reporters are dropped, exactly as the world aggregate drops them.
    """
    import polars as pl

    reporters = refs.load_reporters().filter(
        ~pl.col("is_group") & ~pl.col("expired").fill_null(False)
    )
    names: dict[str, str] = {}
    codes: dict[str, int] = {}
    for row in reporters.to_dicts():
        iso3 = row.get("iso3")
        if not iso3:
            continue
        names[iso3] = row["name"]
        codes[iso3] = int(row["reporter_code"])
    return names, codes


@router.get("/overview")
def overview(request: Request, response: Response,
             year: int | None = Query(None), top: int = Query(10, ge=3, le=25)) -> Any:
    totals = derive.read_world_totals()
    if not totals:
        return envelope(
            {"available": False, "reason": "No countries cached yet"},
            {"source": "UN Comtrade", "available": False},
        )

    years = [int(row["year"]) for row in totals]
    # Choosing "the latest calendar-complete year" is not good enough here: most
    # countries publish an annual dataset months late, so the newest year can
    # contain a handful of fast reporters and understate world trade several
    # times over. Pick the most recent year whose reporter coverage is close to
    # the best coverage on record instead.
    coverage = {int(row["year"]): int(row["reporters"]) for row in totals}
    best = max(coverage.values()) if coverage else 0
    well_covered = [y for y in years if coverage.get(y, 0) >= COVERAGE_FLOOR * best]
    default_year = max(well_covered) if well_covered else max(years)
    target = year if year in years else default_year

    scopes = [("world", "all"), ("macro", "all"), ("global_hs2", f"year={target}")]
    params = f"world:{target}:{top}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params, max_age=900):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        row = next((r for r in totals if int(r["year"]) == target), None)
        previous = next((r for r in totals if int(r["year"]) == target - 1), None)

        countries = derive.read_world_countries(target)
        ranked = [c for c in countries if c["exports"] is not None]

        growth_pool = [
            c for c in ranked
            if c["export_yoy"] is not None and (c["exports"] or 0) >= GROWTH_MIN_EXPORTS
        ]
        growth_pool.sort(key=lambda c: c["export_yoy"], reverse=True)

        # World product composition, where the global matrix has been cached.
        products: dict[str, Any] = {"available": False}
        world_products = store.global_product_totals(target, "X")
        if world_products:
            names = _name_lookup_products(sorted(world_products))
            ordered = sorted(world_products.items(), key=lambda kv: kv[1], reverse=True)
            total = sum(world_products.values())
            head = ordered[:top]
            covered = sum(v for _, v in head)
            products = {
                "available": True,
                "items": [
                    {"code": code, "name": names.get(code, f"HS {code}"), "value": value,
                     "share": value / total if total else None}
                    for code, value in head
                ],
                "other": {"value": total - covered, "count": max(0, len(ordered) - len(head)),
                          "share": (total - covered) / total if total else None},
                "total": total,
            }

        macro = worldbank.load_macro()
        openness: list[dict[str, Any]] = []
        if macro.height:
            import polars as pl

            year_macro = {
                r["iso3"]: r
                for r in macro.filter(pl.col("year") == target).to_dicts()
            }
            for country in ranked:
                entry = year_macro.get(country["iso3"] or "")
                if not entry or not entry.get("gdp_usd") or not entry.get("gdp_per_capita"):
                    continue
                if country["exports"] is None or country["imports"] is None:
                    continue
                trade = country["exports"] + country["imports"]
                openness.append({
                    "code": int(country["reporter_code"]),
                    "iso3": country["iso3"],
                    "name": country["name"],
                    "gdp_per_capita": entry["gdp_per_capita"],
                    "openness": 100.0 * trade / entry["gdp_usd"],
                    "trade": trade,
                })
            openness.sort(key=lambda r: r["trade"], reverse=True)

        exports = row["exports"] if row else None
        imports = row["imports"] if row else None
        return envelope(
            {
                "available": True,
                "year": target,
                "years": years,
                "latest_complete": default_year,
                "partial": coverage.get(target, 0) < COVERAGE_FLOOR * best,
                "coverage_by_year": [
                    {"year": y, "reporters": coverage.get(y, 0)} for y in years
                ],
                "totals": {
                    "exports": exports,
                    "imports": imports,
                    "balance": analytics.trade_balance(exports, imports),
                    "reporters": int(row["reporters"]) if row else 0,
                    "export_change": analytics.percent_change(
                        exports, previous["exports"] if previous else None),
                    "import_change": analytics.percent_change(
                        imports, previous["imports"] if previous else None),
                },
                # Only years whose reporter coverage is comparable are plotted.
                # A year that a handful of fast reporters have published looks
                # like a collapse in world trade when it is really a gap in the
                # local cache, so it is omitted rather than drawn.
                "series": [
                    {"year": int(t["year"]), "period": str(int(t["year"])),
                     "exports": t["exports"], "imports": t["imports"],
                     "reporters": int(t["reporters"])}
                    for t in totals
                    if int(t["reporters"]) >= COVERAGE_FLOOR * best
                ],
                "series_note": (
                    f"Years reported by fewer than {int(COVERAGE_FLOOR * 100)}% of the "
                    f"best-covered year ({best} countries) are omitted, because partial "
                    "coverage would look like a fall in world trade."
                ),
                # Both choropleths carry every reporter that published for the
                # year. The ranked lists below are top-N; a map is not, because
                # an absent country there reads as "no reported data".
                # `change` and `imports` travel with every row because the
                # country directory sorts on them: without them a sort by
                # growth compared nulls and left the order untouched.
                "map": [
                    {"code": int(c["reporter_code"]), "iso3": c["iso3"], "name": c["name"],
                     "value": c["exports"], "share": c["export_share"],
                     "imports": c["imports"], "change": c["export_yoy"]}
                    for c in ranked if c["exports"]
                ],
                "map_imports": [
                    {"code": int(c["reporter_code"]), "iso3": c["iso3"], "name": c["name"],
                     "value": c["imports"], "share": c["import_share"]}
                    for c in countries if c["imports"]
                ],
                "top_traders": [
                    {"code": int(c["reporter_code"]), "iso3": c["iso3"], "name": c["name"],
                     "value": c["exports"], "share": c["export_share"], "change": c["export_yoy"]}
                    for c in ranked[:top]
                ],
                "top_importers": [
                    {"code": int(c["reporter_code"]), "iso3": c["iso3"], "name": c["name"],
                     "value": c["imports"]}
                    for c in sorted(
                        [c for c in countries if c["imports"] is not None],
                        key=lambda c: c["imports"], reverse=True)[:top]
                ],
                "fastest_growing": [
                    {"code": int(c["reporter_code"]), "iso3": c["iso3"], "name": c["name"],
                     "value": c["exports"], "change": c["export_yoy"]}
                    for c in growth_pool[:top]
                ],
                "largest_declines": [
                    {"code": int(c["reporter_code"]), "iso3": c["iso3"], "name": c["name"],
                     "value": c["exports"], "change": c["export_yoy"]}
                    for c in reversed(growth_pool[-top:]) if c["export_yoy"] < 0
                ],
                "products": products,
                "openness": openness[:90],
                "coverage": {
                    "reporters": int(row["reporters"]) if row else 0,
                    "note": "Totals are the sum of what reporting countries published for "
                            "this period. Countries that had not reported are absent, so "
                            "this is reported world trade rather than a complete world total. "
                            "A handful of city-states and small islands — Hong Kong, "
                            "Singapore, Macao and others — report but have no polygon at "
                            "this map's resolution, so they are unshaded here and appear in "
                            "the rankings instead.",
                },
            },
            {
                "source": "UN Comtrade",
                "macro_source": "World Bank",
                "frequency": "annual",
                "classification": "HS (as reported)",
                "measure": "Trade value (current USD)",
                "year": target,
                "partial": coverage.get(target, 0) < COVERAGE_FLOOR * best,
                "available": True,
            },
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)


@router.get("/recent")
def recent(request: Request, response: Response) -> Any:
    """The newest reading available, from the IMF rather than Comtrade.

    Comtrade is the spine of this product and the only source with partner and
    product detail, but a reference year takes one to two years to fill in. The
    IMF's ITG collection carries the same headline aggregates months earlier.

    The two are never summed. This endpoint is entirely IMF-sourced and says so;
    the Comtrade view at /world/overview is untouched by it.
    """
    scopes = [("imf_itg", "all")]
    if apply_http_cache(request, response, version_scopes=scopes, params="recent", max_age=1800):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        coverage = imf.annual_coverage()
        if not coverage:
            return envelope(
                {"available": False, "reason": "IMF ITG not cached yet"},
                {"source": "IMF International Trade in Goods", "available": False},
            )

        year = max(coverage)
        totals = imf.world_totals(year)
        previous = imf.world_totals(year - 1)
        rows = imf.countries_for(year)

        names, codes = _iso3_lookup()

        world_exports = totals["exports"] if totals else None
        ranked = [
            {
                "code": codes.get(r["iso3"], 0),
                "iso3": r["iso3"],
                "name": names.get(r["iso3"], r["iso3"]),
                "value": r["exports"],
                "share": (r["exports"] / world_exports) if world_exports and r["exports"] else None,
            }
            for r in rows if r["exports"]
        ]

        month = imf.latest_month()
        monthly = None
        if month:
            frame_month = str(month["period"])
            monthly = {
                "period": frame_month,
                "label": f"{frame_month[:4]}-{frame_month[4:]}",
                "countries": imf.monthly_country_count(frame_month),
            }

        # What this adds over the Comtrade view, stated plainly rather than
        # implied by a fresher-looking number.
        comtrade_coverage = {
            int(r["year"]): int(r["reporters"]) for r in derive.read_world_totals()
        }
        return envelope(
            {
                "available": True,
                "year": year,
                "countries": coverage[year],
                "comtrade_countries": comtrade_coverage.get(year, 0),
                "totals": {
                    "exports": totals["exports"] if totals else None,
                    "imports": totals["imports"] if totals else None,
                    "balance": analytics.trade_balance(
                        totals["exports"] if totals else None,
                        totals["imports"] if totals else None),
                    "export_change": analytics.percent_change(
                        totals["exports"] if totals else None,
                        previous["exports"] if previous else None),
                    "import_change": analytics.percent_change(
                        totals["imports"] if totals else None,
                        previous["imports"] if previous else None),
                },
                "map": ranked,
                "top_traders": ranked[:12],
                "monthly": monthly,
                "coverage": {
                    "countries": coverage[year],
                    "by_year": [{"year": y, "countries": coverage[y]} for y in sorted(coverage)],
                    "note": "Goods only, exports free-on-board and imports "
                            "cost-insurance-freight, so world imports exceed world "
                            "exports by roughly the cost of freight. Totals only: "
                            "this source carries no partner or product breakdown, "
                            "which is why the rest of the site reads from UN Comtrade.",
                },
            },
            {
                "source": "IMF International Trade in Goods (ITG)",
                "frequency": "annual",
                "measure": "Trade value (current USD)",
                "valuation": imf.valuation_note(),
                "year": year,
                "available": True,
            },
        )

    return cached(f"recent:{dataset_versions_for(scopes)}", build)


@router.get("/europe")
def europe(request: Request, response: Response) -> Any:
    """How much of each member state's trade stays inside the single market.

    Comtrade sees the Union as twenty-seven reporters with bilateral partners
    and cannot express this split without summing twenty-six partners per
    country. Eurostat collects it directly — Intrastat inside the border,
    customs outside it — and publishes about six weeks after month end.

    Figures are euro, not dollars, and are never added to anything else on the
    site. The shares are the point: they hold regardless of currency.
    """
    scopes = [("eurostat", "all")]
    if apply_http_cache(request, response, version_scopes=scopes, params="europe", max_age=1800):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        period = eurostat.latest_period()
        if period is None:
            return envelope(
                {"available": False, "reason": "Eurostat not cached yet"},
                {"source": "Eurostat", "available": False},
            )

        members = eurostat.member_splits(period)
        names, _ = _iso3_lookup()
        for row in members:
            row["name"] = names.get(row["iso3"], row["iso3"])

        intra_exports = sum(
            (m["exports_eur"] or 0) * (m["intra_export_share"] or 0) for m in members)
        total_exports = sum(m["exports_eur"] or 0 for m in members)

        return envelope(
            {
                "available": True,
                "period": period,
                "label": f"{period[:4]}-{period[4:]}",
                "member_states": len(members),
                "union": {
                    "exports_eur": total_exports,
                    "intra_share": (intra_exports / total_exports) if total_exports else None,
                    "extra_share": (1 - intra_exports / total_exports) if total_exports else None,
                },
                "members": members,
                "coverage": {
                    "note": "Intra-EU movements are collected through Intrastat "
                            "declarations and extra-EU movements at the customs "
                            "frontier, so the split is reported rather than derived. "
                            "Values are euro; every other figure on this site is US "
                            "dollars, and the two are never added together.",
                },
            },
            {
                "source": "Eurostat (ext_st_27_2020msbec)",
                "frequency": "monthly",
                "measure": "Trade value (current EUR)",
                "period": period,
                "available": True,
            },
        )

    return cached(f"europe:{dataset_versions_for(scopes)}", build)


@router.get("/product/{hs_code}")
def world_product(hs_code: str, request: Request, response: Response,
                  year: int | None = Query(None), top: int = Query(15, ge=5, le=40)) -> Any:
    """Everything the product page needs: who sells a chapter, who buys it, and
    how concentrated that is.

    Read from the global HS2 matrix, which holds one row per reporter, flow and
    chapter for each year it has been built for.
    """
    from ..api_common import require_hs_code

    code = require_hs_code(hs_code)
    years = store.global_years()
    if not years:
        return envelope({"available": False, "reason": "World product data not available"},
                        {"source": "UN Comtrade", "available": False})
    target = year if year in years else max(years)

    scopes = [("global_hs2", f"year={y}") for y in years]
    params = f"worldproduct:{code}:{target}:{top}"
    if apply_http_cache(request, response, version_scopes=scopes, params=params, max_age=900):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        import polars as pl

        reporters = refs.load_reporters()
        lookup = {int(r["reporter_code"]): r for r in reporters.to_dicts()}

        def side(frame: pl.DataFrame, flow: str) -> tuple[list[dict[str, Any]], float, int]:
            rows_frame = frame.filter(
                (pl.col("hs_code") == code) & (pl.col("flow_code") == flow))
            if rows_frame.height == 0:
                return [], 0.0, 0
            totals = (
                rows_frame.group_by("reporter_code")
                .agg(pl.col("primary_value").sum().alias("value"))
                .sort("value", descending=True)
            )
            world_total = float(totals["value"].sum())
            out = []
            for entry in totals.head(top).to_dicts():
                meta = lookup.get(int(entry["reporter_code"]), {})
                out.append({
                    "code": int(entry["reporter_code"]),
                    "name": meta.get("name", str(entry["reporter_code"])),
                    "iso2": meta.get("iso2"),
                    "iso3": meta.get("iso3"),
                    "value": float(entry["value"]),
                    "share": float(entry["value"]) / world_total if world_total else None,
                })
            return out, world_total, int(totals.height)

        frame = pl.read_parquet(store.global_year_path(target))
        exporters, export_total, export_reporters = side(frame, "X")
        importers, import_total, import_reporters = side(frame, "M")

        if not exporters and not importers:
            return envelope({"available": False, "reason": "No reported data for this chapter"},
                            {"source": "UN Comtrade", "available": False})

        # Concentration across *all* exporters, not just the ones listed: a
        # top-15 HHI would say more about the cut-off than about the market.
        all_export = (
            frame.filter((pl.col("hs_code") == code) & (pl.col("flow_code") == "X"))
            .group_by("reporter_code")
            .agg(pl.col("primary_value").sum().alias("value"))
        )
        concentration = analytics.hhi(all_export["value"].to_list()) if all_export.height else None

        # World trade in the chapter across every year the matrix holds, so the
        # page can show a trajectory rather than a single figure.
        series = []
        for entry_year in years:
            year_frame = pl.read_parquet(store.global_year_path(entry_year)).filter(
                (pl.col("hs_code") == code) & (pl.col("flow_code") == "X"))
            if year_frame.height == 0:
                continue
            series.append({
                "year": entry_year,
                "period": str(entry_year),
                "value": float(year_frame["primary_value"].sum()),
                "reporters": int(year_frame["reporter_code"].n_unique()),
            })

        previous = next((p["value"] for p in series if p["year"] == target - 1), None)
        current = next((p["value"] for p in series if p["year"] == target), None)

        return envelope(
            {
                "available": True,
                "code": code,
                "name": refs.hs_name(code) or f"HS {code}",
                "year": target,
                "years": years,
                "world_total": export_total,
                "world_import_total": import_total,
                "change": analytics.percent_change(current, previous),
                "concentration": concentration,
                "exporters": exporters,
                "importers": importers,
                "reporters": export_reporters,
                "import_reporters": import_reporters,
                "series": series,
                "coverage": {
                    "note": "Chapter totals are the sum of what reporting countries "
                            "published for the year, so this is reported world trade in "
                            "the chapter rather than a complete total. Exports are "
                            "free-on-board and imports cost-insurance-freight, which is "
                            "why the two sides do not match.",
                },
            },
            {"source": "UN Comtrade", "year": target, "available": True,
             "classification": "HS (as reported)",
             "measure": "Trade value (current USD)"},
        )

    return cached(f"{params}:{dataset_versions_for(scopes)}", build)
