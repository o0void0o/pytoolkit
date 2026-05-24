"""Dropship launcher.

Pure-Python serving stack: Flask app, waitress WSGI server. Works on Termux
and any system without a C/Rust toolchain.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from waitress import serve

from app.config import Config
from app.logging_config import configure_logging, get_logger, print_banner
from app.main import create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dropship",
        description="Dropship — a terminal-styled file-drop server.",
    )
    parser.add_argument("--host", default=os.environ.get("DROPSHIP_HOST", "0.0.0.0"),
                        help="Bind address (default: 0.0.0.0).")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DROPSHIP_PORT", "80")),
                        help="Bind port (default: 80).")
    parser.add_argument("--upload-dir", default=os.environ.get("DROPSHIP_UPLOAD_DIR", "uploads"),
                        help="Directory used for stored uploads (default: ./uploads).")
    parser.add_argument("--serve-dir", default=os.environ.get("DROPSHIP_SERVE_DIR"),
                        help=("Folder to serve at /. If it contains index.html, that page is "
                              "served (static site). Otherwise the dashboard opens on this "
                              "folder with tree navigation. Defaults to --upload-dir."))
    parser.add_argument("--max-upload-mb", type=int,
                        default=int(os.environ.get("DROPSHIP_MAX_UPLOAD_MB", "5120")),
                        help="Maximum upload size per request in MB (default: 5120).")
    parser.add_argument("--password", default=os.environ.get("DROPSHIP_PASSWORD"),
                        help="If set, all routes require HTTP Basic auth.")
    parser.add_argument("--username", default=os.environ.get("DROPSHIP_USERNAME", "operator"),
                        help="Username used with --password (default: operator).")
    parser.add_argument("--secret-key", default=os.environ.get("DROPSHIP_SECRET_KEY"),
                        help="Secret used to sign the CSRF cookie. Auto-generated if absent.")
    parser.add_argument("--threads", type=int, default=int(os.environ.get("DROPSHIP_THREADS", "8")),
                        help="Waitress worker threads (default: 8).")
    parser.add_argument("--debug", action="store_true",
                        default=os.environ.get("DROPSHIP_DEBUG", "").lower() in {"1", "true", "yes"},
                        help="Enable Flask debug mode (verbose logs).")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config:
    serve_dir = Path(args.serve_dir).expanduser().resolve() if args.serve_dir else None
    upload_dir = (
        serve_dir
        if serve_dir is not None and args.upload_dir == "uploads"
        else Path(args.upload_dir).expanduser().resolve()
    )
    return Config(
        host=args.host,
        port=args.port,
        upload_dir=upload_dir,
        max_upload_bytes=args.max_upload_mb * 1024 * 1024,
        password=args.password,
        username=args.username,
        secret_key=args.secret_key or os.urandom(32).hex(),
        debug=args.debug,
        serve_dir=serve_dir,
    )


def install_signal_handlers(log) -> None:
    def _handler(signum, _frame):
        log.warning("received signal %s — shutting down", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (AttributeError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = build_config(args)

    configure_logging(debug=config.debug)
    log = get_logger("dropship")
    install_signal_handlers(log)

    config.upload_dir.mkdir(parents=True, exist_ok=True)
    if config.serve_dir is not None:
        config.serve_dir.mkdir(parents=True, exist_ok=True)

    print_banner(config)
    log.info("upload directory: %s", config.upload_dir)
    log.info("max upload size : %.1f MB", config.max_upload_bytes / (1024 * 1024))
    if config.serve_dir is not None:
        index = config.serve_dir / "index.html"
        if index.exists():
            log.info("serve mode      : static site (index.html detected)")
        else:
            log.info("serve mode      : tree browser (no index.html)")
        log.info("hosting folder  : %s", config.serve_dir)
    if config.password:
        log.info("auth            : enabled (user=%s)", config.username)
    else:
        log.warning("auth            : DISABLED — server is open to anyone who can reach it")

    app = create_app(config)

    try:
        serve(
            app,
            host=config.host,
            port=config.port,
            threads=args.threads,
            ident="dropship",
            _quiet=True,  # we own logging
        )
    except PermissionError:
        log.error(
            "permission denied binding %s:%d — ports <1024 typically need elevated "
            "privileges. Try --port 8080 instead.",
            config.host, config.port,
        )
        return 13
    except OSError as exc:
        log.error("failed to bind %s:%d — %s", config.host, config.port, exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
