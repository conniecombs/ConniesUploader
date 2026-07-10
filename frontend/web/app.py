# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Minimal FastAPI shell for the Docker web runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from modules import config
from web.api import register_api_routes
from web.security import install_auth_middleware, security_status

STATIC_DIR = Path(__file__).resolve().parent / "static"


def runtime_paths() -> Dict[str, str]:
    """Return web-visible runtime paths without exposing sensitive values."""
    return {
        "data": config.USER_DATA_DIR,
        "input": config.INPUT_DIR,
        "output": config.OUTPUT_DIR,
        "uploads": config.WEB_UPLOAD_DIR,
        "history": config.HISTORY_DIR,
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Connie's Uploader Web",
        version=config.APP_VERSION,
        docs_url="/api/docs" if config.WEB_DOCS_ENABLED else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.WEB_DOCS_ENABLED else None,
    )
    install_auth_middleware(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    register_api_routes(app)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "app": "ConniesUploader",
            "version": config.APP_VERSION,
            "mode": config.APP_MODE,
            "paths": runtime_paths(),
            "security": security_status(),
        }

    return app


app = create_app()
