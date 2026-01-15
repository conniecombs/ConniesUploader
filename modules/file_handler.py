"""File handling utilities for image processing and validation."""

import os
import io
import re
import base64
from typing import List, Optional, Union
from PIL import Image
from loguru import logger
from modules.sidecar import SidecarBridge
from modules import config
from modules.exceptions import InvalidFileException

# Import centralized extension validation from config
VALID_EXTENSIONS = config.VALID_EXTENSIONS


def validate_file_size(file_path: str, max_size: int = None) -> bool:
    """Validate that a file is not too large.

    Args:
        file_path: Path to the file to check
        max_size: Maximum file size in bytes (defaults to config.MAX_FILE_SIZE)

    Returns:
        True if file size is valid

    Raises:
        InvalidFileException: If file exceeds maximum size
    """
    if max_size is None:
        max_size = config.MAX_FILE_SIZE

    try:
        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            max_size_mb = max_size / (1024 * 1024)
            file_size_mb = file_size / (1024 * 1024)
            raise InvalidFileException(
                f"File '{os.path.basename(file_path)}' is too large "
                f"({file_size_mb:.1f}MB). Maximum allowed size is {max_size_mb:.1f}MB."
            )
        return True
    except OSError as e:
        logger.warning(f"Could not check file size for {file_path}: {e}")
        return True  # Allow the file if we can't check its size


def scan_inputs(inputs: Union[str, List[str]], validate_size: bool = True) -> List[str]:
    """Scan inputs (files or folders) and return valid image paths.

    Args:
        inputs: Single file/folder path or list of paths
        validate_size: Whether to validate file sizes (defaults to True)

    Returns:
        Sorted list of unique valid image file paths

    Raises:
        InvalidFileException: If any file exceeds the maximum size limit
    """
    media_files: List[str] = []

    if isinstance(inputs, str):
        inputs = [inputs]
    if not inputs:
        return []

    for item in inputs:
        if os.path.isfile(item):
            if item.lower().endswith(VALID_EXTENSIONS):
                # Validate file size if requested
                if validate_size:
                    validate_file_size(item)
                media_files.append(item)
        elif os.path.isdir(item):
            media_files.extend(get_files_from_directory(item, validate_size=validate_size))

    return sorted(list(set(media_files)))


def get_files_from_directory(directory: str, validate_size: bool = True) -> List[str]:
    """Recursively get all valid image files from a directory.

    Args:
        directory: Path to directory to scan
        validate_size: Whether to validate file sizes (defaults to True)

    Returns:
        List of valid image file paths

    Raises:
        InvalidFileException: If any file exceeds the maximum size limit
    """
    files: List[str] = []
    try:
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                if filename.lower().endswith(VALID_EXTENSIONS):
                    file_path = os.path.join(root, filename)
                    # Validate file size if requested
                    if validate_size:
                        validate_file_size(file_path)
                    files.append(file_path)
    except OSError as e:
        logger.error(f"Error scanning directory: {e}")
    return files


def generate_thumbnail(file_path: str) -> Optional[Image.Image]:
    """Generate thumbnail using the Go sidecar process.

    Args:
        file_path: Path to image file

    Returns:
        PIL Image object if successful, None otherwise
    """
    payload = {"action": "generate_thumb", "files": [file_path], "config": {"width": "100"}}

    bridge = SidecarBridge.get()
    resp = bridge.request_sync(payload, timeout=2)

    if resp.get("status") == "success" and resp.get("data"):
        try:
            image_data = base64.b64decode(resp["data"])
            return Image.open(io.BytesIO(image_data))
        except Exception as e:
            logger.warning(f"Thumbnail decode error for {file_path}: {e}")
            return None
    return None


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize a filename to prevent security issues and filesystem errors.

    Args:
        filename: The filename to sanitize
        max_length: Maximum allowed length for the filename

    Returns:
        A safe filename string

    Note:
        - Removes NUL bytes and control characters
        - Removes path traversal sequences (.., ./)
        - Replaces invalid filesystem characters with underscores
        - Handles Windows reserved names (CON, PRN, AUX, etc.)
        - Collapses multiple spaces/underscores
        - Ensures result is not empty
    """
    # Remove NUL bytes and control characters
    filename = "".join(c for c in filename if c >= " " and c != "\x00")

    # Remove path traversal attempts
    filename = filename.replace("..", "").replace("./", "").replace(".\\", "")

    # Keep only safe characters: alphanumeric, spaces, hyphens, underscores
    filename = "".join(c if (c.isalnum() or c in (" ", "_", "-")) else "_" for c in filename)

    # Collapse multiple spaces and underscores
    filename = re.sub(r"[ _]+", "_", filename)

    # Remove leading/trailing underscores and spaces
    filename = filename.strip("_ ")

    # Handle Windows reserved names
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }
    if filename.upper() in reserved_names:
        filename = f"file_{filename}"

    # Ensure not empty
    if not filename:
        filename = "untitled"

    # Truncate to max length
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip("_ ")

    return filename
