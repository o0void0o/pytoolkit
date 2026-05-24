"""Optional HTTP Basic auth + CSRF validation helpers."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import Config

basic_scheme = HTTPBasic(auto_error=False)


def get_config(request: Request) -> Config:
    return request.app.state.config


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
) -> None:
    config: Config = request.app.state.config
    if not config.auth_enabled:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
            headers={"WWW-Authenticate": 'Basic realm="Dropship"'},
        )
    user_ok = secrets.compare_digest(credentials.username.encode(), config.username.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), (config.password or "").encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
            headers={"WWW-Authenticate": 'Basic realm="Dropship"'},
        )


def require_csrf(request: Request) -> None:
    config: Config = request.app.state.config
    cookie = request.cookies.get(config.csrf_cookie_name)
    header = request.headers.get(config.csrf_header_name)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf_failed")
