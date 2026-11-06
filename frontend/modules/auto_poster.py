# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Automatic posting to ViperGirls forum."""

import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from loguru import logger
from modules import config
from modules import viper_api

CredentialsSource = Union[Mapping[str, str], Callable[[], Mapping[str, str]]]

# Seconds the worker keeps waiting for a registered batch after uploads end
# before recording it as "no output generated".
UNRESOLVED_GRACE_SECONDS = 2.0
_SKIPPED = object()
_UNRESOLVED = object()
_STOPPED = object()


class AutoPoster:
    """Posts upload results to ViperGirls threads in batch order.

    A session registers, in order, the batch indexes that will post. Groups
    that never produce output call ``skip`` so later batches are not blocked.
    Credentials come from a provider callable (or a plain mapping) and are
    snapshotted at the start of each session.
    """

    def __init__(self, credentials: CredentialsSource, saved_threads_data: Dict):
        self._credentials_source = credentials
        self.credentials: Dict[str, str] = self._resolve_credentials()
        self.saved_threads_data = saved_threads_data
        self.post_queue: Dict[int, Dict[str, str]] = {}
        self._skipped: Dict[int, str] = {}
        self._expected: List[int] = []
        self.next_index = 0
        self.lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        # Each begin_session bumps the generation; a worker that notices a
        # newer generation finishes its current post and exits without
        # touching the new session's queue.
        self._generation = 0
        self._worker_generation = -1

    # ------------------------------------------------------------------ state

    @property
    def is_running(self) -> bool:
        """True while a worker for the current session is alive."""
        thread = self._worker_thread
        return bool(
            thread is not None and thread.is_alive() and self._worker_generation == self._generation
        )

    def _resolve_credentials(self) -> Dict[str, str]:
        source = self._credentials_source
        try:
            values = source() if callable(source) else source
        except Exception as exc:
            logger.error(f"Auto-Post Queue: could not read credentials: {exc}")
            values = {}
        return {str(key): str(value or "") for key, value in dict(values or {}).items()}

    def begin_session(self, expected_indexes: Sequence[int]) -> None:
        """Start a new posting session for the given ordered batch indexes.

        Never blocks: a worker still posting for the previous session is told
        to finish that post and exit. Posts that were queued but not yet sent
        are recorded as failures ("superseded by a new upload") rather than
        silently dropped.
        """
        ordered: List[int] = []
        for index in expected_indexes:
            value = int(index)
            if value not in ordered:
                ordered.append(value)

        self._generation += 1
        self._stop_event.set()  # wake a waiting worker so it sees the new generation
        self._record_all_pending_failures("superseded by a new upload")
        with self.lock:
            self._skipped.clear()
            self._expected = ordered
            self.next_index = 0
        self.credentials = self._resolve_credentials()
        if ordered:
            logger.info(f"Auto-Post Queue: session expects batches {ordered}")

    def reset(self) -> None:
        """Reset the poster state (for new upload session)."""
        self.begin_session([])

    def _stop_worker(self) -> None:
        thread = self._worker_thread
        if thread is not None and thread.is_alive():
            self._stop_event.set()
            thread.join(timeout=3.0)
        self._worker_thread = None

    def stop(self) -> None:
        """Stop the auto-poster; a waiting or sleeping worker exits at once."""
        self._stop_worker()
        logger.info("AutoPoster stopped")

    # ----------------------------------------------------------------- queue

    def _is_registered(self, batch_index: int) -> bool:
        return not self._expected or batch_index in self._expected

    def queue_post(
        self,
        batch_index: int,
        content: str,
        thread_name: str,
        batch_name: str = "",
    ) -> None:
        """Queue content for posting to a thread.

        Args:
            batch_index: Index of the batch (determines posting order)
            content: Content to post (BBCode text)
            thread_name: Name of the thread to post to
            batch_name: Display name of the source batch
        """
        if not thread_name or thread_name == "Do Not Post":
            return

        with self.lock:
            if not self._is_registered(batch_index):
                logger.warning(
                    f"Auto-Post Queue: Batch #{batch_index} is not part of this session; ignored"
                )
                return
            self._skipped.pop(batch_index, None)
            self.post_queue[batch_index] = {
                "content": content,
                "thread": thread_name,
                "batch_name": batch_name or f"Batch {batch_index + 1}",
            }
            logger.info(f"Auto-Post Queue: Queued Batch #{batch_index} for thread '{thread_name}'")

    def skip(self, batch_index: int, reason: str) -> None:
        """Resolve a registered batch without posting (failed or cancelled)."""
        with self.lock:
            if not self._is_registered(batch_index):
                return
            self.post_queue.pop(batch_index, None)
            self._skipped[batch_index] = str(reason or "skipped")
        logger.info(f"Auto-Post Queue: Batch #{batch_index} skipped: {reason}")

    # ---------------------------------------------------------------- worker

    def start_processing(
        self, is_uploading_callback: Callable[[], bool], cancel_event: threading.Event
    ) -> None:
        """Start processing the post queue in a background thread.

        Args:
            is_uploading_callback: Function that returns True if uploads are still active
            cancel_event: Event to signal cancellation
        """
        if self.is_running:
            logger.warning("Auto-Post Queue: Already running")
            return

        generation = self._generation
        self._stop_event.clear()
        self._worker_generation = generation
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            args=(is_uploading_callback, cancel_event, generation),
            name="AutoPoster",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Auto-Post Queue: Started.")

    def _superseded(self, generation: int) -> bool:
        return self._generation != generation

    def _should_stop(self, cancel_event: threading.Event, generation: int) -> bool:
        return self._superseded(generation) or self._stop_event.is_set() or cancel_event.is_set()

    def _wait_for_index(
        self,
        batch_index: int,
        is_uploading_callback: Callable[[], bool],
        cancel_event: threading.Event,
        generation: int,
    ) -> Any:
        """Block until the batch is queued, skipped, stopped, or given up on."""
        grace_deadline: Optional[float] = None
        while True:
            if self._should_stop(cancel_event, generation):
                return _STOPPED
            with self.lock:
                if batch_index in self.post_queue:
                    return self.post_queue.pop(batch_index)
                if batch_index in self._skipped:
                    return _SKIPPED
            if not is_uploading_callback():
                if grace_deadline is None:
                    grace_deadline = time.monotonic() + UNRESOLVED_GRACE_SECONDS
                elif time.monotonic() >= grace_deadline:
                    return _UNRESOLVED
            self._stop_event.wait(0.25)

    def _process_queue(
        self,
        is_uploading_callback: Callable[[], bool],
        cancel_event: threading.Event,
        generation: int = 0,
    ) -> None:
        """Process queued posts sequentially (worker thread method)."""
        user = self.credentials.get("vg_user", "")
        pwd = self.credentials.get("vg_pass", "")

        if not user or not pwd:
            logger.error("Auto-Post Queue: Missing ViperGirls credentials; posting skipped.")
            self._record_all_pending_failures("missing credentials")
            return

        vg = viper_api.ViperGirlsAPI()
        if not vg.login(user, pwd):
            logger.error(
                "Auto-Post Queue: ViperGirls login failed; check credentials before retrying."
            )
            self._record_all_pending_failures("login failed")
            return

        with self.lock:
            expected = list(self._expected)

        if expected:
            self._process_session(vg, expected, is_uploading_callback, cancel_event, generation)
        else:
            self._process_unordered(vg, is_uploading_callback, cancel_event, generation)

        logger.info("Auto-Post Queue: Finished.")

    def _process_session(
        self,
        vg: Any,
        expected: List[int],
        is_uploading_callback: Callable[[], bool],
        cancel_event: threading.Event,
        generation: int,
    ) -> None:
        for batch_index in expected:
            item = self._wait_for_index(
                batch_index, is_uploading_callback, cancel_event, generation
            )
            if item is _STOPPED:
                if self._superseded(generation):
                    logger.info("Auto-Post Queue: superseded by a new session; worker exiting.")
                    return
                logger.info("Auto-Post Queue: Cancelled.")
                self._record_all_pending_failures("cancelled")
                return
            if item is _SKIPPED:
                self.next_index = batch_index + 1
                continue
            if item is _UNRESOLVED:
                logger.error(f"Auto-Post Queue: Batch #{batch_index} produced no output; skipped.")
                self._record_history_item(
                    {"batch_name": f"Batch {batch_index + 1}", "thread": "", "content": ""},
                    "failure",
                    "",
                    "no output generated",
                )
                self.next_index = batch_index + 1
                continue
            self._post_item(vg, batch_index, item)
            if self._stop_event.wait(config.POST_COOLDOWN_SECONDS) or self._superseded(generation):
                return

    def _process_unordered(
        self,
        vg: Any,
        is_uploading_callback: Callable[[], bool],
        cancel_event: threading.Event,
        generation: int,
    ) -> None:
        """Compatibility mode: post whatever is queued, lowest index first."""
        while True:
            if self._should_stop(cancel_event, generation):
                logger.info("Auto-Post Queue: Cancelled.")
                return
            with self.lock:
                pending = sorted(self.post_queue)
                item = self.post_queue.pop(pending[0]) if pending else None
                batch_index = pending[0] if pending else None
            if item is None:
                if not is_uploading_callback():
                    return
                self._stop_event.wait(0.25)
                continue
            self._post_item(vg, batch_index, item)
            if self._stop_event.wait(config.POST_COOLDOWN_SECONDS) or self._superseded(generation):
                return

    def _post_item(self, vg: Any, batch_index: int, item: Dict[str, str]) -> None:
        content = item.get("content", "")
        thread_name = item.get("thread", "")
        batch_name = item.get("batch_name", f"Batch {batch_index + 1}")
        thread_id, thread_error = self._resolve_thread_id(thread_name)

        if not content:
            logger.error(f"Auto-Post Queue: Batch #{batch_index} has no content; posting skipped.")
            self._record_history_item(item, "failure", thread_id or "", "empty post content")
        elif thread_error:
            logger.error(f"Auto-Post Queue: Batch #{batch_index} skipped: {thread_error}.")
            self._record_history_item(item, "failure", "", thread_error)
        else:
            logger.info(
                f"Auto-Post Queue: Posting Batch #{batch_index} "
                f"({batch_name}) to '{thread_name}' (thread {thread_id})."
            )
            error = ""
            try:
                posted = vg.post_reply(thread_id, content)
            except Exception as exc:
                error = str(exc)
                logger.exception(
                    f"Auto-Post Queue: Batch #{batch_index} post failed "
                    f"for '{thread_name}' (thread {thread_id}): {exc}"
                )
                posted = False

            if posted:
                logger.info(f"Auto-Post Queue: Batch #{batch_index} SUCCESS.")
                self._mark_target_used(thread_name)
                self._record_history_item(item, "success", thread_id, "")
            else:
                error = error or "post rejected or failed"
                logger.error(
                    f"Auto-Post Queue: Batch #{batch_index} post rejected/failed "
                    f"for '{thread_name}' (thread {thread_id})."
                )
                self._record_history_item(item, "failure", thread_id, error)

        self.next_index = batch_index + 1

    # --------------------------------------------------------------- helpers

    def _resolve_thread_id(self, thread_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Resolve a saved posting target to a ViperGirls thread ID.

        Returns ``(thread_id, error)`` where one value is populated.
        """
        clean_name = str(thread_name or "").strip()
        if not clean_name:
            return None, "posting target is missing"

        if clean_name not in self.saved_threads_data:
            return None, f"target '{clean_name}' is missing"

        data = self.saved_threads_data[clean_name]
        if isinstance(data, dict):
            thread_id = viper_api.extract_thread_id(str(data.get("thread_id") or ""))
            if thread_id:
                return thread_id, None

            thread_id = viper_api.extract_thread_id(str(data.get("url") or ""))
            if thread_id:
                return thread_id, None
        else:
            thread_id = viper_api.extract_thread_id(str(data or ""))
            if thread_id:
                return thread_id, None

        return None, f"target '{clean_name}' has an invalid thread ID"

    def _get_thread_id(self, thread_name: str) -> Optional[str]:
        thread_id, _error = self._resolve_thread_id(thread_name)
        return thread_id

    def _target_url(self, thread_name: str, thread_id: str = "") -> str:
        data = self.saved_threads_data.get(thread_name, {})
        if isinstance(data, dict) and data.get("url"):
            return str(data.get("url") or "")
        if thread_id:
            return f"{viper_api.VIPERGIRLS_BASE_URL}/threads/{thread_id}"
        return ""

    def _record_history_item(
        self,
        item: Dict[str, str],
        status: str,
        thread_id: str = "",
        error: str = "",
    ) -> None:
        thread_name = str(item.get("thread") or "")
        try:
            viper_api.append_posting_history(
                {
                    "batch_name": item.get("batch_name") or "Batch",
                    "target_name": thread_name,
                    "thread_id": thread_id,
                    "target_url": self._target_url(thread_name, thread_id),
                    "status": status,
                    "error": error,
                    "post_text": item.get("content") or "",
                }
            )
        except OSError as exc:
            logger.error(f"Could not save ViperGirls posting history: {exc}")

    def _record_all_pending_failures(self, error: str) -> None:
        with self.lock:
            pending_items = list(self.post_queue.values())
            self.post_queue.clear()

        for item in pending_items:
            thread_name = str(item.get("thread") or "")
            thread_id, _thread_error = self._resolve_thread_id(thread_name)
            self._record_history_item(item, "failure", thread_id or "", error)

    def _mark_target_used(self, thread_name: str) -> None:
        try:
            record = viper_api.mark_thread_target_used(thread_name)
        except OSError as exc:
            logger.error(f"Could not update ViperGirls target last-used time: {exc}")
            return

        if record:
            self.saved_threads_data[thread_name] = record
