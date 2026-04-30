# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Thread-safe bridge for the Go upload sidecar process.

The bridge owns sidecar startup, shutdown, event fan-out, and synchronous
request helpers used by GUI code. It is intentionally defensive because it sits
between UI threads and a long-running subprocess.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from . import config

JsonDict = Dict[str, Any]


class SidecarBridge:
    """Singleton process bridge for the Go sidecar."""

    _instance: Optional["SidecarBridge"] = None
    _instance_lock = threading.Lock()
    _worker_count: int = 8
    _min_workers: int = 1
    _max_workers: int = 16

    @classmethod
    def set_worker_count(cls, count: int) -> None:
        """Set the worker count and restart the sidecar if already running."""
        try:
            requested_count = int(count)
        except (TypeError, ValueError):
            logger.warning(f"Invalid worker count {count!r}; keeping {cls._worker_count}")
            return

        new_count = max(cls._min_workers, min(requested_count, cls._max_workers))
        if new_count == cls._worker_count:
            return

        cls._worker_count = new_count
        instance = cls._instance
        if instance and instance.is_process_alive():
            logger.info(f"Worker count changed to {new_count}; restarting sidecar")
            instance.restart_for_config_change()

    @classmethod
    def get(cls) -> "SidecarBridge":
        """Return the process bridge singleton."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen[str]] = None
        self.cmd_lock = threading.RLock()
        self.restart_lock = threading.RLock()
        self.listeners: List[queue.Queue[JsonDict]] = []
        self.listeners_lock = threading.RLock()
        self.restart_count = 0
        self.max_restarts = int(config.SIDECAR_MAX_RESTARTS)
        self.restart_delay = float(config.SIDECAR_RESTART_DELAY_SECONDS)
        self._shutdown_requested = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None

        self._start_process()

    def _resolve_executable(self) -> Optional[Path]:
        """Find the bundled or development sidecar executable."""
        binary_name = "uploader.exe" if os.name == "nt" else "uploader"
        candidates: List[Path] = []

        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / binary_name)
            candidates.append(Path(sys.executable).resolve().parent / binary_name)
        else:
            candidates.append(Path(__file__).resolve().parents[1] / binary_name)

        candidates.append(Path.cwd() / binary_name)

        for candidate in candidates:
            if candidate.is_file():
                return candidate

        logger.error(f"Sidecar executable '{binary_name}' was not found")
        for index, candidate in enumerate(candidates, start=1):
            logger.error(f"Search path {index}: {candidate}")
        return None

    def _start_process(self) -> bool:
        """Start the sidecar process if it is not already alive."""
        if self._shutdown_requested.is_set():
            logger.debug("Skipping sidecar start because shutdown was requested")
            return False

        with self.restart_lock:
            if self.is_process_alive():
                return True

            exe = self._resolve_executable()
            if exe is None:
                return False

            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            try:
                self.proc = subprocess.Popen(
                    [str(exe), "--workers", str(self._worker_count)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    startupinfo=startupinfo,
                )
            except OSError as exc:
                logger.exception(f"Failed to start sidecar: {exc}")
                self.proc = None
                return False

            self._listener_thread = threading.Thread(
                target=self._listen,
                name="SidecarListener",
                daemon=True,
            )
            self._listener_thread.start()
            logger.info(f"Sidecar started: {exe} (workers: {self._worker_count})")
            return True

    def add_listener(self, q: queue.Queue[JsonDict]) -> None:
        """Register a queue to receive sidecar events."""
        with self.listeners_lock:
            if q not in self.listeners:
                self.listeners.append(q)

    def remove_listener(self, q: queue.Queue[JsonDict]) -> None:
        """Unregister a sidecar event queue."""
        with self.listeners_lock:
            try:
                self.listeners.remove(q)
            except ValueError:
                pass

    def is_process_alive(self) -> bool:
        """Return True when the sidecar process exists and is running."""
        return self.proc is not None and self.proc.poll() is None

    def _is_process_alive(self) -> bool:
        """Backward-compatible alias for older callers."""
        return self.is_process_alive()

    def _listen(self) -> None:
        """Read stdout from the sidecar and dispatch JSON events."""
        proc = self.proc
        if proc is None or proc.stdout is None:
            return

        while not self._shutdown_requested.is_set():
            try:
                line = proc.stdout.readline()
            except OSError as exc:
                logger.error(f"Sidecar stdout read failed: {exc}")
                self._handle_crash()
                return

            if line == "":
                if not self._shutdown_requested.is_set():
                    logger.warning("Sidecar stdout closed unexpectedly")
                    self._handle_crash()
                return

            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"[GO-RAW] {line}")
                continue

            if not isinstance(data, dict):
                logger.warning(f"Ignoring non-object sidecar event: {data!r}")
                continue

            self._dispatch_event(data)

    def _handle_crash(self) -> None:
        """Handle sidecar crashes with bounded exponential-backoff restarts."""
        if self._shutdown_requested.is_set():
            return

        with self.restart_lock:
            if self.is_process_alive():
                return

            exit_code = self.proc.poll() if self.proc else None
            logger.error(f"Sidecar process exited unexpectedly (exit code: {exit_code})")

            if self.restart_count >= self.max_restarts:
                logger.critical(
                    f"Sidecar failed to restart after {self.max_restarts} attempts; giving up"
                )
                self.proc = None
                return

            delay = self.restart_delay * (2**self.restart_count)
            self.restart_count += 1
            logger.info(
                f"Attempting sidecar restart in {delay:.1f}s "
                f"(attempt {self.restart_count}/{self.max_restarts})"
            )
            time.sleep(delay)

            self.proc = None
            if self._start_process():
                logger.info("Sidecar restarted successfully")
                self.restart_count = 0

    def _dispatch_event(self, data: JsonDict) -> None:
        """Broadcast an event to listeners without blocking the stdout reader."""
        event_type = data.get("type")
        if event_type == "log":
            logger.info(f"[GO] {data.get('msg', '')}")
        elif event_type in {"status", "result", "error", "data", "batch_complete"}:
            logger.debug(
                f"[GO-EVENT] type={event_type}, "
                f"file={data.get('file') or data.get('file_path') or 'N/A'}, "
                f"status={data.get('status', 'N/A')}"
            )

        with self.listeners_lock:
            listeners = list(self.listeners)

        stale_listeners: List[queue.Queue[JsonDict]] = []
        for listener in listeners:
            try:
                listener.put_nowait(data)
            except queue.Full:
                logger.warning("Dropping sidecar event because a listener queue is full")
            except Exception as exc:
                logger.warning(f"Removing failed sidecar listener: {exc}")
                stale_listeners.append(listener)

        if stale_listeners:
            with self.listeners_lock:
                for listener in stale_listeners:
                    try:
                        self.listeners.remove(listener)
                    except ValueError:
                        pass

    def send_cmd(self, payload: JsonDict) -> bool:
        """Send a JSON command to the sidecar."""
        if not self.is_process_alive():
            logger.warning("Sidecar is not running; attempting restart")
            self._start_process()

        if not self.is_process_alive() or self.proc is None or self.proc.stdin is None:
            logger.error("Cannot send command; sidecar is unavailable")
            return False

        with self.cmd_lock:
            try:
                json.dump(payload, self.proc.stdin)
                self.proc.stdin.write("\n")
                self.proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError) as exc:
                logger.error(f"Send error: {exc}")
                self._handle_crash()
                return False

    def request_sync(self, payload: JsonDict, timeout: float = 5.0) -> JsonDict:
        """Send a command and wait for a correlated terminal response."""
        request_id = str(payload.get("id") or uuid.uuid4())
        payload = dict(payload)
        payload["id"] = request_id

        temp_q: queue.Queue[JsonDict] = queue.Queue(maxsize=100)
        self.add_listener(temp_q)

        try:
            if not self.send_cmd(payload):
                return {
                    "id": request_id,
                    "type": "error",
                    "status": "error",
                    "msg": "Sidecar unavailable",
                }

            deadline = time.monotonic() + timeout
            terminal_types = {"result", "data", "error", "success"}
            while time.monotonic() < deadline:
                try:
                    item = temp_q.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    break

                if item.get("id") == request_id:
                    return item

                # Compatibility with older sidecar responses that do not echo ids.
                if "id" not in item and item.get("type") in terminal_types:
                    return item

            return {
                "id": request_id,
                "type": "error",
                "status": "error",
                "msg": "Timeout waiting for sidecar response",
            }
        finally:
            self.remove_listener(temp_q)

    def restart_for_config_change(self) -> bool:
        """Restart the sidecar process to apply configuration changes."""
        logger.info("Restarting sidecar for configuration change")
        with self.restart_lock:
            self._terminate_process(grace_period=2.0)
            self.proc = None
            return self._start_process()

    def _restart_for_config_change(self) -> None:
        """Backward-compatible alias for older callers."""
        self.restart_for_config_change()

    def _terminate_process(self, grace_period: float = 5.0) -> None:
        """Terminate the current process gracefully, then forcefully if needed."""
        proc = self.proc
        if proc is None:
            return

        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass

        try:
            proc.wait(timeout=grace_period)
            logger.info("Sidecar terminated gracefully")
            return
        except subprocess.TimeoutExpired:
            logger.warning("Sidecar did not terminate gracefully; terminating")

        try:
            proc.terminate()
            proc.wait(timeout=2.0)
            logger.info("Sidecar terminated")
            return
        except subprocess.TimeoutExpired:
            logger.warning("Sidecar did not terminate; killing")
        except OSError as exc:
            logger.warning(f"Error terminating sidecar: {exc}")
            return

        try:
            proc.kill()
            proc.wait(timeout=2.0)
            logger.info("Sidecar killed")
        except OSError as exc:
            logger.error(f"Failed to kill sidecar: {exc}")

    def shutdown(self) -> None:
        """Gracefully shut down the sidecar process."""
        self._shutdown_requested.set()
        if not self.is_process_alive():
            logger.info("Sidecar already terminated")
            self.proc = None
            return

        logger.info("Shutting down sidecar process")
        self._terminate_process(grace_period=5.0)
        self.proc = None
