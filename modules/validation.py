# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Input validation utilities for security and data integrity."""

import os
from pathlib import Path
from typing import Optional
from loguru import logger
from modules import config


def validate_file_path(filepath: str, allowed_extensions: tuple = None) -> Optional[str]:
    """Validate and sanitize a file path.

    Args:
        filepath: The file path to validate
        allowed_extensions: Tuple of allowed file extensions (defaults to VALID_EXTENSIONS from config)

    Returns:
        Absolute path string if valid, None otherwise

    Security Notes:
        - Prevents directory traversal attacks
        - Ensures file exists and is a regular file
        - Validates file extension against centralized VALID_EXTENSIONS
    """
    # Use centralized extensions from config if not specified
    if allowed_extensions is None:
        allowed_extensions = config.VALID_EXTENSIONS
    try:
        # Resolve to absolute path and normalize
        abs_path = Path(filepath).resolve()

        # Check if file exists
        if not abs_path.exists():
            logger.warning(f"File does not exist: {filepath}")
            return None

        # Ensure it's a file, not a directory or special file
        if not abs_path.is_file():
            logger.warning(f"Path is not a regular file: {filepath}")
            return None

        # Validate extension if specified
        if allowed_extensions:
            if not abs_path.suffix.lower() in allowed_extensions:
                logger.warning(
                    f"Invalid file extension for {filepath}. Allowed: {allowed_extensions}"
                )
                return None

        # Additional security: check for suspicious patterns
        path_str = str(abs_path)
        if ".." in path_str or abs_path.name.startswith("."):
            logger.warning(f"Suspicious file path pattern: {filepath}")
            return None

        return str(abs_path)

    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error validating file path '{filepath}': {e}")
        return None


def validate_directory_path(dirpath: str) -> Optional[str]:
    """Validate and sanitize a directory path.

    Args:
        dirpath: The directory path to validate

    Returns:
        Absolute path string if valid, None otherwise
    """
    try:
        abs_path = Path(dirpath).resolve()

        if not abs_path.exists():
            logger.warning(f"Directory does not exist: {dirpath}")
            return None

        if not abs_path.is_dir():
            logger.warning(f"Path is not a directory: {dirpath}")
            return None

        # Check for suspicious patterns
        path_str = str(abs_path)
        if ".." in path_str:
            logger.warning(f"Suspicious directory path pattern: {dirpath}")
            return None

        return str(abs_path)

    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error validating directory path '{dirpath}': {e}")
        return None


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize a filename for safe filesystem operations.

    Args:
        filename: The filename to sanitize
        max_length: Maximum allowed filename length

    Returns:
        Sanitized filename
    """
    # Remove/replace dangerous characters
    dangerous_chars = '<>:"/\\|?*\x00'
    sanitized = filename

    for char in dangerous_chars:
        sanitized = sanitized.replace(char, "_")

    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip(". ")

    # Ensure not empty
    if not sanitized:
        sanitized = "unnamed_file"

    # Truncate if too long
    if len(sanitized) > max_length:
        name, ext = os.path.splitext(sanitized)
        max_name_len = max_length - len(ext)
        sanitized = name[:max_name_len] + ext

    return sanitized


def validate_service_name(service: str, plugin_manager=None) -> bool:
    """Validate that a service name is recognized.

    Args:
        service: The service name to validate
        plugin_manager: Optional PluginManager instance to get loaded plugins dynamically.
                       If not provided, uses a fallback set of known services.

    Returns:
        True if valid, False otherwise

    Note:
        This function now supports dynamic validation based on loaded plugins,
        avoiding the need to hardcode service names.
    """
    # Get valid services dynamically from plugin manager if available
    if plugin_manager is not None:
        valid_services = {plugin.service_id for plugin in plugin_manager.get_all_plugins()}
    else:
        # Fallback to hardcoded list if plugin_manager not provided
        # This ensures backward compatibility if called without plugin_manager
        valid_services = {"imx.to", "pixhost.to", "turboimagehost", "vipr.im", "imagebam.com"}
        logger.debug("Using fallback service list (no plugin_manager provided)")

    if service not in valid_services:
        logger.warning(f"Invalid service name: {service}. Valid services: {valid_services}")
        return False

    return True


def validate_thread_count(count: int, min_val: int = 1, max_val: int = 20) -> int:
    """Validate and clamp thread count to safe range.

    Args:
        count: The thread count to validate
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Clamped thread count
    """
    if count < min_val:
        logger.warning(f"Thread count {count} below minimum {min_val}, using minimum")
        return min_val
    if count > max_val:
        logger.warning(f"Thread count {count} above maximum {max_val}, using maximum")
        return max_val
    return count
