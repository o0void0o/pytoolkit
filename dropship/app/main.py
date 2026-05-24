"""Flask application factory.

Pure-Python stack: Flask + Werkzeug (handles multipart parsing natively, no
python-multipart needed). CSRF is enforced by a before_request hook, body
size by Flask's MAX_CONTENT_LENGTH, and a per-request access log line is
emitted by a tiny after_request hook.
"""

from __future__ import annotations

import secrets
import time
from pathlib import Path

from flask import Flask, current_app, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from app import __version__
from app.config import Config
from app.logging_config import get_logger
from app.routes import api as api_routes
from app.routes import views as view_routes
from app.services.stats_service import StatsService

log = get_logger("dropship.app")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(config: Config) -> Flask:
    """Build a Flask app bound to the given Config."""
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
        template_folder=str(TEMPLATES_DIR),
    )

    # Werkzeug enforces this for us — any request larger than the cap is
    # rejected with 413 before bodies start being read.
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_bytes

    app.extensions["dropship_config"] = config
    app.extensions["dropship_stats"] = StatsService(config.upload_dir)
    app.extensions["dropship_started_at"] = time.time()

    # ---- access log + timing ------------------------------------------------
    @app.before_request
    def _start_timer():
        g._started = time.perf_counter()

    @app.after_request
    def _access_log(response):
        elapsed = (time.perf_counter() - getattr(g, "_started", time.perf_counter())) * 1000
        client = request.remote_addr or "-"
        log.info("%s %s %s -> %d in %.1fms", client, request.method, request.path, response.status_code, elapsed)
        # Make sure a CSRF cookie exists for the client to echo on writes.
        if config.csrf_cookie_name not in request.cookies:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                config.csrf_cookie_name,
                token,
                httponly=False,
                samesite="Strict",
                secure=(request.scheme == "https"),
                max_age=60 * 60 * 24 * 7,
                path="/",
            )
        return response

    # ---- error handlers -----------------------------------------------------
    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # If a downstream view already returned a JSON body, preserve it.
        if isinstance(exc.response, app.response_class) and exc.response.is_json:
            return exc.response
        return jsonify({"error": exc.description or exc.name}), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        log.exception("unhandled error: %s", exc)
        return jsonify({"error": "internal_server_error"}), 500

    # ---- routes -------------------------------------------------------------
    app.register_blueprint(api_routes.bp, url_prefix="/api")

    # Two serving modes auto-detected from --serve-dir:
    #   has index.html  -> serve the folder as a static site at /
    #   no index.html   -> dashboard at /, browsing that folder
    serve_dir = config.serve_dir
    has_index = serve_dir is not None and (serve_dir / "index.html").exists()

    if has_index:
        @app.get("/")
        def _site_root():
            return send_from_directory(str(serve_dir), "index.html")

        @app.get("/<path:filename>")
        def _site_file(filename: str):
            # Werkzeug's safe_join inside send_from_directory blocks traversal.
            return send_from_directory(str(serve_dir), filename)
    else:
        app.register_blueprint(view_routes.bp)

    return app


def get_config() -> Config:
    return current_app.extensions["dropship_config"]


def get_stats() -> StatsService:
    return current_app.extensions["dropship_stats"]
