"""Optional HTTP Basic auth + CSRF validation, as Flask decorators."""

from __future__ import annotations

import secrets
from functools import wraps

from flask import Response, abort, request


def _cfg():
    from app.main import get_config
    return get_config()


def require_auth(view):
    """Demand HTTP Basic credentials if a password is configured."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        config = _cfg()
        if not config.auth_enabled:
            return view(*args, **kwargs)
        auth = request.authorization
        if auth is None or auth.type.lower() != "basic":
            return Response(
                response='{"error":"authentication_required"}',
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Dropship"', "Content-Type": "application/json"},
            )
        user_ok = secrets.compare_digest((auth.username or "").encode(), config.username.encode())
        pass_ok = secrets.compare_digest((auth.password or "").encode(), (config.password or "").encode())
        if not (user_ok and pass_ok):
            return Response(
                response='{"error":"invalid_credentials"}',
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Dropship"', "Content-Type": "application/json"},
            )
        return view(*args, **kwargs)
    return wrapper


def require_csrf(view):
    """Block state-changing requests unless the CSRF cookie matches the header."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        config = _cfg()
        cookie = request.cookies.get(config.csrf_cookie_name)
        header = request.headers.get(config.csrf_header_name)
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            abort(403, description="csrf_failed")
        return view(*args, **kwargs)
    return wrapper
