# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Per-job state and the post-processing pool of the Python upload path."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from loguru import logger

from .result_matcher import ResultPageMatcher
from .upload_results import normalize_secrets


class SessionState(dict):
    """State shared by the ``parse_upload_response`` calls of one upload job.

    It is a dict a plugin may keep its own values in (for example a gallery
    URL found by the first file). The job's files are parsed concurrently, so
    a read-modify-write must hold ``lock``; ``get_or_create`` does that for
    you.

    ``files`` lists the job's files (as the sidecar reports them), and
    ``secrets`` the values no failure message may quote (the plugin's
    credentials and the session values ``open_upload_session`` returned; add
    more with ``add_secrets``).

    ``result_matcher(mode)`` returns the job's shared ``ResultPageMatcher`` for
    that mode. The upload manager keeps it informed: ``record_uploaded`` when
    the host received a file's whole body, ``settle`` when a file is finished.
    """

    def __init__(self, files: Sequence[str] = (), secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self.files: Tuple[str, ...] = tuple(files)
        self.lock = threading.RLock()
        self._secrets: List[str] = list(secrets)
        self._uploaded: List[str] = []
        self._settled: set = set()
        self._matchers: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], ResultPageMatcher] = {}

    @property
    def secrets(self) -> List[str]:
        with self.lock:
            return normalize_secrets(self._secrets)

    def add_secrets(self, *values: str) -> None:
        """Values to redact from failure messages, such as a token a parser extracted."""
        with self.lock:
            self._secrets.extend(str(value) for value in values if value)

    @property
    def uploaded_files(self) -> Tuple[str, ...]:
        """Files whose whole body reached the host, in that order."""
        with self.lock:
            return tuple(self._uploaded)

    def is_settled(self, file_path: str) -> bool:
        with self.lock:
            return file_path in self._settled

    def get_or_create(self, key: str, factory: Callable[[], Any]) -> Any:
        """``self[key]``, created by ``factory()`` on first use, atomically."""
        with self.lock:
            if key not in self:
                self[key] = factory()
            return self[key]

    def record_uploaded(self, file_path: str) -> None:
        with self.lock:
            if file_path in self._uploaded:
                return
            self._uploaded.append(file_path)
            for matcher in self._matchers.values():
                matcher.record_uploaded(file_path)

    def settle(self, file_path: str) -> None:
        with self.lock:
            self._settled.add(file_path)
            for matcher in self._matchers.values():
                matcher.settle(file_path)

    def result_matcher(
        self, mode: str = "filename", file_names: Optional[Mapping[str, str]] = None
    ) -> ResultPageMatcher:
        """The job's matcher for ``mode`` (created on first use, then shared)."""
        key = (str(mode or ""), tuple(sorted((file_names or {}).items())))
        with self.lock:
            matcher = self._matchers.get(key)
            if matcher is None:
                matcher = ResultPageMatcher(self.files, mode=mode, file_names=file_names)
                for file_path in self._uploaded:
                    matcher.record_uploaded(file_path)
                for file_path in self._settled:
                    matcher.settle(file_path)
                self._matchers[key] = matcher
            return matcher


class PostProcessingPool:
    """A few daemon threads that run upload post-processing tasks.

    Parsers may make follow-up requests and poll result pages, so they run
    here and never on the sidecar event listener. Daemon threads never hold
    up the app's exit.
    """

    def __init__(self, workers: int = 4, name: str = "UploadPostProcess") -> None:
        self._workers = max(1, int(workers))
        self._name = name
        self._tasks: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._threads: List[threading.Thread] = []
        self._start_lock = threading.Lock()

    def submit(self, task: Callable[[], None]) -> None:
        self._ensure_started()
        self._tasks.put(task)

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._threads:
                return
            for index in range(self._workers):
                thread = threading.Thread(
                    target=self._run, name=f"{self._name}-{index + 1}", daemon=True
                )
                thread.start()
                self._threads.append(thread)

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            try:
                task()
            except Exception as exc:  # a task must never kill its worker
                logger.exception(f"Upload post-processing task failed: {exc}")
