# modules/config.py
import sys
import re
from loguru import logger
import os

# --- Version ---
APP_VERSION = "1.2.1"
USER_AGENT = f"ConniesUploader/{APP_VERSION}"

# --- Constants ---
IMX_URL = "https://api.imx.to/v1/upload.php"
PIX_URL = "https://api.pixhost.to/images"
PIX_COVERS_URL = "https://api.pixhost.to/covers"
PIX_GALLERIES_URL = "https://api.pixhost.to/galleries"
IMX_LOGIN_URL = "https://imx.to/login.php"
IMX_DASHBOARD_URL = "https://imx.to/user/dashboard"
IMX_GALLERY_ADD_URL = "https://imx.to/user/gallery/add"
IMX_GALLERY_EDIT_URL = "https://imx.to/user/gallery/edit"

# TURBO Constants
TURBO_HOME_URL = "https://www.turboimagehost.com/"
TURBO_LOGIN_URL = "https://www.turboimagehost.com/login.tu"

# VIPR Constants
VIPR_HOME_URL = "https://vipr.im/"
VIPR_LOGIN_URL = "https://vipr.im/"
VIPR_AJAX_URL = "https://vipr.im/"

# IMAGEBAM Constants
IMAGEBAM_HOME_URL = "https://www.imagebam.com/"
IMAGEBAM_LOGIN_URL = "https://www.imagebam.com/auth/login"
IMAGEBAM_SESSION_URL = "https://www.imagebam.com/upload/session"
IMAGEBAM_UPLOAD_URL = "https://www.imagebam.com/upload"
IMAGEBAM_GALLERIES_URL = "https://www.imagebam.com/my/galleries"

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
# Alias for backward compatibility - centralized extension validation
VALID_EXTENSIONS = SUPPORTED_EXTENSIONS
SETTINGS_FILE = "user_settings.json"
CRASH_LOG_FILE = "crash_log.log"
UI_THUMB_SIZE = (40, 40)

# Upload Configuration
DEFAULT_THREAD_COUNT = 5
MIN_THREAD_COUNT = 1
MAX_THREAD_COUNT = 20
DEFAULT_UPLOAD_TIMEOUT = 120  # seconds

# Thread Pool Configuration
THUMBNAIL_WORKERS = 4
GO_WORKER_POOL_SIZE = 8

# Auto-Post Configuration
POST_COOLDOWN_SECONDS = 1.5

# Sidecar Configuration
SIDECAR_RESTART_DELAY_SECONDS = 2  # Initial restart delay before exponential backoff
SIDECAR_MAX_RESTARTS = 5  # Maximum restart attempts before giving up

# File Size Limits (in bytes)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_FILENAME_LENGTH = 255

# UI Update Intervals
UI_UPDATE_INTERVAL_MS = 10
UI_QUEUE_BATCH_SIZE = 10
PROGRESS_UPDATE_BATCH_SIZE = 50
UI_CLEANUP_INTERVAL_MS = 30000  # 30 seconds - cleanup orphaned images
UI_DROP_TARGET_DELAY_MS = 100  # Delay before registering drop targets after widget creation
UI_GALLERY_REFRESH_DELAY_MS = 200  # Gallery manager refresh delay

# Keyring Services
KEYRING_SERVICE_API = "ImageUploader:imx_api_key"
KEYRING_SERVICE_USER = "ImageUploader:imx_username"
KEYRING_SERVICE_PASS = "ImageUploader:imx_password"
KEYRING_SERVICE_VIPR_USER = "ImageUploader:vipr_username"
KEYRING_SERVICE_VIPR_PASS = "ImageUploader:vipr_password"
KEYRING_SERVICE_IB_USER = "ImageUploader:imagebam_username"
KEYRING_SERVICE_IB_PASS = "ImageUploader:imagebam_password"
# NEW: ViperGirls Forum Credentials
KEYRING_SERVICE_VG_USER = "ImageUploader:vipergirls_username"
KEYRING_SERVICE_VG_PASS = "ImageUploader:vipergirls_password"

# --- Logging Setup ---
logger.remove()
# Only log to stderr if it exists (fixes EXE crash)
if sys.stderr:
    logger.add(sys.stderr, level="INFO")
logger.add(CRASH_LOG_FILE, rotation="1 MB", retention="10 days", level="DEBUG", backtrace=True, diagnose=True)


def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
