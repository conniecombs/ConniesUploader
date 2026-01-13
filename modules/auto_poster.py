"""Automatic posting to ViperGirls forum."""

import time
import re
import threading
from typing import Dict, Optional, Callable
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

    def queue_post(self, batch_index: int, content: str, thread_name: str) -> None:
        """Queue content for posting to a thread.

        Args:
            batch_index: Index of the batch (determines posting order)
            content: Content to post (BBCode text)
            thread_name: Name of the thread to post to
        """
        if not thread_name or thread_name == "Do Not Post":
            return

        with self.lock:
            self.post_queue[batch_index] = {"content": content, "thread": thread_name}
            logger.info(
                f"Auto-Post Queue: Queued Batch #{batch_index} for thread '{thread_name}'"
            )

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
            logger.error("Auto-Post Queue: No credentials provided")
            self.is_running = False
            return

        vg = viper_api.ViperGirlsAPI()
        if not vg.login(user, pwd):
            logger.error("Auto-Post Queue: Login Failed.")
            self.is_running = False
            return

        # Process queue until uploads finish and queue is empty
        while is_uploading_callback() or len(self.post_queue) > 0:
            if cancel_event.is_set():
                logger.info("Auto-Post Queue: Cancelled.")
                break

            # Check if next post is ready
            if self.next_index in self.post_queue:
                with self.lock:
                    item = self.post_queue.pop(self.next_index)

                content = item.get("content", "")
                thread_name = item.get("thread", "")

                # Extract thread ID from saved thread data
                thread_id = self._get_thread_id(thread_name)

                if thread_id and content:
                    logger.info(
                        f"Auto-Post Queue: Posting Batch #{self.next_index} to '{thread_name}'"
                    )

                    if vg.post_reply(thread_id, content):
                        logger.info(
                            f"Auto-Post Queue: Batch #{self.next_index} SUCCESS."
                        )
                    else:
                        logger.error(
                            f"Auto-Post Queue: Batch #{self.next_index} FAILED."
                        )

                self.next_index += 1
                time.sleep(config.POST_COOLDOWN_SECONDS)
            else:
                # Wait for next post to be queued
                time.sleep(0.5)

        logger.info("Auto-Post Queue: Finished.")
        self.is_running = False

    def _get_thread_id(self, thread_name: str) -> Optional[str]:
        """Extract thread ID from saved thread data.

        Args:
            thread_name: Name of the thread

        Returns:
            Thread ID or None if not found
        """
        if thread_name not in self.saved_threads_data:
            return None

        url = self.saved_threads_data[thread_name].get("url", "")
        if not url:
            return None

        # Try to match thread ID from URL patterns
        match = re.search(r"threads/(\d+)", url) or re.search(r"t=(\d+)", url)
        if match:
            return match.group(1)

        return None

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
