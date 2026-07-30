# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Input validation utilities for security and data integrity."""

import os
import re
from pathlib import Path
from typing import Optional

from loguru import logger

from modules import config


def validate_file_path(filepath: str, allowed_extensions: tuple = None) -> Optional[str]:
    """Validate and sanitize a file path."""
    if allowed_extensions is None:
        allowed_extensions = config.VALID_EXTENSIONS
    try:
        abs_path = Path(filepath).resolve()

        if not abs_path.exists():
            logger.warning(f"File does not exist: {filepath}")
            return None

        if not abs_path.is_file():
            logger.warning(f"Path is not a regular file: {filepath}")
            return None

        if allowed_extensions and abs_path.suffix.lower() not in allowed_extensions:
            logger.warning(f"Invalid file extension for {filepath}. Allowed: {allowed_extensions}")
            return None

        path_str = str(abs_path)
        if ".." in path_str or abs_path.name.startswith("."):
            logger.warning(f"Suspicious file path pattern: {filepath}")
            return None

        return str(abs_path)

    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error validating file path '{filepath}': {e}")
        return None


def validate_directory_path(dirpath: str) -> Optional[str]:
    """Validate and sanitize a directory path."""
    try:
        abs_path = Path(dirpath).resolve()

        if not abs_path.exists():
            logger.warning(f"Directory does not exist: {dirpath}")
            return None

        if not abs_path.is_dir():
            logger.warning(f"Path is not a directory: {dirpath}")
            return None

        if ".." in str(abs_path):
            logger.warning(f"Suspicious directory path pattern: {dirpath}")
            return None

        return str(abs_path)

    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error validating directory path '{dirpath}': {e}")
        return None


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize a filename for safe filesystem operations."""
    sanitized = str(filename).replace("\x00", "")
    sanitized = sanitized.replace("..", "")
    sanitized = sanitized.replace("/", "_").replace("\\", "_")
    sanitized = sanitized.replace(" ", "_")

    dangerous_chars = '<>:"|?*()[]{}'
    for char in dangerous_chars:
        sanitized = sanitized.replace(char, "_")

    sanitized = re.sub(r"_+", "_", sanitized).strip("._ ")

    if not sanitized:
        sanitized = "untitled"

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
    if sanitized.upper() in reserved_names:
        sanitized = f"file_{sanitized}"

    if len(sanitized) > max_length:
        name, ext = os.path.splitext(sanitized)
        max_name_len = max_length - len(ext)
        sanitized = name[:max_name_len] + ext

    return sanitized


def validate_service_name(service: str, plugin_manager=None) -> bool:
    """Validate that a service name is recognized."""
    service = config.normalize_service_id(service)
    if plugin_manager is not None:
        valid_services = {
            config.normalize_service_id(getattr(plugin, "service_id", getattr(plugin, "id", "")))
            for plugin in plugin_manager.get_all_plugins()
        }
    else:
        valid_services = {
            "imx.to",
            config.PIXHOST_SERVICE_ID,
            "turboimagehost",
            "vipr.im",
            "imagebam.com",
            "imgur.com",
        }
        logger.debug("Using fallback service list (no plugin_manager provided)")

    if service not in valid_services:
        logger.warning(f"Invalid service name: {service}. Valid services: {valid_services}")
        return False

    return True


def validate_thread_count(count: int, min_val: int = 1, max_val: int = 16) -> int:
    """Validate and clamp thread count to safe range."""
    try:
        count = int(count)
    except (TypeError, ValueError) as e:
        logger.warning(f"Invalid thread count {count!r}: {e}, using minimum {min_val}")
        return min_val

    if count < min_val:
        logger.warning(f"Thread count {count} below minimum {min_val}, using minimum")
        return min_val
    if count > max_val:
        logger.warning(f"Thread count {count} above maximum {max_val}, using maximum")
        return max_val
    return count
