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
import uuid

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, Response, UploadFile
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
from web.auth_store import AccountValidationError, WebAccountStore
from web.security import (
    authenticate_credentials,
    clear_session,
    issue_session,
    request_authorized,
    request_username,
    security_status,
    setup_required,
)

router = APIRouter(prefix="/api")


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any]


class CredentialUpdateRequest(BaseModel):
    credentials: Dict[str, Any]


class ViperGirlsTargetRequest(BaseModel):
    name: str
    url: str
    old_name: str = ""
    notes: str = ""
    tags: List[str] | str = Field(default_factory=list)
    fetch_title: bool = False


class ViperGirlsPostRequest(BaseModel):
    target_name: str
    message: str
    batch_name: str = "Web Post"


class ViperGirlsScheduleRequest(BaseModel):
    target_name: str
    message: str
    scheduled_time: str
    batch_name: str = "Scheduled Post"
    cover_thumbnail: str = ""


class AuthCredentialsRequest(BaseModel):
    username: str
    password: str


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
    app.state.web_account_store = getattr(app.state, "web_account_store", WebAccountStore())
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


def _viper_api_factory(request: Request):
    return getattr(request.app.state, "viper_api_factory", None)


def _web_account_store(request: Request) -> WebAccountStore:
    return getattr(request.app.state, "web_account_store", None) or WebAccountStore()


def _viper_api():
    from modules import viper_api

    viper_api.configure_storage(config.USER_DATA_DIR)
    return viper_api


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


def _delete_file_under(root: str, relative_path: str, missing_detail: str) -> Dict[str, str]:
    target = _resolve_under(root, relative_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=missing_detail)
    root_path = Path(root).expanduser().resolve()
    relative_name = str(target.relative_to(root_path))
    target.unlink()
    return {"name": target.name, "relative_path": relative_name}


def _staged_upload_files(upload_dir: Path) -> List[Path]:
    if not upload_dir.exists():
        return []
    return [path for path in upload_dir.iterdir() if path.is_file() or path.is_symlink()]


def _cleanup_staged_uploads(upload_dir: Path) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc).timestamp() - config.WEB_UPLOAD_RETENTION_SECONDS
    for path in _staged_upload_files(upload_dir):
        try:
            stat = path.lstat()
        except OSError:
            continue
        if path.is_symlink() or stat.st_mtime < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def _staged_upload_usage(upload_dir: Path) -> tuple[int, int]:
    count = 0
    total = 0
    for path in _staged_upload_files(upload_dir):
        try:
            stat = path.lstat()
        except OSError:
            continue
        count += 1
        total += stat.st_size
    return count, total


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


def _viper_target_items(targets: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"name": name, **dict(record)}
        for name, record in sorted(targets.items(), key=lambda item: item[0].lower())
    ]


def _load_viper_targets() -> Dict[str, Dict[str, Any]]:
    return _viper_api().load_saved_threads()


def _resolve_viper_target(name: str) -> tuple[str, Dict[str, Any]]:
    clean_name = str(name or "").strip()
    targets = _load_viper_targets()
    record = targets.get(clean_name)
    if not record:
        raise HTTPException(status_code=404, detail="ViperGirls target not found.")
    return clean_name, record


def _viper_credentials(request: Request) -> Dict[str, str]:
    credentials = _credential_store(request).load_all()
    return {
        "vg_user": str(credentials.get("vg_user") or "").strip(),
        "vg_pass": str(credentials.get("vg_pass") or "").strip(),
    }


@router.get("/vipergirls/targets")
def list_vipergirls_targets() -> Dict[str, Any]:
    return {"targets": _viper_target_items(_load_viper_targets())}


@router.put("/vipergirls/targets")
def put_vipergirls_target(payload: ViperGirlsTargetRequest) -> Dict[str, Any]:
    api = _viper_api()
    targets = _load_viper_targets()
    old_name = str(payload.old_name or "").strip()
    requested_name = str(payload.name or "").strip()
    existing = targets.get(old_name or requested_name, {})

    try:
        if payload.fetch_title:
            target_name, record, _fetched = api.build_site_named_thread_record(
                requested_name,
                payload.url,
                existing=existing,
                notes=payload.notes,
                tags=payload.tags,
                existing_names=targets.keys(),
                exclude=old_name or requested_name,
            )
        else:
            if not requested_name:
                raise api.ThreadTargetError("Target name is required.")
            target_name = requested_name
            record = api.normalize_thread_record(
                target_name,
                payload.url,
                existing=existing,
                notes=payload.notes,
                tags=payload.tags,
            )
    except api.ThreadTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if target_name in targets and target_name != (old_name or target_name):
        raise HTTPException(status_code=409, detail="A target with that name already exists.")

    updated = dict(targets)
    if old_name and old_name != target_name:
        updated.pop(old_name, None)
    updated[target_name] = record
    api.save_saved_threads(updated)
    return {"target": {"name": target_name, **dict(record)}, "targets": _viper_target_items(updated)}


@router.delete("/vipergirls/targets/{name:path}")
def delete_vipergirls_target(name: str) -> Dict[str, Any]:
    api = _viper_api()
    targets = _load_viper_targets()
    if name not in targets:
        raise HTTPException(status_code=404, detail="ViperGirls target not found.")
    updated = dict(targets)
    updated.pop(name, None)
    api.save_saved_threads(updated)
    return {"targets": _viper_target_items(updated)}


@router.post("/vipergirls/preview")
def preview_vipergirls_post(payload: ViperGirlsPostRequest) -> Dict[str, Any]:
    _name, record = _resolve_viper_target(payload.target_name)
    message = str(payload.message or "")
    if not message.strip():
        raise HTTPException(status_code=400, detail="Post message is empty.")
    return {
        "target": {"name": payload.target_name, **dict(record)},
        "batch_name": payload.batch_name,
        "message": message,
    }


@router.post("/vipergirls/post")
def post_vipergirls_now(payload: ViperGirlsPostRequest, request: Request) -> Dict[str, Any]:
    api = _viper_api()
    target_name, record = _resolve_viper_target(payload.target_name)
    message = str(payload.message or "")
    thread_id = api.extract_thread_id(str(record.get("thread_id") or ""))
    if not message.strip():
        raise HTTPException(status_code=400, detail="Post message is empty.")
    if not thread_id:
        raise HTTPException(status_code=400, detail="ViperGirls target has no usable thread ID.")

    creds = _viper_credentials(request)
    if not creds["vg_user"] or not creds["vg_pass"]:
        raise HTTPException(status_code=400, detail="ViperGirls credentials are missing.")

    status = "failed"
    error = ""
    status_code = 502
    try:
        factory = _viper_api_factory(request)
        client = factory() if factory else api.ViperGirlsAPI()
        if not client.login(creds["vg_user"], creds["vg_pass"]):
            error = "ViperGirls login failed."
        elif client.post_reply(thread_id, message):
            status = "success"
            status_code = 200
            api.mark_thread_target_used(target_name)
        else:
            error = "ViperGirls post failed."
    except Exception as exc:
        error = str(exc)

    entry = api.append_posting_history(
        {
            "batch_name": payload.batch_name,
            "target_name": target_name,
            "thread_id": thread_id,
            "target_url": str(record.get("url") or ""),
            "status": status,
            "error": error,
            "post_text": message,
        }
    )
    if status != "success":
        raise HTTPException(status_code=status_code, detail=error or "ViperGirls post failed.")
    return {"history": entry}


@router.get("/vipergirls/history")
def list_vipergirls_history() -> Dict[str, Any]:
    return {"history": list(reversed(_viper_api().load_posting_history()))}


@router.delete("/vipergirls/history")
def clear_vipergirls_history() -> Dict[str, Any]:
    _viper_api().clear_posting_history()
    return {"history": []}


@router.get("/vipergirls/scheduled")
def list_vipergirls_scheduled() -> Dict[str, Any]:
    return {"scheduled": _viper_api().load_scheduled_posts()}


@router.post("/vipergirls/scheduled")
def schedule_vipergirls_post(payload: ViperGirlsScheduleRequest) -> Dict[str, Any]:
    api = _viper_api()
    target_name, record = _resolve_viper_target(payload.target_name)
    thread_id = api.extract_thread_id(str(record.get("thread_id") or ""))
    if not thread_id:
        raise HTTPException(status_code=400, detail="ViperGirls target has no usable thread ID.")
    try:
        scheduled = api.add_scheduled_post(
            {
                "id": str(uuid.uuid4()),
                "thread_id": thread_id,
                "thread_name": target_name or payload.batch_name,
                "message": payload.message,
                "scheduled_time": payload.scheduled_time,
                "cover_thumbnail": payload.cover_thumbnail,
            }
        )
    except api.ViperPostError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"scheduled": scheduled, "items": api.load_scheduled_posts()}


@router.delete("/vipergirls/scheduled/{post_id}")
def cancel_vipergirls_scheduled(post_id: str) -> Dict[str, Any]:
    api = _viper_api()
    if not api.cancel_scheduled_post(post_id):
        raise HTTPException(status_code=404, detail="Pending scheduled post not found.")
    return {"scheduled": api.load_scheduled_posts()}


@router.get("/auth/status")
def auth_status(request: Request) -> Dict[str, Any]:
    status = security_status()
    username = request_username(request)
    return {
        **status,
        "authenticated": request_authorized(request),
        "username": username,
    }


@router.post("/auth/setup")
def setup_account(
    payload: AuthCredentialsRequest,
    request: Request,
    response: Response,
) -> Dict[str, Any]:
    if not setup_required():
        raise HTTPException(status_code=409, detail="A web account is already configured.")
    try:
        account = _web_account_store(request).create_account(payload.username, payload.password)
    except AccountValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    issue_session(response, account["username"])
    return {"ok": True, "username": account["username"]}


@router.post("/auth/login")
def login(payload: AuthCredentialsRequest, response: Response) -> Dict[str, Any]:
    if setup_required():
        raise HTTPException(status_code=428, detail="Create the first web account before signing in.")
    if not authenticate_credentials(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    issue_session(response, payload.username)
    return {"ok": True, "username": payload.username}


@router.post("/auth/logout")
def logout(response: Response) -> Dict[str, bool]:
    clear_session(response)
    return {"ok": True}


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
    _cleanup_staged_uploads(upload_dir)
    file_count, total_bytes = _staged_upload_usage(upload_dir)
    saved = []
    for upload in files:
        if file_count >= config.WEB_UPLOAD_MAX_FILES:
            raise HTTPException(status_code=413, detail="Staged upload file limit reached")
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
                if total_bytes + bytes_written > config.WEB_UPLOAD_MAX_BYTES:
                    handle.close()
                    try:
                        target.unlink()
                    except OSError:
                        pass
                    raise HTTPException(status_code=413, detail="Staged upload storage limit reached")
                handle.write(chunk)
        saved.append({"name": original_name, "path": str(target), "size": bytes_written})
        file_count += 1
        total_bytes += bytes_written
    return {"files": saved}


@router.post("/uploads")
def start_upload(payload: UploadStartRequest, request: Request) -> Dict[str, Any]:
    if not payload.groups:
        raise HTTPException(status_code=400, detail="At least one upload group is required")

    registry = _registry(request)
    if registry.has_active():
        raise HTTPException(status_code=409, detail="Another upload is already running")

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
    viper_factory = _viper_api_factory(request)
    if viper_factory:
        create_kwargs["viper_api_factory"] = viper_factory
    session = registry.create(
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
        cursor = 0
        while True:
            if await request.is_disconnected():
                break
            cursor, events = session.events_since(cursor)
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


@router.delete("/history/{name:path}")
def delete_history_file(name: str) -> Dict[str, Any]:
    deleted = _delete_file_under(config.HISTORY_DIR, name, "History file not found")
    return {"deleted": deleted}


@router.get("/output/{name:path}")
def get_output(name: str) -> FileResponse:
    output_path = _resolve_under(config.OUTPUT_DIR, name)
    if not output_path.exists() or not output_path.is_file():
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(output_path, filename=output_path.name)


@router.delete("/output/{name:path}")
def delete_output(name: str) -> Dict[str, Any]:
    deleted = _delete_file_under(config.OUTPUT_DIR, name, "Output file not found")
    return {"deleted": deleted}
