# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Authentication helpers for the web runtime."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from modules import config
from web.auth_store import WebAccountStore

SESSION_COOKIE = "conniesuploader_session"
SESSION_SECONDS = 12 * 60 * 60
PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/setup",
    "/login",
    "/setup",
    "/favicon.ico",
}
PUBLIC_STATIC_PATHS = {"/static/app.css", "/static/auth.js"}
_PROCESS_SESSION_SECRET = secrets.token_bytes(32)


def auth_configured() -> bool:
    return bool(config.WEB_PASSWORD or config.WEB_TOKEN or account_configured())


def security_status() -> dict[str, bool]:
    return {
        "auth_required": bool(config.WEB_AUTH_REQUIRED),
        "auth_configured": auth_configured(),
        "env_auth_configured": bool(config.WEB_PASSWORD or config.WEB_TOKEN),
        "account_configured": account_configured(),
        "setup_required": setup_required(),
        "docs_enabled": bool(config.WEB_DOCS_ENABLED),
    }


def account_configured() -> bool:
    return WebAccountStore().exists()


def setup_required() -> bool:
    return bool(config.WEB_AUTH_REQUIRED) and not auth_configured()


def request_authorized(request: Request) -> bool:
    return _authorized_session(request.cookies.get(SESSION_COOKIE, "")) or _authorized_header(
        request.headers.get("authorization", ""),
    )


def request_username(request: Request) -> str:
    session_username = _session_username(request.cookies.get(SESSION_COOKIE, ""))
    if session_username:
        return session_username
    return _header_username(request.headers.get("authorization", ""))


def authenticate_credentials(username: str, password: str) -> bool:
    if config.WEB_PASSWORD and hmac.compare_digest(username, config.WEB_USERNAME):
        return hmac.compare_digest(password, config.WEB_PASSWORD)
    return WebAccountStore().verify_password(username, password)


def issue_session(response: Response, username: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        _make_session_token(username),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_auth(request: Request, call_next: Callable):
        if not _should_protect(request.url.path):
            return await call_next(request)

        if setup_required():
            return _setup_required_response(request)

        if request_authorized(request):
            return await call_next(request)

        return _unauthorized_response(request)


def _should_protect(path: str) -> bool:
    if not config.WEB_AUTH_REQUIRED:
        return False
    return path not in PUBLIC_PATHS and path not in PUBLIC_STATIC_PATHS


def _setup_required_response(request: Request) -> Response:
    if _wants_html(request):
        return RedirectResponse("/setup", status_code=303)
    return JSONResponse(
        status_code=428,
        content={"detail": "Create the first web account before using Connie's Uploader."},
    )


def _unauthorized_response(request: Request) -> Response:
    if _wants_html(request):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required."},
        headers={"WWW-Authenticate": 'Basic realm="ConniesUploader"'},
    )


def _wants_html(request: Request) -> bool:
    path = request.url.path
    if path == "/":
        return True
    if path.startswith("/api/") or path.startswith("/static/"):
        return False
    return "text/html" in request.headers.get("accept", "").lower()


def _authorized_header(header: str) -> bool:
    scheme, _, value = str(header or "").partition(" ")
    if not scheme or not value:
        return False

    if scheme.lower() == "bearer" and config.WEB_TOKEN:
        return hmac.compare_digest(value.strip(), config.WEB_TOKEN)

    if scheme.lower() != "basic":
        return False

    credentials = _decode_basic(value)
    if credentials is None:
        return False
    username, password = credentials
    return authenticate_credentials(username, password)


def _header_username(header: str) -> str:
    scheme, _, value = str(header or "").partition(" ")
    if scheme.lower() != "basic" or not value:
        return ""
    credentials = _decode_basic(value)
    if credentials is None:
        return ""
    username, password = credentials
    return username if authenticate_credentials(username, password) else ""


def _decode_basic(value: str) -> tuple[str, str] | None:
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def _make_session_token(username: str) -> str:
    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + SESSION_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(
        hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def _authorized_session(token: str) -> bool:
    return bool(_session_username(token))


def _session_username(token: str) -> str:
    encoded, separator, signature = str(token or "").partition(".")
    if not separator or not encoded or not signature:
        return ""
    expected = _b64(
        hmac.new(_session_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected):
        return ""
    try:
        payload = json.loads(_unb64(encoded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if int(payload.get("exp") or 0) < int(time.time()):
        return ""
    return str(payload.get("sub") or "")


def _session_secret() -> bytes:
    return WebAccountStore().session_secret() or _PROCESS_SESSION_SECRET


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
