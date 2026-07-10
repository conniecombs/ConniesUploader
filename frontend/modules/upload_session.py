# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""UI-neutral upload sessions for the web runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        self.results: List[UploadFileResult] = []
        self.output_files: List[UploadGeneratedOutput] = []
        self.last_events: List[UploadProgressEvent] = []
        self._outputs_finalized = False

    def start(self) -> None:
        if self.state not in {"pending", "cancelled", "failed"}:
            return
        self.cancel_event.clear()
        self.started_at = datetime.now(timezone.utc)
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

    def drain_events(self, limit: int = 100) -> List[UploadProgressEvent]:
        events: List[UploadProgressEvent] = []
        for _ in range(max(0, limit)):
            event = self._drain_one_result()
            if event is None:
                event = self._drain_one_progress()
            if event is None:
                break
            events.append(event)

        if events:
            self.last_events.extend(events)
            self.last_events = self.last_events[-200:]
        if self.state == "running" and self.total_files and self.completed_files >= self.total_files:
            self.state = "complete"
            self._finalize_outputs()
        return events

    def snapshot(self) -> UploadSessionSnapshot:
        self.drain_events()
        return UploadSessionSnapshot(
            id=self.id,
            state=self.state,
            total_files=self.total_files,
            completed_files=self.completed_files,
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
                self.last_events.append(
                    UploadProgressEvent("output_error", None, str(exc))
                )
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
            self.last_events.append(
                UploadProgressEvent("output", None, generated)
            )

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
        result = UploadFileResult(file_path, viewer_url, thumb_url)
        self.results.append(result)
        return UploadProgressEvent("result", file_path, result)

    def _drain_one_progress(self) -> UploadProgressEvent | None:
        try:
            kind, file_path, value = self.progress_queue.get_nowait()
        except queue.Empty:
            return None

        return UploadProgressEvent(str(kind), file_path, value)


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
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> UploadSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> List[UploadSessionSnapshot]:
        with self._lock:
            return [session.snapshot() for session in self._sessions.values()]


default_registry = UploadSessionRegistry()
