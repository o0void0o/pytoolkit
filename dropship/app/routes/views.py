"""HTML page routes — just the SPA shell."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Config
from app.security.auth import require_auth

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def index(request: Request) -> HTMLResponse:
    config: Config = request.app.state.config
    browse_root = config.serve_dir if config.serve_dir is not None else config.upload_dir
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "csrf_cookie_name": config.csrf_cookie_name,
            "csrf_header_name": config.csrf_header_name,
            "max_upload_bytes": config.max_upload_bytes,
            "auth_enabled": config.auth_enabled,
            "browse_root": str(browse_root),
        },
    )
