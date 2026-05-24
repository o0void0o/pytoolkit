"""HTML page routes — just the SPA shell."""

from __future__ import annotations

from flask import Blueprint, render_template

from app.security.auth import require_auth

bp = Blueprint("views", __name__)


@bp.get("/")
@require_auth
def index():
    from app.main import get_config
    config = get_config()
    browse_root = config.serve_dir if config.serve_dir is not None else config.upload_dir
    return render_template(
        "index.html",
        csrf_cookie_name=config.csrf_cookie_name,
        csrf_header_name=config.csrf_header_name,
        max_upload_bytes=config.max_upload_bytes,
        auth_enabled=config.auth_enabled,
        browse_root=str(browse_root),
    )
