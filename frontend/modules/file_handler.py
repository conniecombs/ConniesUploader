# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""File handling utilities for image processing and validation."""

from __future__ import annotations

import base64
import io
import os
import re
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image
from loguru import logger

from modules import config
from modules.exceptions import InvalidFileException
from modules.sidecar import SidecarBridge

VALID_EXTENSIONS = config.VALID_EXTENSIONS
MAX_SCAN_FILES = getattr(config, "MAX_SCAN_FILES", 1000)


def validate_file_extension(file_path: str) -> bool:
    """Validate that a file has a supported image extension."""
    filename = os.path.basename(file_path)
    if not filename.lower().endswith(VALID_EXTENSIONS):
        supported = ", ".join(VALID_EXTENSIONS)
        raise InvalidFileException(
            f"File '{filename}' has an unsupported format. Supported formats: {supported}"
        )
    return True


def validate_regular_file(file_path: str) -> bool:
    """Validate that a path points to a regular, non-symlink file."""
    path = Path(file_path)
    try:
        if path.is_symlink():
            raise InvalidFileException(f"File '{path.name}' is a symlink and is not allowed.")
        if not path.is_file():
            raise InvalidFileException(f"Path '{path}' is not a regular file.")
    except OSError as exc:
        raise InvalidFileException(f"Could not validate file '{path}': {exc}") from exc
    return True


def validate_file_size(file_path: str, max_size: int = None) -> bool:
    """Validate that a file is not too large.

    This intentionally fails closed when file metadata cannot be read. Allowing
    files through after an OSError can admit broken paths, special files, or
    permission-protected files into later image processing/upload code.
    """
    if max_size is None:
        max_size = config.MAX_FILE_SIZE

    validate_regular_file(file_path)

    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        raise InvalidFileException(
            f"Could not check file size for '{os.path.basename(file_path)}': {exc}"
        ) from exc

    if file_size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        file_size_mb = file_size / (1024 * 1024)
        raise InvalidFileException(
            f"File '{os.path.basename(file_path)}' is too large "
            f"({file_size_mb:.1f}MB). Maximum allowed size is {max_size_mb:.1f}MB."
        )
    return True


def _append_valid_file(media_files: List[str], file_path: str, validate_size: bool) -> None:
    """Validate and append a file path to the media list."""
    validate_file_extension(file_path)
    validate_regular_file(file_path)
    if validate_size:
        validate_file_size(file_path)
    media_files.append(os.path.abspath(file_path))


def scan_inputs(inputs: Union[str, List[str]], validate_size: bool = True) -> List[str]:
    """Scan inputs (files or folders) and return valid image paths."""
    media_files: List[str] = []

    if isinstance(inputs, str):
        inputs = [inputs]
    if not inputs:
        return []

    for item in inputs:
        if len(media_files) >= MAX_SCAN_FILES:
            raise InvalidFileException(
                f"Too many files selected. Maximum allowed per batch is {MAX_SCAN_FILES}."
            )

        if os.path.isfile(item):
            if item.lower().endswith(VALID_EXTENSIONS):
                _append_valid_file(media_files, item, validate_size)
        elif os.path.isdir(item):
            media_files.extend(get_files_from_directory(item, validate_size=validate_size))
        else:
            logger.warning(f"Skipping inaccessible path: {item}")

    unique_files = sorted(set(media_files))
    if len(unique_files) > MAX_SCAN_FILES:
        raise InvalidFileException(
            f"Too many files selected. Maximum allowed per batch is {MAX_SCAN_FILES}."
        )
    return unique_files


def get_files_from_directory(directory: str, validate_size: bool = True) -> List[str]:
    """Recursively get all valid image files from a directory.

    Symlinked directories are not followed to avoid recursive loops and escaping
    the selected tree. Symlinked files are rejected by validate_regular_file().
    """
    files: List[str] = []
    base_dir = Path(directory).resolve()

    if not base_dir.is_dir():
        logger.warning(f"Skipping non-directory path: {directory}")
        return files

    try:
        for root, dirs, filenames in os.walk(base_dir, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]

            for filename in filenames:
                if len(files) >= MAX_SCAN_FILES:
                    raise InvalidFileException(
                        f"Too many files found. Maximum allowed per batch is {MAX_SCAN_FILES}."
                    )

                if not filename.lower().endswith(VALID_EXTENSIONS):
                    continue

                file_path = Path(root) / filename
                try:
                    resolved = file_path.resolve()
                    if not resolved.is_relative_to(base_dir):
                        logger.warning(f"Skipping path outside selected directory: {file_path}")
                        continue
                    _append_valid_file(files, str(resolved), validate_size)
                except InvalidFileException:
                    raise
                except OSError as exc:
                    logger.warning(f"Skipping unreadable file {file_path}: {exc}")
    except OSError as exc:
        raise InvalidFileException(f"Error scanning directory '{directory}': {exc}") from exc

    return files


def generate_thumbnail(file_path: str) -> Optional[Image.Image]:
    """Generate thumbnail using the Go sidecar process."""
    try:
        validate_file_extension(file_path)
        validate_regular_file(file_path)
    except InvalidFileException as exc:
        logger.warning(f"Thumbnail validation failed for {file_path}: {exc}")
        return None

    payload = {"action": "generate_thumb", "files": [file_path], "config": {"width": "100"}}

    bridge = SidecarBridge.get()
    resp = bridge.request_sync(payload, timeout=2)

    if resp.get("status") == "success" and resp.get("data"):
        try:
            image_data = base64.b64decode(resp["data"])
            return Image.open(io.BytesIO(image_data))
        except Exception as exc:
            logger.warning(f"Thumbnail decode error for {file_path}: {exc}")
            return None
    return None


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize a filename to prevent security issues and filesystem errors."""
    filename = "".join(c for c in filename if c >= " " and c != "\x00")
    filename = filename.replace("..", "").replace("./", "").replace(".\\", "")
    filename = "".join(c if (c.isalnum() or c in (" ", "_", "-")) else "_" for c in filename)
    filename = re.sub(r"[ _]+", "_", filename)
    filename = filename.strip("_ ")

    reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    if filename.upper() in reserved_names:
        filename = f"file_{filename}"

    if not filename:
        filename = "untitled"

    if len(filename) > max_length:
        filename = filename[:max_length].rstrip("_ ")

    return filename
