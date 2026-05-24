"""FastAPI application factory and middleware wiring."""

from __future__ import annotations

import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.config import Config
from app.logging_config import get_logger
from app.routes import api as api_routes
from app.routes import views as view_routes
from app.services.stats_service import StatsService

log = get_logger("dropship.app")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            log.exception("%s %s -> 500 in %.1fms", request.method, request.url.path, elapsed)
            raise
        elapsed = (time.perf_counter() - started) * 1000
        client = request.client.host if request.client else "-"
        log.info(
            "%s %s %s -> %d in %.1fms",
            client,
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
        return response


class CSRFCookieMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, cookie_name: str) -> None:
        super().__init__(app)
        self.cookie_name = cookie_name

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if self.cookie_name not in request.cookies:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                self.cookie_name,
                token,
                httponly=False,
                samesite="strict",
                secure=request.url.scheme == "https",
                max_age=60 * 60 * 24 * 7,
                path="/",
            )
        return response


def create_app(config: Config) -> FastAPI:
    app = FastAPI(
        title="Dropship",
        version=__version__,
        docs_url="/docs" if config.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.debug else None,
    )

    app.state.config = config
    app.state.stats = StatsService(config.upload_dir)
    app.state.started_at = time.time()

    @app.middleware("http")
    async def enforce_max_body(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > config.max_upload_bytes:
            return JSONResponse(
                {"error": "request_too_large", "max_bytes": config.max_upload_bytes},
                status_code=413,
            )
        return await call_next(request)

    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CSRFCookieMiddleware, cookie_name=config.csrf_cookie_name)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(api_routes.router, prefix="/api")

    # Auto-detect serving mode based on what's in --serve-dir.
    serve_dir = config.serve_dir
    has_index = serve_dir is not None and (serve_dir / "index.html").exists()

    if has_index:
        app.mount(
            "/",
            StaticFiles(directory=str(serve_dir), html=True, check_dir=False),
            name="site",
        )
    else:
        app.include_router(view_routes.router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "invalid_request", "detail": exc.errors()}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception):
        log.exception("unhandled error: %s", exc)
        return JSONResponse({"error": "internal_server_error"}, status_code=500)

    return app
