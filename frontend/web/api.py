# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""FastAPI routes for the Connie's Uploader web runtime."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from modules import config
from modules.credential_store import JsonCredentialStore
from modules.exceptions import InvalidConfigException, InvalidFileException
from modules.file_handler import sanitize_filename, validate_file_extension, validate_file_size
from modules.plugin_manager import PluginManager
from modules.settings_manager import SettingsManager
from modules.upload_models import UploadBatch
from modules.upload_session import UploadSessionRegistry

router = APIRouter(prefix="/api")


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any]


class CredentialUpdateRequest(BaseModel):
    credentials: Dict[str, Any]


class UploadGroupRequest(BaseModel):
    title: str
    files: List[str]
    source: str = "web"
    selected_template: str = "BBCode"
    selected_thread: str = "Do Not Post"
    batch_index: int = 0
    cover_files: List[str] = Field(default_factory=list)
    gallery: Optional[Dict[str, Any]] = None


class UploadStartRequest(BaseModel):
    groups: List[UploadGroupRequest]
    settings: Dict[str, Any] = Field(default_factory=dict)


def register_api_routes(app: FastAPI) -> None:
    app.state.registry = getattr(app.state, "registry", UploadSessionRegistry())
    app.state.settings_manager = getattr(app.state, "settings_manager", SettingsManager())
    app.state.credential_store = getattr(app.state, "credential_store", JsonCredentialStore())
    app.state.plugin_manager = getattr(app.state, "plugin_manager", PluginManager())
    app.include_router(router)


def _registry(request: Request) -> UploadSessionRegistry:
    return request.app.state.registry


def _settings_manager(request: Request) -> SettingsManager:
    return request.app.state.settings_manager


def _credential_store(request: Request) -> JsonCredentialStore:
    return request.app.state.credential_store


def _plugin_manager(request: Request) -> PluginManager:
    return request.app.state.plugin_manager


def _manager_factory(request: Request):
    return getattr(request.app.state, "manager_factory", None)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _snapshot_payload(snapshot: Any) -> Dict[str, Any]:
    return _jsonable(snapshot)


def _event_payload(event: Any) -> Dict[str, Any]:
    return _jsonable(event)


def _resolve_under(root: str, relative_path: str = "") -> Path:
    root_path = Path(root).expanduser().resolve()
    raw = (relative_path or "").strip()
    candidate = root_path / raw
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path is outside the allowed root") from exc
    return resolved


def _allowed_upload_roots() -> List[Path]:
    return [
        Path(config.INPUT_DIR).expanduser().resolve(),
        Path(config.WEB_UPLOAD_DIR).expanduser().resolve(),
    ]


def _resolve_allowed_upload_file(file_path: str) -> str:
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = Path(config.INPUT_DIR).expanduser() / path
    resolved = path.resolve()
    for root in _allowed_upload_roots():
        try:
            resolved.relative_to(root)
            validate_file_extension(str(resolved))
            validate_file_size(str(resolved))
            return str(resolved)
        except ValueError:
            continue
        except InvalidFileException as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="File is outside /input or staged uploads")


def _file_record(path: Path, root: Path) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "relative_path": str(path.relative_to(root)),
        "is_dir": path.is_dir(),
        "size": stat.st_size if path.is_file() else None,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "selectable": path.is_file() and path.name.lower().endswith(config.VALID_EXTENSIONS),
    }


@router.get("/services")
def services(request: Request) -> Dict[str, Any]:
    manager = _plugin_manager(request)
    service_payload = []
    for plugin in manager.get_all_plugins():
        metadata = plugin.metadata
        service_payload.append(
            {
                "id": plugin.id,
                "name": plugin.name,
                "metadata": metadata,
                "settings_schema": getattr(plugin, "settings_schema", []),
                "credentials": metadata.get("credentials", []),
            }
        )
    return {"services": service_payload, "load_errors": manager.get_load_errors()}


@router.get("/settings")
def get_settings(request: Request) -> Dict[str, Any]:
    manager = _settings_manager(request)
    return {"settings": manager.load()}


@router.put("/settings")
def put_settings(payload: SettingsUpdateRequest, request: Request) -> Dict[str, Any]:
    manager = _settings_manager(request)
    current = manager.load()
    updated = {**current, **payload.settings}
    try:
        manager.save(updated)
    except InvalidConfigException as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"settings": manager.load()}


@router.get("/credentials/status")
def credential_status(request: Request) -> Dict[str, Any]:
    return _credential_store(request).status()


@router.put("/credentials")
def put_credentials(payload: CredentialUpdateRequest, request: Request) -> Dict[str, Any]:
    return _credential_store(request).update(payload.credentials)


@router.get("/files/input")
def list_input_files(path: str = "") -> Dict[str, Any]:
    root = Path(config.INPUT_DIR).expanduser().resolve()
    target = _resolve_under(str(root), path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Input path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Input path is not a directory")
    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.is_dir() or child.name.lower().endswith(config.VALID_EXTENSIONS):
                entries.append(_file_record(child, root))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Could not list input path: {exc}") from exc
    return {"root": str(root), "path": str(target), "entries": entries}


@router.post("/files/upload")
async def upload_files(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    upload_dir = Path(config.WEB_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload in files:
        original_name = upload.filename or "upload"
        safe_name = sanitize_filename(original_name)
        extension = Path(original_name).suffix.lower()
        if extension and not safe_name.lower().endswith(extension):
            safe_name = f"{safe_name}{extension}"
        if not safe_name.lower().endswith(config.VALID_EXTENSIONS):
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {original_name}")

        target = upload_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
        bytes_written = 0
        with open(target, "wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > config.MAX_FILE_SIZE:
                    handle.close()
                    try:
                        target.unlink()
                    except OSError:
                        pass
                    raise HTTPException(status_code=400, detail=f"File too large: {original_name}")
                handle.write(chunk)
        saved.append({"name": original_name, "path": str(target), "size": bytes_written})
    return {"files": saved}


@router.post("/uploads")
def start_upload(payload: UploadStartRequest, request: Request) -> Dict[str, Any]:
    if not payload.groups:
        raise HTTPException(status_code=400, detail="At least one upload group is required")

    settings_manager = _settings_manager(request)
    settings = {**settings_manager.load(), **payload.settings}
    groups = []
    for index, group_request in enumerate(payload.groups):
        files = [_resolve_allowed_upload_file(file_path) for file_path in group_request.files]
        covers = [_resolve_allowed_upload_file(file_path) for file_path in group_request.cover_files]
        group = UploadBatch(
            title=group_request.title,
            files=files,
            source=group_request.source,
            selected_template=group_request.selected_template,
            selected_thread=group_request.selected_thread,
            batch_index=group_request.batch_index or index,
            cover_files=[cover for cover in covers if cover in files],
        )
        if group_request.gallery:
            gallery = group_request.gallery
            group.gallery_id = str(gallery.get("id") or "")
            group.gallery_name = str(gallery.get("name") or "")
            group.gallery_url = str(gallery.get("url") or "")
            group.gallery_service = str(gallery.get("service") or "")
            group.gallery_upload_hash = str(gallery.get("upload_hash") or "")
        groups.append(group)

    factory = _manager_factory(request)
    create_kwargs = {"manager_factory": factory} if factory else {}
    session = _registry(request).create(
        groups,
        settings,
        _credential_store(request).load_all(),
        **create_kwargs,
    )
    session.start()
    return {"upload": _snapshot_payload(session.snapshot())}


@router.post("/uploads/{upload_id}/cancel")
def cancel_upload(upload_id: str, request: Request) -> Dict[str, Any]:
    session = _registry(request).get(upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    session.cancel()
    return {"upload": _snapshot_payload(session.snapshot())}


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, request: Request) -> Dict[str, Any]:
    session = _registry(request).get(upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    return {"upload": _snapshot_payload(session.snapshot())}


@router.get("/uploads/{upload_id}/events")
async def upload_events(upload_id: str, request: Request) -> StreamingResponse:
    session = _registry(request).get(upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            events = session.drain_events()
            if not events:
                snapshot = _snapshot_payload(session.snapshot())
                yield _sse("snapshot", snapshot)
            else:
                for event in events:
                    yield _sse(event.kind, _event_payload(event))

            if session.state in {"complete", "cancelled", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _sse(event: str, payload: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, sort_keys=True)}\n\n"


@router.get("/history")
def list_history() -> Dict[str, Any]:
    history_dir = Path(config.HISTORY_DIR).expanduser().resolve()
    history_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        _file_record(path, history_dir)
        for path in sorted(history_dir.glob("*.txt"), key=lambda item: item.stat().st_mtime, reverse=True)
        if path.is_file()
    ]
    return {"root": str(history_dir), "entries": entries}


@router.get("/output/{name:path}")
def get_output(name: str) -> FileResponse:
    output_path = _resolve_under(config.OUTPUT_DIR, name)
    if not output_path.exists() or not output_path.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(output_path, filename=output_path.name)
