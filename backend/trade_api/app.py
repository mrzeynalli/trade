"""FastAPI application.

Serves the API and the built single-page frontend under a configurable base
path (``/trade`` in production), so Nginx needs exactly one extra location
block and the existing site is untouched.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import orjson
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, ORJSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from . import __version__, state
from .config import get_settings, redact
from .logging_setup import configure_logging, get_logger
from .routers import advanced, country, drilldown, meta, system, world

log = get_logger("trade.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    configure_logging()
    log.info("api starting", extra={"version": __version__, "base_path": settings.base_path,
                                    "data_dir": str(settings.data_dir)})
    yield
    state.reset_thread_conn()


def create_app() -> FastAPI:
    settings = get_settings()
    base = settings.base_path

    app = FastAPI(
        title="Global Trade Intelligence",
        version=__version__,
        default_response_class=ORJSONResponse,
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable) -> Response:
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            duration = (time.perf_counter() - started) * 1000
            log.error("request failed", extra={
                "request_id": request_id, "route": request.url.path,
                "duration_ms": round(duration, 1), "error": redact(str(exc))[:400],
            })
            return ORJSONResponse({"error": "Internal error", "request_id": request_id},
                                  status_code=500)
        duration = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(f"{base}/api"):
            log.info("request", extra={
                "request_id": request_id, "route": request.url.path,
                "status": response.status_code, "duration_ms": round(duration, 1),
                "cache": response.headers.get("ETag", "")[:12],
            })
        return response

    api = APIRouter()
    api.include_router(meta.router)
    api.include_router(world.router)
    api.include_router(country.router)
    api.include_router(drilldown.router)
    api.include_router(advanced.router)
    api.include_router(system.router)
    app.include_router(api, prefix=f"{base}/api")

    _mount_frontend(app, base, settings.static_dir)
    return app


class ImmutableStatic(StaticFiles):
    """Vite emits content-hashed filenames, so those files never change under a
    given URL and can be cached for a year."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _mount_frontend(app: FastAPI, base: str, static_dir: Path | None) -> None:
    """Serve the built SPA. Hashed assets are immutable; the shell is not."""
    root = Path(static_dir) if static_dir else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    assets = root / "assets"

    if assets.is_dir():
        app.mount(f"{base}/assets", ImmutableStatic(directory=assets), name="assets")

    index_file = root / "index.html"

    @app.get(f"{base}/healthz", include_in_schema=False)
    def healthz() -> Any:
        return {"status": "ok", "service": "analytics-trade", "version": __version__}

    @app.get(base, include_in_schema=False)
    @app.get(f"{base}/{{full_path:path}}", include_in_schema=False)
    def spa(full_path: str = "") -> Response:
        if full_path.startswith("api/"):
            return ORJSONResponse({"error": "Not found"}, status_code=404)
        if not index_file.exists():
            return PlainTextResponse(
                "Frontend build not found. Run 'npm run build' in frontend/.",
                status_code=503,
            )
        html = index_file.read_text(encoding="utf-8")
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; font-src 'self' data:; "
                    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
                ),
            },
        )


app = create_app()
