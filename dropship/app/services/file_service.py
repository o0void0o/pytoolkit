"""File storage operations.

Sync version for Flask + Werkzeug — no asyncio, no aiofiles. Werkzeug already
spools large uploads to a temp file, so reading the FileStorage in chunks
gives us streaming-to-disk behaviour with bounded memory.
"""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException, abort

from app.config import Config
from app.logging_config import get_logger

log = get_logger("dropship.files")

CHUNK_SIZE: Final = 1024 * 1024

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._\- ]+")
_COLLAPSE_DOTS = re.compile(r"\.{2,}")
_COLLAPSE_SPACES = re.compile(r"\s+")


def _http(code: int, detail: str):
    """Raise a Flask/Werkzeug HTTPException with a JSON-safe description."""
    abort(code, description=detail)


def _to_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass(frozen=True, slots=True)
class StoredEntry:
    """A directory entry (file or folder)."""

    name: str
    kind: str  # "file" | "dir"
    size: int
    uploaded_at: float
    content_type: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "uploaded_at": self.uploaded_at,
            "uploaded_at_iso": _to_iso(self.uploaded_at),
            "content_type": self.content_type,
        }


StoredFile = StoredEntry


def secure_filename(raw: str | None) -> str:
    """Return a filename safe to write inside the upload dir.

    Local impl instead of werkzeug.secure_filename because that one strips
    non-ASCII entirely; ours transliterates via NFKD and only swaps the truly
    unsafe characters.
    """
    if raw is None:
        return "unnamed"

    raw = raw.replace("\\", "/").split("/")[-1]
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(c for c in raw if not unicodedata.category(c).startswith("C"))
    raw = _SAFE_CHARS.sub("_", raw)
    raw = _COLLAPSE_DOTS.sub(".", raw)
    raw = _COLLAPSE_SPACES.sub(" ", raw).strip(" .")
    raw = raw[:200]

    if not raw:
        return "unnamed"

    stem = raw.split(".")[0].upper()
    if stem in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raw = f"_{raw}"

    return raw


def resolve_safe_path(upload_dir: Path, name: str) -> Path:
    """Resolve a single filename inside `upload_dir`. No slashes allowed."""
    safe_name = secure_filename(name)
    upload_root = upload_dir.resolve()
    candidate = (upload_root / safe_name).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError:
        log.warning("traversal attempt blocked: %r", name)
        _http(400, "invalid_path")
    return candidate


def resolve_safe_subpath(root: Path, relpath: str | None) -> Path:
    """Resolve a multi-segment relative path inside `root`."""
    root_real = root.resolve()
    if not relpath or relpath in {"/", "."}:
        return root_real
    raw_segments = relpath.replace("\\", "/").strip("/").split("/")
    safe_segments = [secure_filename(s) for s in raw_segments if s not in {"", ".", ".."}]
    if not safe_segments:
        return root_real
    candidate = root_real.joinpath(*safe_segments).resolve()
    try:
        candidate.relative_to(root_real)
    except ValueError:
        log.warning("traversal attempt blocked: %r", relpath)
        _http(400, "invalid_path")
    return candidate


def _unique_destination(target_dir: Path, desired: str, *, attempts: int) -> Path:
    safe = secure_filename(desired)
    base = (target_dir / safe).resolve()
    if not base.exists():
        return base
    stem, dot, ext = safe.rpartition(".")
    if not dot:
        stem, ext = safe, ""
    for i in range(2, attempts + 2):
        candidate = (target_dir / f"{stem}-{i}{('.' + ext) if ext else ''}").resolve()
        if not candidate.exists():
            return candidate
    _http(409, "too_many_collisions")
    return base  # unreachable; satisfies type checkers


def validate_extension(config: Config, filename: str) -> None:
    ext = Path(filename).suffix.lower()
    if ext in config.denylist_extensions:
        _http(415, f"extension_blocked:{ext}")


def _detect_mime(name: str, declared: str | None) -> str:
    guessed, _ = mimetypes.guess_type(name)
    if guessed:
        return guessed
    if declared and "/" in declared:
        return declared
    return "application/octet-stream"


def save_upload(config: Config, upload: FileStorage, *, subpath: str | None = None) -> StoredEntry:
    """Save a single Werkzeug FileStorage to disk inside upload_dir / subpath.

    Werkzeug already buffers the request body to a SpooledTemporaryFile, so
    `upload.stream` is a real file-like object we can copy in chunks without
    pulling everything into memory.
    """
    raw_name = upload.filename or "unnamed"
    safe = secure_filename(raw_name)
    validate_extension(config, safe)

    target_dir = resolve_safe_subpath(config.upload_dir, subpath)
    if not target_dir.exists() or not target_dir.is_dir():
        _http(404, "target_dir_not_found")

    dest = _unique_destination(target_dir, safe, attempts=config.rename_attempts)
    log.debug("saving upload %r -> %s", raw_name, dest)

    written = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with open(tmp, "wb") as fh:
            stream = upload.stream
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > config.max_upload_bytes:
                    _http(413, "file_too_large")
                fh.write(chunk)
        os.replace(tmp, dest)
    except HTTPException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        log.exception("write failed: %s", exc)
        _http(500, "write_failed")

    stat = dest.stat()
    return StoredEntry(
        name=dest.name,
        kind="file",
        size=stat.st_size,
        uploaded_at=stat.st_mtime,
        content_type=_detect_mime(dest.name, upload.mimetype),
    )


def _browse_root(config: Config) -> Path:
    if config.serve_dir is not None:
        return config.serve_dir
    return config.upload_dir


def list_entries(config: Config, *, subpath: str | None = None) -> tuple[str, list[StoredEntry]]:
    """List entries inside the browse root + (optional) subpath.

    Directories first (alphabetical), then files (newest first). Hidden files
    and `.part` uploads are skipped.
    """
    root = _browse_root(config).resolve()
    target = resolve_safe_subpath(root, subpath)
    if not target.exists() or not target.is_dir():
        _http(404, "not_found")

    dirs: list[StoredEntry] = []
    files: list[StoredEntry] = []
    for entry in target.iterdir():
        if entry.name.startswith(".") or entry.name.endswith(".part"):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        record = StoredEntry(
            name=entry.name,
            kind="dir" if entry.is_dir() else "file",
            size=0 if entry.is_dir() else stat.st_size,
            uploaded_at=stat.st_mtime,
            content_type="inode/directory" if entry.is_dir() else _detect_mime(entry.name, None),
        )
        (dirs if entry.is_dir() else files).append(record)

    dirs.sort(key=lambda e: e.name.lower())
    files.sort(key=lambda e: e.uploaded_at, reverse=True)
    normalized = "" if target == root else str(target.relative_to(root)).replace("\\", "/")
    return normalized, dirs + files


def list_files(config: Config) -> list[StoredEntry]:
    """All files recursively under the browse root. Used by stats."""
    root = _browse_root(config).resolve()
    results: list[StoredEntry] = []
    for entry in root.rglob("*"):
        if entry.name.startswith(".") or entry.name.endswith(".part"):
            continue
        if entry.is_file():
            try:
                stat = entry.stat()
            except OSError:
                continue
            results.append(StoredEntry(
                name=entry.name,
                kind="file",
                size=stat.st_size,
                uploaded_at=stat.st_mtime,
                content_type=_detect_mime(entry.name, None),
            ))
    return results


def delete_entry(config: Config, subpath: str) -> None:
    root = _browse_root(config).resolve()
    target = resolve_safe_subpath(root, subpath)
    if target == root:
        _http(400, "cannot_delete_root")
    if not target.exists():
        _http(404, "not_found")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        log.exception("delete failed: %s", exc)
        _http(500, "delete_failed")


delete_file = delete_entry


def get_file_for_download(config: Config, subpath: str) -> tuple[Path, str]:
    root = _browse_root(config).resolve()
    target = resolve_safe_subpath(root, subpath)
    if not target.exists() or not target.is_file():
        _http(404, "not_found")
    return target, _detect_mime(target.name, None)


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


def disk_usage_for(path: Path) -> tuple[int, int, int]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return 0, 0, 0
    return usage.total, usage.used, usage.free
