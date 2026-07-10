# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Authentication helpers for the web runtime."""

from __future__ import annotations

import base64
import binascii
import hmac
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from modules import config

PUBLIC_PATHS = {"/api/health"}


def auth_configured() -> bool:
    return bool(config.WEB_PASSWORD or config.WEB_TOKEN)


def security_status() -> dict[str, bool]:
    return {
        "auth_required": bool(config.WEB_AUTH_REQUIRED),
        "auth_configured": auth_configured(),
        "docs_enabled": bool(config.WEB_DOCS_ENABLED),
    }


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_auth(request: Request, call_next: Callable):
        if not _should_protect(request.url.path):
            return await call_next(request)

        if not auth_configured():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "Web authentication is required but no password or token is "
                        "configured. Set CONNIESUPLOADER_WEB_PASSWORD, "
                        "CONNIESUPLOADER_WEB_PASSWORD_FILE, CONNIESUPLOADER_WEB_TOKEN, "
                        "or CONNIESUPLOADER_WEB_TOKEN_FILE."
                    )
                },
            )

        if _authorized(request.headers.get("authorization", "")):
            return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="ConniesUploader"'},
        )


def _should_protect(path: str) -> bool:
    if not config.WEB_AUTH_REQUIRED:
        return False
    return path not in PUBLIC_PATHS


def _authorized(header: str) -> bool:
    scheme, _, value = str(header or "").partition(" ")
    if not scheme or not value:
        return False

    if scheme.lower() == "bearer" and config.WEB_TOKEN:
        return hmac.compare_digest(value.strip(), config.WEB_TOKEN)

    if scheme.lower() != "basic" or not config.WEB_PASSWORD:
        return False

    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return hmac.compare_digest(username, config.WEB_USERNAME) and hmac.compare_digest(
        password,
        config.WEB_PASSWORD,
    )
