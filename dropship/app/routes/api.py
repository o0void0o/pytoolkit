"""JSON API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import Config
from app.security.auth import require_auth, require_csrf
from app.services import file_service
from app.services.stats_service import StatsService

router = APIRouter(tags=["api"])


def _config(request: Request) -> Config:
    return request.app.state.config


def _stats(request: Request) -> StatsService:
    return request.app.state.stats


@router.get("/files", dependencies=[Depends(require_auth)])
async def list_files_endpoint(request: Request, path: str = "") -> JSONResponse:
    normalized, entries = file_service.list_entries(_config(request), subpath=path)
    return JSONResponse({"path": normalized, "entries": [e.to_dict() for e in entries]})


@router.post(
    "/upload",
    dependencies=[Depends(require_auth), Depends(require_csrf)],
    status_code=201,
)
async def upload_endpoint(
    request: Request,
    files: Annotated[list[UploadFile], File(description="One or more files to upload")],
    path: Annotated[str, Form()] = "",
) -> JSONResponse:
    config = _config(request)
    saved = []
    errors = []
    for upload in files:
        try:
            stored = await file_service.save_upload(config, upload, subpath=path)
            saved.append(stored.to_dict())
        except Exception as exc:
            errors.append({"name": upload.filename, "error": str(exc)})
        finally:
            await upload.close()
    _stats(request).record_upload(len(saved))
    status_code = 201 if saved and not errors else (207 if saved and errors else 400)
    return JSONResponse({"saved": saved, "errors": errors}, status_code=status_code)


@router.get(
    "/download",
    dependencies=[Depends(require_auth)],
)
async def download_endpoint(request: Request, path: str) -> FileResponse:
    target, content_type = file_service.get_file_for_download(_config(request), path)
    return FileResponse(path=target, media_type=content_type, filename=target.name)


@router.delete(
    "/files",
    dependencies=[Depends(require_auth), Depends(require_csrf)],
)
async def delete_endpoint(request: Request, path: str) -> JSONResponse:
    file_service.delete_entry(_config(request), path)
    return JSONResponse({"deleted": path})


@router.get("/stats", dependencies=[Depends(require_auth)])
async def stats_endpoint(request: Request) -> JSONResponse:
    files = file_service.list_files(_config(request))
    snap = _stats(request).snapshot(files=files)
    return JSONResponse(snap.to_dict())


@router.get("/health")
async def health_endpoint() -> JSONResponse:
    return JSONResponse({"status": "ok"})
