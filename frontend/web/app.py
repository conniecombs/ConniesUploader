# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Minimal FastAPI shell for the Docker web runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from modules import config
from modules.credential_store import JsonCredentialStore
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


def _viper_credentials_provider(app: FastAPI):
    def load_credentials() -> Dict[str, str]:
        store = getattr(app.state, "credential_store", None) or JsonCredentialStore()
        credentials = store.load_all()
        return {
            "vg_user": str(credentials.get("vg_user") or "").strip(),
            "vg_pass": str(credentials.get("vg_pass") or "").strip(),
        }

    return load_credentials


def _viper_api_factory_provider(app: FastAPI):
    def create_api():
        from modules import viper_api

        factory = getattr(app.state, "viper_api_factory", None)
        return factory() if factory else viper_api.ViperGirlsAPI()

    return create_api


def _start_vipergirls_scheduler(app: FastAPI) -> Optional[Any]:
    if config.APP_MODE != "web":
        return None

    try:
        from modules import viper_api

        viper_api.configure_storage(config.USER_DATA_DIR)
        scheduler = viper_api.ViperGirlsPostScheduler(
            {},
            credentials_provider=_viper_credentials_provider(app),
            api_factory=_viper_api_factory_provider(app),
        )
        scheduler.start()
        app.state.viper_scheduler = scheduler
        return scheduler
    except Exception as exc:
        logger.warning(f"ViperGirls scheduled-post worker did not start: {exc}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = _start_vipergirls_scheduler(app)
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Connie's Uploader Web",
        version=config.APP_VERSION,
        docs_url="/api/docs" if config.WEB_DOCS_ENABLED else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.WEB_DOCS_ENABLED else None,
        lifespan=lifespan,
    )
    install_auth_middleware(app)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    register_api_routes(app)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/login", include_in_schema=False)
    def login() -> FileResponse:
        return FileResponse(STATIC_DIR / "auth.html")

    @app.get("/setup", include_in_schema=False)
    def setup() -> FileResponse:
        return FileResponse(STATIC_DIR / "auth.html")

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
