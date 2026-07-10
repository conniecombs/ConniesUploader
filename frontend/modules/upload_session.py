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
from .upload_output import generate_group_output


UploadManagerFactory = Callable[
    [queue.Queue, queue.Queue, threading.Event],
    UploadManager,
]


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

        result_tuples = [
            (result.file_path, result.viewer_url, result.thumb_url)
            for result in self.results
            if result.success
        ]
        for group in self.groups:
            try:
                output = generate_group_output(
                    group,
                    result_tuples,
                    self.settings,
                    self.template_manager,
                    output_dir=config.OUTPUT_DIR,
                    history_dir=config.HISTORY_DIR,
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
            )
            self.output_files.append(generated)
            self._record_event(UploadProgressEvent("output", None, generated))

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
    ) -> UploadSession:
        session = UploadSession(
            groups,
            settings,
            credentials,
            manager_factory=manager_factory,
            template_manager=template_manager,
        )
        with self._lock:
            self.prune_locked()
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
