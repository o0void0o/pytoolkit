# Dropship

A single-page, terminal-aesthetic file-drop server. FastAPI on the backend,
vanilla JS on the frontend — no build step, no node_modules.

```
  ____                       _     _
 |  _ \ _ __ ___  _ __  ___| |__ (_)_ __
 | | | | '__/ _ \| '_ \/ __| '_ \| | '_ \
 | |_| | | | (_) | |_) \__ \ | | | | |_) |
 |____/|_|  \___/| .__/|___/_| |_|_| .__/
                 |_|               |_|
```

## Features

- **Drag-and-drop multi-file uploads** with real per-file progress bars
  (XHR-backed, since `fetch()` still can't report upload progress).
- **File browser with full folder navigation** — breadcrumbs, click-to-descend,
  `..` row, URL-synced (`?path=…`) so back/forward and reloads work.
- **Live stats**: uptime, stored file count, total bytes, session uploads, disk free.
- **Two serving modes** auto-detected from `--serve-dir`:
  - has `index.html` → plain static site at `/`
  - no `index.html`  → dashboard browses the folder + accepts uploads
- **Security**:
  - Path-traversal-proof filename handling (`resolve_safe_subpath`).
  - Per-request body cap enforced by middleware AND mid-stream during writes.
  - Extension denylist (`.exe`, `.bat`, `.js`, …).
  - Sanitized stored filenames with Windows reserved-name handling.
  - CSRF token (cookie + `X-CSRF-Token` header) required for all writes.
  - Optional HTTP Basic auth (`--password`).
  - No eval, no shelling out, no client filename trust.

## Requirements

- Python **3.12+**
- pip

## Install

```bash
cd dropship
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## Run

The default bind is `0.0.0.0:80`. **Port 80 needs admin/root on most systems** —
use something higher for dev.

```bash
# defaults (host 0.0.0.0, port 80, ./uploads)
python run.py

# dev: high port, debug logs
python run.py --host 127.0.0.1 --port 8080 --debug

# custom upload directory
python run.py --port 8080 --upload-dir /var/uploads
python run.py --port 8080 --upload-dir C:\Users\Public\Drops
python run.py --port 8080 --upload-dir ~/Downloads/drops

# with auth
python run.py --port 8080 --username operator --password 'changeme'

# raise the upload cap to 20 GB
python run.py --port 8080 --max-upload-mb 20480

# serve a folder — auto-detects what to do
python run.py --port 8080 --serve-dir ./my-folder
#   - if ./my-folder/index.html exists -> served as a static site at /
#   - otherwise                        -> dashboard opens the folder tree
#                                         with folder navigation + uploads
```

## CLI flags

| Flag              | Env var                  | Default     | Notes |
|-------------------|--------------------------|-------------|-------|
| `--host`          | `DROPSHIP_HOST`          | `0.0.0.0`   | bind interface |
| `--port`          | `DROPSHIP_PORT`          | `80`        | TCP port |
| `--upload-dir`    | `DROPSHIP_UPLOAD_DIR`    | `./uploads` | auto-created if missing |
| `--serve-dir`     | `DROPSHIP_SERVE_DIR`     | *(unset)*   | folder to serve at `/` — auto-detects index.html |
| `--max-upload-mb` | `DROPSHIP_MAX_UPLOAD_MB` | `5120`      | per-request cap |
| `--username`      | `DROPSHIP_USERNAME`      | `operator`  | basic-auth user |
| `--password`      | `DROPSHIP_PASSWORD`      | *(unset)*   | enables basic auth when set |
| `--secret-key`    | `DROPSHIP_SECRET_KEY`    | random      | cookie signing key |
| `--debug`         | `DROPSHIP_DEBUG`         | off         | verbose logs + `/docs` route |

## API

| Method  | Path                          | Description                          |
|--------:|-------------------------------|--------------------------------------|
| `GET`   | `/`                           | SPA shell (or static site)           |
| `GET`   | `/api/health`                 | liveness probe, unauthenticated      |
| `GET`   | `/api/stats`                  | server stats                         |
| `GET`   | `/api/files?path=…`           | list entries (files + folders)       |
| `POST`  | `/api/upload` (form `path=`)  | multipart upload, field name `files` |
| `GET`   | `/api/download?path=…`        | stream a file as attachment          |
| `DELETE`| `/api/files?path=…`           | delete a file or folder (recursive)  |

## Project layout

```
dropship/
├── run.py
├── requirements.txt
├── README.md
└── app/
    ├── __init__.py
    ├── config.py
    ├── logging_config.py
    ├── main.py
    ├── routes/
    │   ├── api.py
    │   └── views.py
    ├── services/
    │   ├── file_service.py
    │   └── stats_service.py
    ├── security/
    │   └── auth.py
    ├── templates/
    │   └── index.html
    └── static/
        ├── css/styles.css
        └── js/app.js
```

## Keyboard shortcuts

| Key         | Action               |
|-------------|----------------------|
| `U`         | open file picker     |
| `R`         | refresh file list    |
| `/`         | focus filter         |
| `Esc`       | clear filter / blur  |
| `Backspace` | navigate up a folder |

## Security notes

- The denylist in `app/config.py` blocks common executable extensions.
- Downloads are served with `Content-Disposition: attachment` so browsers save
  rather than render — no XSS via uploaded HTML.
- Path safety is enforced by `resolve_safe_subpath`: each segment passes
  through `secure_filename`, then the full resolved path is re-validated to
  stay inside the served root. Symlink escapes are blocked.
- If exposed publicly: **always** set `--password`, put TLS in front, and
  tighten `--max-upload-mb`.
