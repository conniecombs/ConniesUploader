import subprocess
import json
import threading
import queue
import os
import sys
import time
from typing import Dict, Any, Optional, List
from loguru import logger


class SidecarBridge:
    _instance: Optional["SidecarBridge"] = None
    _worker_count: int = 8  # Default worker count

    @classmethod
    def set_worker_count(cls, count: int) -> None:
        """Set the worker count before the sidecar is started."""
        cls._worker_count = max(1, min(count, 16))  # Clamp between 1 and 16

    @classmethod
    def get(cls) -> "SidecarBridge":
        if not cls._instance:
            cls._instance = SidecarBridge()
        return cls._instance

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.cmd_lock: threading.Lock = threading.Lock()
        self.restart_lock: threading.Lock = threading.Lock()
        self.restart_count: int = 0
        self.max_restarts: int = 5  # Maximum restart attempts
        self.restart_delay: int = 2  # Initial restart delay (seconds)

        # Event distribution
        self.listeners: List[queue.Queue] = []
        self.listeners_lock: threading.Lock = threading.Lock()

        self._start_process()

    def _start_process(self) -> None:
        # Determine base directory for finding uploader.exe
        if getattr(sys, "frozen", False):
            # PyInstaller mode - use _MEIPASS for temp extraction folder
            if hasattr(sys, '_MEIPASS'):
                # Running from PyInstaller bundle
                base_dir = sys._MEIPASS
            else:
                # Frozen but not PyInstaller (shouldn't happen)
                base_dir = os.path.dirname(sys.executable)
        else:
            # Development mode - go up from modules/ to project root
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        # Cross-platform binary check
        binary_name = "uploader.exe" if os.name == "nt" else "uploader"
        exe = os.path.join(base_dir, binary_name)

        # Fallback: try current working directory
        if not os.path.exists(exe):
            exe = os.path.join(os.getcwd(), binary_name)

        # Fallback: try same directory as executable
        if not os.path.exists(exe) and getattr(sys, "frozen", False):
            exe = os.path.join(os.path.dirname(sys.executable), binary_name)

        if not os.path.exists(exe):
            logger.error(f"Sidecar executable '{binary_name}' not found.")
            logger.error(f"Expected location (primary): {os.path.join(base_dir, binary_name)}")
            logger.error(f"Fallback locations checked:")
            logger.error(f"  - Current working directory: {os.path.join(os.getcwd(), binary_name)}")
            if getattr(sys, "frozen", False):
                logger.error(f"  - Executable directory (PyInstaller): {os.path.join(os.path.dirname(sys.executable), binary_name)}")
            logger.error(f"Running in PyInstaller mode: {getattr(sys, 'frozen', False)}")
            if hasattr(sys, '_MEIPASS'):
                logger.error(f"_MEIPASS: {sys._MEIPASS}")
            return

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.proc = subprocess.Popen(
                [exe, "--workers", str(self._worker_count)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # FIX: Merge stderr into stdout to prevent deadlock
                text=True,
                bufsize=1,
                startupinfo=startupinfo,
            )

            t = threading.Thread(target=self._listen, daemon=True)
            t.start()
            logger.info(f"Sidecar started: {exe} (workers: {self._worker_count})")

        except Exception as e:
            logger.error(f"Failed to start sidecar: {e}")

    def add_listener(self, q: queue.Queue) -> None:
        """Registers a queue to receive all events from the sidecar."""
        with self.listeners_lock:
            if q not in self.listeners:
                self.listeners.append(q)

    def remove_listener(self, q: queue.Queue) -> None:
        """Unregisters a queue."""
        with self.listeners_lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def _is_process_alive(self) -> bool:
        """Check if the sidecar process is still running."""
        return self.proc and self.proc.poll() is None

    def _listen(self) -> None:
        while self.proc:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    # Process terminated
                    logger.warning("Sidecar stdout closed - process may have crashed")
                    self._handle_crash()
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    self._dispatch_event(data)
                except json.JSONDecodeError:
                    # Logic to handle non-JSON lines (like pure Go logs) if they slip through
                    pass
            except Exception as e:
                logger.error(f"Sidecar read error: {e}")
                self._handle_crash()
                break

    def _handle_crash(self) -> None:
        """Handle sidecar process crash with automatic restart."""
        if not self._is_process_alive():
            exit_code = self.proc.poll() if self.proc else None
            logger.error(f"Sidecar process crashed (exit code: {exit_code})")

            # Try to restart with exponential backoff (protected by lock to prevent race conditions)
            with self.restart_lock:
                if self.restart_count < self.max_restarts:
                    delay = self.restart_delay * (2 ** self.restart_count)
                    logger.info(f"Attempting to restart sidecar in {delay}s (attempt {self.restart_count + 1}/{self.max_restarts})")
                    time.sleep(delay)

                    self.restart_count += 1
                    self.proc = None  # Clear dead process
                    self._start_process()

                    # Reset restart count on successful start
                    if self._is_process_alive():
                        logger.info("Sidecar restarted successfully")
                        self.restart_count = 0
                else:
                    logger.critical(f"Sidecar failed to restart after {self.max_restarts} attempts - giving up")
                    self.proc = None

    def _dispatch_event(self, data: Dict[str, Any]) -> None:
        # 1. Log internal messages
        if data.get("type") == "log":
            # DIAGNOSTIC: Show Go logs as INFO so they're visible in console
            logger.info(f"[GO] {data.get('msg')}")

        # DIAGNOSTIC: Log ALL events to see what's being sent
        event_type = data.get("type")
        if event_type in ["status", "result", "error"]:
            msg = data.get('msg', '')
            msg_str = f", msg={msg}" if msg and event_type == "error" else ""
            logger.info(f"[GO-EVENT] type={event_type}, file={data.get('file', 'N/A')}, status={data.get('status', 'N/A')}, url={data.get('url', 'N/A')[:50] if data.get('url') else 'N/A'}{msg_str}")

        # 2. Broadcast to all listeners
        with self.listeners_lock:
            for q in self.listeners:
                try:
                    q.put(data)
                except Exception:
                    pass

    def send_cmd(self, payload: Dict[str, Any]) -> None:
        # Check if process is alive, restart if needed
        if not self._is_process_alive():
            logger.warning("Sidecar not running, attempting restart...")
            self._start_process()

        if not self._is_process_alive():
            logger.error("Cannot send command - sidecar failed to start")
            return

        with self.cmd_lock:
            try:
                json.dump(payload, self.proc.stdin)
                self.proc.stdin.write("\n")
                self.proc.stdin.flush()
            except Exception as e:
                logger.error(f"Send error: {e}")
                # If send fails, process might be dead - trigger recovery
                self._handle_crash()

    def request_sync(self, payload: Dict[str, Any], timeout: int = 5) -> Dict[str, Any]:
        """
        Sends a command and waits for a specific response.
        Used for login/verification/scraping.
        """
        temp_q = queue.Queue(maxsize=100)
        self.add_listener(temp_q)
        self.send_cmd(payload)

        response = {"status": "error", "msg": "Timeout"}

        try:
            # Simple heuristic: wait for 'result', 'data', or 'error'
            while True:
                item = temp_q.get(timeout=timeout)
                if item.get("type") in ["result", "data", "error", "success"]:
                    response = item
                    break
        except queue.Empty:
            pass
        finally:
            self.remove_listener(temp_q)

        return response

    def shutdown(self) -> None:
        """Gracefully shutdown the sidecar process."""
        if not self.proc or not self._is_process_alive():
            logger.info("Sidecar already terminated")
            return

        logger.info("Shutting down sidecar process...")

        try:
            # Close stdin to signal the Go process to finish
            if self.proc.stdin:
                self.proc.stdin.close()

            # Wait up to 5 seconds for graceful termination
            try:
                self.proc.wait(timeout=5.0)
                logger.info("Sidecar terminated gracefully")
            except subprocess.TimeoutExpired:
                # If it doesn't terminate, force kill it
                logger.warning("Sidecar did not terminate gracefully, forcing termination")
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
                logger.info("Sidecar terminated forcefully")

        except Exception as e:
            logger.error(f"Error during sidecar shutdown: {e}")
        finally:
            self.proc = None