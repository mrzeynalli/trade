"""Reference metadata: the country selector and the HS hierarchy."""

from __future__ import annotations

from typing import Any

import polars as pl
from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import refs, state, store
from ..api_common import apply_http_cache
from ..cache import cached

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/countries")
def countries(request: Request, response: Response,
              include_groups: bool = Query(False)) -> Any:
    """Reporter territories. Aggregate groups are excluded by default so the
    selector offers countries rather than confusing composite entries."""
    if apply_http_cache(request, response, version_scopes=[("refs", "all")],
                        params=f"countries:{include_groups}", max_age=86400):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        frame = refs.load_reporters()
        if frame.height == 0:
            return {"data": [], "meta": {"source": "UN Comtrade", "available": False}}
        if not include_groups:
            # Aggregates and historical territories are hidden by default so the
            # selector offers reporting countries rather than confusing entries.
            frame = frame.filter(~pl.col("is_group") & ~pl.col("expired").fill_null(False))
        cached_a = set(store.cached_reporters("A"))
        cached_m = set(store.cached_reporters("M"))
        rows = [
            {
                "code": int(r["reporter_code"]),
                "name": r["name"],
                "iso2": r["iso2"],
                "iso3": r["iso3"],
                "is_group": bool(r["is_group"]),
                "expired": bool(r["expired"]),
                "cached": int(r["reporter_code"]) in cached_a,
                "cached_monthly": int(r["reporter_code"]) in cached_m,
            }
            for r in frame.sort("name").to_dicts()
        ]
        return {
            "data": rows,
            "meta": {"source": "UN Comtrade", "count": len(rows),
                     "cached_countries": len(cached_a), "available": True},
        }

    return cached(f"meta:countries:{include_groups}:{state.dataset_versions_for([('refs', 'all')])}"
                  f":{len(store.cached_reporters('A'))}", build)


@router.get("/products")
def products(request: Request, response: Response, level: int = Query(2, ge=2, le=6)) -> Any:
    """HS categories at the requested level, with names and parents."""
    if level not in (2, 4, 6):
        raise HTTPException(400, "level must be 2, 4 or 6")
    if apply_http_cache(request, response, version_scopes=[("refs", "all")],
                        params=f"products:{level}", max_age=86400):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        frame = refs.load_hs().filter(pl.col("level") == level)
        rows = [
            {"code": r["hs_code"], "name": r["name"], "parent": r["parent"],
             "level": int(r["level"])}
            for r in frame.sort("hs_code").to_dicts()
        ]
        return {"data": rows, "meta": {"source": "UN Comtrade", "classification": "HS",
                                       "level": level, "count": len(rows)}}

    return cached(f"meta:products:{level}:{state.dataset_versions_for([('refs', 'all')])}", build)


@router.get("/partners")
def partners(request: Request, response: Response) -> Any:
    if apply_http_cache(request, response, version_scopes=[("refs", "all")],
                        params="partners", max_age=86400):
        return Response(status_code=304)

    def build() -> dict[str, Any]:
        frame = refs.load_partners().filter(
            (pl.col("partner_code") != 0) & ~pl.col("expired").fill_null(False)
        )
        rows = [
            {"code": int(r["partner_code"]), "name": r["name"], "iso3": r["iso3"],
             "iso2": r["iso2"], "is_group": bool(r["is_group"])}
            for r in frame.sort("name").to_dicts()
        ]
        return {"data": rows, "meta": {"source": "UN Comtrade", "count": len(rows)}}

    return cached(f"meta:partners:{state.dataset_versions_for([('refs', 'all')])}", build)
