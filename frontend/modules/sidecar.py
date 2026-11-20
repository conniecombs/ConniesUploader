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

# Event sent to listeners when a sidecar process exits without a shutdown
# request. Jobs written to that process (its "generation") are lost.
SIDECAR_CRASHED_EVENT = "sidecar_crashed"
PROCESS_RESTARTED_MSG = "Uploader process restarted; upload interrupted"
# Events a listener must receive (see SidecarBridge._dispatch_event).
TERMINAL_STATUSES = frozenset({"Done", "Failed", "Cancelled"})
TERMINAL_EVENT_TYPES = frozenset(
    {"result", "error", "batch_complete", SIDECAR_CRASHED_EVENT, "sidecar_stopped"}
)


class SidecarBridge:
    """Singleton process bridge for the Go sidecar."""

    _instance: Optional["SidecarBridge"] = None
    _instance_lock = threading.Lock()
    _worker_count: int = 8
    _min_workers: int = 1
    _max_workers: int = 16
    # Number of sidecar processes started so far; each process is identified
    # by the generation it was started with.
    generation: int = 0

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

    @staticmethod
    def _binary_names() -> List[str]:
        if os.name != "nt":
            return ["uploader"]
        return ["uploader.exe", "uploader"]

    def _resolve_executable(self) -> Optional[Path]:
        """Find the bundled or development sidecar executable."""
        binary_names = self._binary_names()
        candidates: List[Path] = []

        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.extend(Path(meipass) / name for name in binary_names)
            candidates.extend(Path(sys.executable).resolve().parent / name for name in binary_names)
        else:
            candidates.extend(Path(__file__).resolve().parents[2] / name for name in binary_names)

        candidates.extend(Path.cwd() / name for name in binary_names)

        unique_candidates: List[Path] = []
        seen_candidates = set()
        for candidate in candidates:
            if candidate in seen_candidates:
                continue
            seen_candidates.add(candidate)
            unique_candidates.append(candidate)

        for candidate in unique_candidates:
            if candidate.is_file():
                return candidate

        logger.error(f"Sidecar executable '{binary_names[0]}' was not found")
        for index, candidate in enumerate(unique_candidates, start=1):
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

            self.generation += 1
            self._listener_thread = threading.Thread(
                target=self._listen,
                args=(self.proc, self.generation),
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

    def _listen(self, proc: Any = None, generation: Optional[int] = None) -> None:
        """Read stdout from one sidecar process and dispatch JSON events."""
        if proc is None:
            proc = self.proc
        if generation is None:
            generation = self.generation
        if proc is None or proc.stdout is None:
            return

        while not self._shutdown_requested.is_set():
            try:
                line = proc.stdout.readline()
            except OSError as exc:
                logger.error(f"Sidecar stdout read failed: {exc}")
                self._process_exited(generation)
                return

            if line == "":
                if not self._shutdown_requested.is_set():
                    logger.warning("Sidecar stdout closed unexpectedly")
                    self._process_exited(generation)
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

    def _process_exited(self, generation: int) -> None:
        """Tell listeners a process died, then restart it.

        Every job written to that process is lost, whether or not a restart
        follows, so listeners hear about it first and can end those jobs.
        """
        if self._shutdown_requested.is_set():
            return
        self._dispatch_event(
            {
                "type": SIDECAR_CRASHED_EVENT,
                "generation": generation,
                "msg": PROCESS_RESTARTED_MSG,
            }
        )
        self._handle_crash()

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
                self._dispatch_event({"type": "sidecar_stopped", "msg": "Sidecar crash exhaustion"})
                self.proc = None
                return

            delay = self.restart_delay * (2**self.restart_count)
            self.restart_count += 1
            self.proc = None
            logger.info(
                f"Attempting sidecar restart in {delay:.1f}s "
                f"(attempt {self.restart_count}/{self.max_restarts})"
            )

        # Back off without holding restart_lock: send_cmd callers would
        # otherwise block for the whole delay instead of failing fast.
        time.sleep(delay)

        with self.restart_lock:
            if self.is_process_alive():
                return
            if self._start_process():
                logger.info("Sidecar restarted successfully")
                self.restart_count = 0

    @staticmethod
    def _is_terminal_event(data: JsonDict) -> bool:
        """Whether a listener must receive this event: it ends a file, job or process."""
        event_type = data.get("type")
        if event_type == "status":
            return data.get("status") in TERMINAL_STATUSES
        return event_type in TERMINAL_EVENT_TYPES

    def _put_until_delivered(self, listener: queue.Queue[JsonDict], data: JsonDict) -> None:
        """Wait for room in a full listener queue instead of dropping the event.

        Gives up only when the listener is removed or the bridge shuts down,
        since nobody would read the event then.
        """
        waited = False
        while True:
            try:
                listener.put(data, timeout=1.0)
                return
            except queue.Full:
                pass
            with self.listeners_lock:
                registered = listener in self.listeners
            if not registered or self._shutdown_requested.is_set():
                logger.warning("Dropping a sidecar event for a listener that is gone")
                return
            if not waited:
                waited = True
                logger.warning("A sidecar listener queue is full; waiting to deliver an event")

    def _dispatch_event(self, data: JsonDict) -> None:
        """Broadcast an event to listeners.

        Progress events are dropped when a listener's queue is full. Terminal
        events (a file's result, error, Done/Failed/Cancelled status, a job's
        batch_complete, and process crash/stop notices) are never dropped:
        the stdout reader waits for room instead.
        """
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

        must_deliver = self._is_terminal_event(data)
        stale_listeners: List[queue.Queue[JsonDict]] = []
        for listener in listeners:
            try:
                if must_deliver:
                    self._put_until_delivered(listener, data)
                else:
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
        return self.send_job(payload) is not None

    def send_job(self, payload: JsonDict) -> Optional[int]:
        """Send a JSON command; return the generation of the process it reached.

        Returns None when the command could not be written. A caller that
        tracks long-running jobs compares the generation with the one in a
        ``sidecar_crashed`` event to know whether its job was lost.
        """
        if not self.is_process_alive():
            logger.warning("Sidecar is not running; attempting restart")
            self._start_process()

        with self.restart_lock:
            proc = self.proc
            generation = self.generation
        if proc is None or proc.poll() is not None or proc.stdin is None:
            logger.error("Cannot send command; sidecar is unavailable")
            return None

        with self.cmd_lock:
            try:
                json.dump(payload, proc.stdin)
                proc.stdin.write("\n")
                proc.stdin.flush()
                return generation
            except (BrokenPipeError, OSError, ValueError) as exc:
                logger.error(f"Send error: {exc}")
        # Restart off this thread and without cmd_lock: the restart backs off
        # for seconds, and other senders (Stop's cancel on the Tk thread
        # among them) must fail fast meanwhile, not wait for it.
        threading.Thread(target=self._handle_crash, name="SidecarRestart", daemon=True).start()
        return None

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
            while time.monotonic() < deadline:
                try:
                    item = temp_q.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    break

                if item.get("id") == request_id:
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
