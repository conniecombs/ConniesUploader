# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Automatic posting to ViperGirls forum."""

import time
import threading
from typing import Dict, Optional, Callable, Tuple
from loguru import logger
from modules import config
from modules import viper_api


class AutoPoster:
    """Handles automatic posting of upload results to ViperGirls forum threads.

    This class manages a queue of posts and processes them sequentially with
    cooldown periods to avoid rate limiting.
    """

    def __init__(self, credentials: Dict[str, str], saved_threads_data: Dict):
        """Initialize AutoPoster.

        Args:
            credentials: Dictionary containing vg_user and vg_pass
            saved_threads_data: Dictionary of saved thread information
        """
        self.credentials = credentials
        self.saved_threads_data = saved_threads_data
        self.post_queue: Dict[int, Dict[str, str]] = {}
        self.next_index = 0
        self.lock = threading.Lock()
        self.is_running = False
        self._worker_thread: Optional[threading.Thread] = None

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
            self.post_queue[batch_index] = {
                "content": content,
                "thread": thread_name,
                "batch_name": batch_name or f"Batch {batch_index + 1}",
            }
            logger.info(f"Auto-Post Queue: Queued Batch #{batch_index} for thread '{thread_name}'")

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

        self.is_running = True
        self._worker_thread = threading.Thread(
            target=self._process_queue,
            args=(is_uploading_callback, cancel_event),
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Auto-Post Queue: Started.")

    def _process_queue(
        self, is_uploading_callback: Callable[[], bool], cancel_event: threading.Event
    ) -> None:
        """Process queued posts sequentially (worker thread method).

        Args:
            is_uploading_callback: Function that returns True if uploads are still active
            cancel_event: Event to signal cancellation
        """
        # Initialize ViperGirls API
        user = self.credentials.get("vg_user", "")
        pwd = self.credentials.get("vg_pass", "")

        if not user or not pwd:
            logger.error("Auto-Post Queue: Missing ViperGirls credentials; posting skipped.")
            self._record_all_pending_failures("missing credentials")
            self.is_running = False
            return

        vg = viper_api.ViperGirlsAPI()
        if not vg.login(user, pwd):
            logger.error(
                "Auto-Post Queue: ViperGirls login failed; check credentials before retrying."
            )
            self._record_all_pending_failures("login failed")
            self.is_running = False
            return

        # Process queue until uploads finish and queue is empty
        with self.lock:
            queue_has_items = len(self.post_queue) > 0

        while is_uploading_callback() or queue_has_items:
            if cancel_event.is_set():
                logger.info("Auto-Post Queue: Cancelled.")
                break

            # Check if next post is ready and get item atomically
            with self.lock:
                if self.next_index in self.post_queue:
                    item = self.post_queue.pop(self.next_index)
                else:
                    item = None

            if item:
                content = item.get("content", "")
                thread_name = item.get("thread", "")
                batch_name = item.get("batch_name", f"Batch {self.next_index + 1}")

                # Extract thread ID from saved thread data
                thread_id, thread_error = self._resolve_thread_id(thread_name)

                if not content:
                    error = "empty post content"
                    logger.error(
                        f"Auto-Post Queue: Batch #{self.next_index} has no content; posting skipped."
                    )
                    self._record_history_item(item, "failure", thread_id or "", error)
                elif thread_error:
                    logger.error(
                        f"Auto-Post Queue: Batch #{self.next_index} skipped: {thread_error}."
                    )
                    self._record_history_item(item, "failure", "", thread_error)
                else:
                    logger.info(
                        f"Auto-Post Queue: Posting Batch #{self.next_index} "
                        f"({batch_name}) to '{thread_name}' (thread {thread_id})."
                    )

                    error = ""
                    try:
                        posted = vg.post_reply(thread_id, content)
                    except Exception as exc:
                        error = str(exc)
                        logger.exception(
                            f"Auto-Post Queue: Batch #{self.next_index} post failed "
                            f"for '{thread_name}' (thread {thread_id}): {exc}"
                        )
                        posted = False

                    if posted:
                        logger.info(f"Auto-Post Queue: Batch #{self.next_index} SUCCESS.")
                        self._mark_target_used(thread_name)
                        self._record_history_item(item, "success", thread_id, "")
                    else:
                        if not error:
                            error = "post rejected or failed"
                        logger.error(
                            f"Auto-Post Queue: Batch #{self.next_index} post rejected/failed "
                            f"for '{thread_name}' (thread {thread_id})."
                        )
                        self._record_history_item(item, "failure", thread_id, error)

                self.next_index += 1
                time.sleep(config.POST_COOLDOWN_SECONDS)
            else:
                # Wait for next post to be queued
                time.sleep(0.5)

            # Update queue status for next iteration
            with self.lock:
                queue_has_items = len(self.post_queue) > 0

        logger.info("Auto-Post Queue: Finished.")
        self.is_running = False

    def _resolve_thread_id(self, thread_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Resolve a saved posting target to a ViperGirls thread ID.

        Args:
            thread_name: Name of the thread

        Returns:
            ``(thread_id, error)`` where one value is populated.
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
        """Extract thread ID from saved thread data.

        Args:
            thread_name: Name of the thread

        Returns:
            Thread ID or None if not found
        """
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

    def reset(self) -> None:
        """Reset the poster state (for new upload session)."""
        with self.lock:
            self.post_queue.clear()
            self.next_index = 0

    def stop(self) -> None:
        """Stop the auto-poster gracefully."""
        self.is_running = False
        if self._worker_thread and self._worker_thread.is_alive():
            # Wait up to 3 seconds for the worker thread to finish
            self._worker_thread.join(timeout=3.0)
        logger.info("AutoPoster stopped")
