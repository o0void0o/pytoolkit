"""Lightweight in-memory stats counter."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.services.file_service import directory_size, disk_usage_for, list_files


@dataclass(slots=True)
class StatsSnapshot:
    uptime_seconds: float
    total_uploads_session: int
    stored_files: int
    stored_bytes: int
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int

    def to_dict(self) -> dict:
        return asdict(self)


class StatsService:
    def __init__(self, upload_dir: Path) -> None:
        self._upload_dir = upload_dir
        self._started_at = time.monotonic()
        self._uploads = 0
        self._lock = threading.Lock()

    def record_upload(self, count: int = 1) -> None:
        with self._lock:
            self._uploads += count

    def snapshot(self, *, files: list | None = None) -> StatsSnapshot:
        if files is None:
            from app.config import Config
            tmp = Config(
                host="",
                port=0,
                upload_dir=self._upload_dir,
                max_upload_bytes=0,
                secret_key="x",
            )
            files = list_files(tmp)
        total_total, total_used, total_free = disk_usage_for(self._upload_dir)
        stored_bytes = sum(f.size for f in files) if files else directory_size(self._upload_dir)
        return StatsSnapshot(
            uptime_seconds=time.monotonic() - self._started_at,
            total_uploads_session=self._uploads,
            stored_files=len(files) if files is not None else 0,
            stored_bytes=stored_bytes,
            disk_total_bytes=total_total,
            disk_used_bytes=total_used,
            disk_free_bytes=total_free,
        )
