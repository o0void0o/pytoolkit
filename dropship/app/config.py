"""Runtime configuration for Dropship.

A single immutable dataclass carries every knob the rest of the app reads.
The launcher (`run.py`) builds it from CLI args / env vars and hands it to
`create_app`, which stuffs it into `app.state.config`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DENYLIST_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".msi", ".ps1",
        ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".jar", ".sh",
        ".app", ".dmg", ".pkg",
    }
)


@dataclass(frozen=True, slots=True)
class Config:
    """Server configuration. Immutable after construction."""

    host: str
    port: int
    upload_dir: Path
    max_upload_bytes: int
    secret_key: str
    username: str = "operator"
    password: str | None = None
    debug: bool = False

    csrf_cookie_name: str = "dropship_csrf"
    csrf_header_name: str = "X-CSRF-Token"

    rename_attempts: int = 1000

    # Optional folder served at "/". If it contains index.html, it's served
    # as a static site. Otherwise the dashboard browser opens on it directly.
    serve_dir: Path | None = None

    denylist_extensions: frozenset[str] = field(default_factory=lambda: DENYLIST_EXTENSIONS)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.password)
