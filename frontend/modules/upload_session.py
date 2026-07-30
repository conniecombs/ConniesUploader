# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""UI-neutral upload sessions for the web runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import queue
import threading
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import config
from .settings_manager import SettingsManager
from .sidecar import SidecarBridge
from .template_core import HeadlessTemplateManager
from .upload_manager import UploadManager
from .upload_models import (
    UploadBatch,
    UploadFileResult,
    UploadGeneratedOutput,
    UploadProgressEvent,
)
from .upload_output import generate_failed_group_output, generate_group_output


UploadManagerFactory = Callable[
    [queue.Queue, queue.Queue, threading.Event],
    UploadManager,
]
ViperApiFactory = Callable[[], Any]


@dataclass
class UploadSessionSnapshot:
    id: str
    state: str
    total_files: int
    completed_files: int
    failed_files: int = 0
    results: List[UploadFileResult] = field(default_factory=list)
    output_files: List[UploadGeneratedOutput] = field(default_factory=list)
    last_events: List[UploadProgressEvent] = field(default_factory=list)


class UploadSession:
    """Manage one upload run without depending on desktop widgets."""

    def __init__(
        self,
        groups: Iterable[UploadBatch],
        settings: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        manager_factory: UploadManagerFactory = UploadManager,
        template_manager: Any | None = None,
        viper_api_factory: ViperApiFactory | None = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.id = session_id or str(uuid.uuid4())
        self.groups = list(groups)
        self.settings = SettingsManager().normalize_numeric_ranges(dict(settings))
        self.credentials = dict(credentials)
        self.progress_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.result_queue: queue.Queue = queue.Queue(maxsize=1000)
        self.cancel_event = threading.Event()
        self.upload_manager = manager_factory(
            self.progress_queue,
            self.result_queue,
            self.cancel_event,
        )
        self.template_manager = template_manager or HeadlessTemplateManager()
        self.viper_api_factory = viper_api_factory
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.state = "pending"
        self.total_files = sum(len(group.files) for group in self.groups)
        self.completed_files = 0
        self.failed_files = 0
        self.results: List[UploadFileResult] = []
        self.output_files: List[UploadGeneratedOutput] = []
        self.last_events: List[UploadProgressEvent] = []
        self.finished_at: Optional[datetime] = None
        self.updated_at = self.created_at
        self._event_log: List[UploadProgressEvent] = []
        self._event_lock = threading.RLock()
        self._outputs_finalized = False

    def start(self) -> None:
        if self.state not in {"pending", "cancelled", "failed"}:
            return
        self.cancel_event.clear()
        self.started_at = datetime.now(timezone.utc)
        self.finished_at = None
        self.updated_at = self.started_at
        self.state = "running"

        SidecarBridge.set_worker_count(self.settings.get("global_worker_count", 8))
        upload_settings = dict(self.settings)
        if upload_settings.get("global_worker_count") == 1:
            upload_settings["global_thread_limit"] = 1
            upload_settings["threads"] = 1

        pending_by_group = {group: list(group.files) for group in self.groups if group.files}
        self.upload_manager.start_batch(pending_by_group, upload_settings, self.credentials)

    def cancel(self) -> None:
        self.cancel_event.set()
        self.state = "cancelled"
        self.finished_at = datetime.now(timezone.utc)
        self.updated_at = self.finished_at
        shutdown = getattr(self.upload_manager, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def drain_events(self, limit: int = 100) -> List[UploadProgressEvent]:
        return self.collect_events(limit=limit)

    def collect_events(self, limit: int = 100) -> List[UploadProgressEvent]:
        events: List[UploadProgressEvent] = []
        with self._event_lock:
            for _ in range(max(0, limit)):
                event = self._drain_one_result()
                if event is None:
                    event = self._drain_one_progress()
                if event is None:
                    break
                events.append(event)
                self._record_event(event)

            if self.state == "running" and self.total_files and self.completed_files >= self.total_files:
                self.state = "failed" if self.failed_files else "complete"
                self.finished_at = datetime.now(timezone.utc)
                self.updated_at = self.finished_at
                self._finalize_outputs()
        return events

    def events_since(self, cursor: int = 0, limit: int = 200) -> tuple[int, List[UploadProgressEvent]]:
        with self._event_lock:
            self.collect_events()
            start = max(0, int(cursor or 0))
            end = min(len(self._event_log), start + max(1, limit))
            return end, list(self._event_log[start:end])

    def snapshot(self) -> UploadSessionSnapshot:
        self.collect_events()
        return UploadSessionSnapshot(
            id=self.id,
            state=self.state,
            total_files=self.total_files,
            completed_files=self.completed_files,
            failed_files=self.failed_files,
            results=list(self.results),
            output_files=list(self.output_files),
            last_events=list(self.last_events),
        )

    def _finalize_outputs(self) -> None:
        if self._outputs_finalized:
            return
        self._outputs_finalized = True

        result_by_path = {result.file_path: result for result in self.results}
        saved_threads = self._load_vipergirls_targets()
        for group in self.groups:
            group_results = [
                result_by_path[file_path]
                for file_path in group.files
                if file_path in result_by_path
            ]
            incomplete = len(group_results) != len(group.files) or any(
                not result.success or not str(result.viewer_url or "").strip()
                for result in group_results
            )
            try:
                if incomplete:
                    output = generate_failed_group_output(
                        group,
                        group_results,
                        self.settings,
                        output_dir=config.OUTPUT_DIR,
                        history_dir=config.HISTORY_DIR,
                    )
                else:
                    output = generate_group_output(
                        group,
                        group_results,
                        self.settings,
                        self.template_manager,
                        output_dir=config.OUTPUT_DIR,
                        history_dir=config.HISTORY_DIR,
                        saved_threads_data=saved_threads,
                    )
            except Exception as exc:
                self._record_event(UploadProgressEvent("output_error", None, str(exc)))
                continue
            if output is None:
                continue

            generated = UploadGeneratedOutput(
                group_title=str(getattr(group, "title", "") or ""),
                text=output.text,
                output_file=output.output_file,
                output_name=self._relative_output_name(output.output_file),
                history_file=output.history_file,
                links_file=output.links_file,
                links_name=(
                    self._relative_output_name(output.links_file)
                    if output.links_file
                    else None
                ),
                copyable=output.copyable,
                failed_report=output.failed_report,
            )
            self.output_files.append(generated)
            self._record_event(UploadProgressEvent("output", None, generated))
            if generated.copyable:
                self._post_to_vipergirls_if_requested(group, generated, saved_threads)

    def _load_vipergirls_targets(self) -> Dict[str, Any]:
        try:
            from . import viper_api

            viper_api.configure_storage(config.USER_DATA_DIR)
            return viper_api.load_saved_threads()
        except Exception as exc:
            self._record_event(UploadProgressEvent("post_error", None, str(exc)))
            return {}

    def _post_to_vipergirls_if_requested(
        self,
        group: UploadBatch,
        generated: UploadGeneratedOutput,
        saved_threads: Dict[str, Any],
    ) -> None:
        if not self.settings.get("auto_post_enabled"):
            return

        target_name = str(getattr(group, "selected_thread", "") or "").strip()
        if not target_name or target_name == "Do Not Post":
            return

        try:
            from . import viper_api

            viper_api.configure_storage(config.USER_DATA_DIR)
            record = saved_threads.get(target_name) if isinstance(saved_threads, dict) else None
            thread_id = viper_api.extract_thread_id(str((record or {}).get("thread_id") or ""))
            if not thread_id:
                raise viper_api.ViperPostError(
                    f'ViperGirls target "{target_name}" is missing a usable thread ID.'
                )

            username = str(self.credentials.get("vg_user") or "").strip()
            password = str(self.credentials.get("vg_pass") or "").strip()
            if not username or not password:
                raise viper_api.ViperPostError("Missing ViperGirls credentials.")

            client = self.viper_api_factory() if self.viper_api_factory else viper_api.ViperGirlsAPI()
            if not client.login(username, password):
                raise viper_api.ViperPostError("ViperGirls login failed.")

            posted = client.post_reply(thread_id, generated.text)
            if not posted:
                raise viper_api.ViperPostError("ViperGirls post failed.")

            viper_api.mark_thread_target_used(target_name)
            entry = viper_api.append_posting_history(
                {
                    "batch_name": generated.group_title,
                    "target_name": target_name,
                    "thread_id": thread_id,
                    "target_url": str((record or {}).get("url") or ""),
                    "status": "success",
                    "post_text": generated.text,
                }
            )
            self._record_event(UploadProgressEvent("post", None, entry))
        except Exception as exc:
            entry = self._record_failed_vipergirls_post(group, generated, target_name, str(exc))
            self._record_event(UploadProgressEvent("post_error", None, entry))

    def _record_failed_vipergirls_post(
        self,
        group: UploadBatch,
        generated: UploadGeneratedOutput,
        target_name: str,
        error: str,
    ) -> Dict[str, str]:
        try:
            from . import viper_api

            viper_api.configure_storage(config.USER_DATA_DIR)
            saved_threads = viper_api.load_saved_threads()
            record = saved_threads.get(target_name, {}) if target_name else {}
            entry = viper_api.append_posting_history(
                {
                    "batch_name": generated.group_title or getattr(group, "title", "Batch"),
                    "target_name": target_name,
                    "thread_id": str(record.get("thread_id") or ""),
                    "target_url": str(record.get("url") or ""),
                    "status": "failed",
                    "error": error,
                    "post_text": generated.text,
                }
            )
            return entry
        except Exception:
            return {
                "batch_name": generated.group_title,
                "target_name": target_name,
                "thread_id": "",
                "target_url": "",
                "status": "failed",
                "error": error,
                "post_text": generated.text,
            }

    @staticmethod
    def _relative_output_name(filepath: str) -> str:
        path = Path(filepath).expanduser().resolve()
        root = Path(config.OUTPUT_DIR).expanduser().resolve()
        try:
            return str(path.relative_to(root))
        except ValueError:
            return path.name

    def _drain_one_result(self) -> UploadProgressEvent | None:
        try:
            file_path, viewer_url, thumb_url = self.result_queue.get_nowait()
        except queue.Empty:
            return None

        self.completed_files += 1
        success = bool(viewer_url or thumb_url)
        if not success:
            self.failed_files += 1
        result = UploadFileResult(
            file_path,
            viewer_url,
            thumb_url,
            success=success,
            error="" if success else "Upload failed",
        )
        self.results.append(result)
        return UploadProgressEvent("result", file_path, result)

    def _drain_one_progress(self) -> UploadProgressEvent | None:
        try:
            kind, file_path, value = self.progress_queue.get_nowait()
        except queue.Empty:
            return None

        return UploadProgressEvent(str(kind), file_path, value)

    def _record_event(self, event: UploadProgressEvent) -> None:
        self.updated_at = datetime.now(timezone.utc)
        self.last_events.append(event)
        self.last_events = self.last_events[-200:]
        self._event_log.append(event)
        self._event_log = self._event_log[-1000:]


class UploadSessionRegistry:
    """In-memory session registry for the first web runtime slice."""

    def __init__(self) -> None:
        self._sessions: Dict[str, UploadSession] = {}
        self._lock = threading.RLock()

    def create(
        self,
        groups: Iterable[UploadBatch],
        settings: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        manager_factory: UploadManagerFactory = UploadManager,
        template_manager: Any | None = None,
        viper_api_factory: ViperApiFactory | None = None,
    ) -> UploadSession:
        session = UploadSession(
            groups,
            settings,
            credentials,
            manager_factory=manager_factory,
            template_manager=template_manager,
            viper_api_factory=viper_api_factory,
        )
        with self._lock:
            self.prune_locked()
            self._sessions[session.id] = session
        return session

    def create_if_idle(
        self,
        groups: Iterable[UploadBatch],
        settings: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        manager_factory: UploadManagerFactory = UploadManager,
        template_manager: Any | None = None,
        viper_api_factory: ViperApiFactory | None = None,
    ) -> UploadSession | None:
        with self._lock:
            self.prune_locked()
            if self._has_active_locked():
                return None
            session = UploadSession(
                groups,
                settings,
                credentials,
                manager_factory=manager_factory,
                template_manager=template_manager,
                viper_api_factory=viper_api_factory,
            )
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str) -> UploadSession | None:
        with self._lock:
            self.prune_locked()
            return self._sessions.get(session_id)

    def list(self) -> List[UploadSessionSnapshot]:
        with self._lock:
            self.prune_locked()
            return [session.snapshot() for session in self._sessions.values()]

    def has_active(self) -> bool:
        with self._lock:
            self.prune_locked()
            return self._has_active_locked()

    def _has_active_locked(self) -> bool:
        return any(
            session.state not in {"complete", "cancelled", "failed"}
            for session in self._sessions.values()
        )

    def prune_locked(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=config.WEB_SESSION_RETENTION_SECONDS
        )
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.state in {"complete", "cancelled", "failed"}
            and (session.finished_at or session.updated_at) < cutoff
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


default_registry = UploadSessionRegistry()
