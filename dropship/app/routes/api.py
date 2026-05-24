"""JSON API endpoints (Flask blueprint)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, send_file

from app.security.auth import require_auth, require_csrf
from app.services import file_service

bp = Blueprint("api", __name__)


def _cfg():
    from app.main import get_config
    return get_config()


def _stats():
    from app.main import get_stats
    return get_stats()


@bp.get("/files")
@require_auth
def list_files_endpoint():
    path = request.args.get("path", "")
    normalized, entries = file_service.list_entries(_cfg(), subpath=path)
    return jsonify({"path": normalized, "entries": [e.to_dict() for e in entries]})


@bp.post("/upload")
@require_auth
@require_csrf
def upload_endpoint():
    config = _cfg()
    subpath = request.form.get("path", "")
    uploads = request.files.getlist("files")
    saved = []
    errors = []
    for upload in uploads:
        try:
            stored = file_service.save_upload(config, upload, subpath=subpath)
            saved.append(stored.to_dict())
        except Exception as exc:
            errors.append({"name": getattr(upload, "filename", "?"), "error": str(exc)})
    _stats().record_upload(len(saved))
    status = 201 if saved and not errors else (207 if saved and errors else 400)
    return jsonify({"saved": saved, "errors": errors}), status


@bp.get("/download")
@require_auth
def download_endpoint():
    path = request.args.get("path", "")
    target, content_type = file_service.get_file_for_download(_cfg(), path)
    return send_file(
        str(target),
        mimetype=content_type,
        as_attachment=True,
        download_name=target.name,
    )


@bp.delete("/files")
@require_auth
@require_csrf
def delete_endpoint():
    path = request.args.get("path", "")
    file_service.delete_entry(_cfg(), path)
    return jsonify({"deleted": path})


@bp.get("/stats")
@require_auth
def stats_endpoint():
    files = file_service.list_files(_cfg())
    snap = _stats().snapshot(files=files)
    return jsonify(snap.to_dict())


@bp.get("/health")
def health_endpoint():
    return jsonify({"status": "ok"})
