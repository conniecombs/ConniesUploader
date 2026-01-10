import subprocess
import json
import threading
import queue
import os
import sys
import time
from loguru import logger


class SidecarBridge:
    _instance = None

    @classmethod
    def get(cls):
        if not cls._instance:
            cls._instance = SidecarBridge()
        return cls._instance

    def __init__(self):
        self.proc = None
        self.cmd_lock = threading.Lock()
        self.restart_lock = threading.Lock()
        self.restart_count = 0
        self.max_restarts = 5  # Maximum restart attempts
        self.restart_delay = 2  # Initial restart delay (seconds)

        # Event distribution
        self.listeners = []
        self.listeners_lock = threading.Lock()

        self._start_process()

    def _start_process(self):
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
            logger.error(f"Sidecar executable not found. Tried:")
            logger.error(f"  1. {os.path.join(base_dir, binary_name)}")
            logger.error(f"  2. {os.path.join(os.getcwd(), binary_name)}")
            if getattr(sys, "frozen", False):
                logger.error(f"  3. {os.path.join(os.path.dirname(sys.executable), binary_name)}")
            logger.error(f"PyInstaller mode: {getattr(sys, 'frozen', False)}")
            if hasattr(sys, '_MEIPASS'):
                logger.error(f"_MEIPASS: {sys._MEIPASS}")
            return

        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.proc = subprocess.Popen(
                [exe],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # FIX: Merge stderr into stdout to prevent deadlock
                text=True,
                bufsize=1,
                startupinfo=startupinfo,
            )

            t = threading.Thread(target=self._listen, daemon=True)
            t.start()
            logger.info(f"Sidecar started: {exe}")

        except Exception as e:
            logger.error(f"Failed to start sidecar: {e}")

    def add_listener(self, q):
        """Registers a queue to receive all events from the sidecar."""
        with self.listeners_lock:
            if q not in self.listeners:
                self.listeners.append(q)

    def remove_listener(self, q):
        """Unregisters a queue."""
        with self.listeners_lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def _is_process_alive(self):
        """Check if the sidecar process is still running."""
        return self.proc and self.proc.poll() is None

    def _listen(self):
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

    def _handle_crash(self):
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

    def _dispatch_event(self, data):
        # 1. Log internal messages
        if data.get("type") == "log":
            # DIAGNOSTIC: Show Go logs as INFO so they're visible in console
            logger.info(f"[GO] {data.get('msg')}")

        # DIAGNOSTIC: Log ALL events to see what's being sent
        event_type = data.get("type")
        if event_type in ["status", "result", "error"]:
            logger.info(f"[GO-EVENT] type={event_type}, file={data.get('file', 'N/A')}, status={data.get('status', 'N/A')}, url={data.get('url', 'N/A')[:50] if data.get('url') else 'N/A'}")

        # 2. Broadcast to all listeners
        with self.listeners_lock:
            for q in self.listeners:
                try:
                    q.put(data)
                except Exception:
                    pass

    def send_cmd(self, payload):
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

    def request_sync(self, payload, timeout=5):
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