# modules/plugins/helpers.py
"""
Plugin helper utilities - Common patterns extracted for reuse.

This module contains helper functions for common plugin operations:
- Configuration validation
- Upload context management
- Cover image detection
- Progress callbacks
- Error handling

Used across all plugins to reduce code duplication and ensure consistency.
"""

from typing import Dict, Any, List, Callable, Optional, Tuple
from loguru import logger


# ============================================================================
# Validation Helpers
# ============================================================================


def validate_cover_count(config: Dict[str, Any], errors: List[str]) -> None:
    """
    Validate and convert cover_count to integer.

    Converts config["cover_count"] to config["cover_limit"] as integer.
    Adds error to errors list if conversion fails.

    Args:
        config: Plugin configuration dictionary (modified in-place)
        errors: List of error messages (appended to if validation fails)

    Example:
        >>> config = {"cover_count": "5"}
        >>> errors = []
        >>> validate_cover_count(config, errors)
        >>> config["cover_limit"]
        5
    """
    try:
        cover_count = config.get("cover_count", 0)
        config["cover_limit"] = int(cover_count)
    except (ValueError, TypeError):
        errors.append("Cover count must be a valid number")


def validate_gallery_id(
    gallery_id: str, errors: List[str], alphanumeric: bool = True
) -> None:
    """
    Validate gallery ID format.

    Args:
        gallery_id: Gallery identifier to validate
        errors: List of error messages (appended to if validation fails)
        alphanumeric: If True, require only letters and numbers

    Example:
        >>> errors = []
        >>> validate_gallery_id("abc123", errors, alphanumeric=True)
        >>> len(errors)
        0
        >>> validate_gallery_id("abc-123", errors, alphanumeric=True)
        >>> len(errors)
        1
    """
    if gallery_id:
        if alphanumeric and not gallery_id.isalnum():
            errors.append("Gallery ID must contain only letters and numbers")


def validate_credentials(creds: Dict[str, Any], required_keys: List[str]) -> List[str]:
    """
    Validate that required credentials are present.

    Args:
        creds: Credentials dictionary
        required_keys: List of required credential keys

    Returns:
        List of error messages (empty if all required keys present)

    Example:
        >>> creds = {"api_key": "abc123"}
        >>> validate_credentials(creds, ["api_key"])
        []
        >>> validate_credentials(creds, ["api_key", "secret"])
        ['Missing required credential: secret']
    """
    errors = []
    for key in required_keys:
        if not creds.get(key):
            errors.append(f"Missing required credential: {key}")
    return errors


# ============================================================================
# Upload Context Helpers
# ============================================================================


def create_upload_context(api_module, **extras) -> Dict[str, Any]:
    """
    Create standard upload context with resilient HTTP client.

    Args:
        api_module: API module containing create_resilient_client()
        **extras: Additional context fields to include

    Returns:
        Context dictionary with 'client' and any extras

    Example:
        >>> from modules import api
        >>> context = create_upload_context(api, uploaded_count=0)
        >>> "client" in context
        True
        >>> context["uploaded_count"]
        0
    """
    context = {"client": api_module.create_resilient_client()}
    context.update(extras)
    return context


def get_client_from_context(context: Dict[str, Any]):
    """
    Safely retrieve HTTP client from context.

    Args:
        context: Upload context dictionary

    Returns:
        HTTP client object

    Raises:
        ValueError: If client not found in context

    Example:
        >>> context = {"client": some_client}
        >>> client = get_client_from_context(context)
        >>> client == some_client
        True
    """
    client = context.get("client")
    if not client:
        raise ValueError("No HTTP client found in upload context")
    return client


# ============================================================================
# Cover Image Detection
# ============================================================================


def is_cover_image(file_path: str, group, config: Dict[str, Any]) -> bool:
    """
    Determine if a file should be treated as a cover image.

    Cover images are the first N images in a group, where N is cover_limit.

    Args:
        file_path: Path to the image file
        group: Group object containing files list
        config: Plugin configuration with cover_limit

    Returns:
        True if file is a cover image, False otherwise

    Example:
        >>> # Assuming group.files = ["/a.jpg", "/b.jpg", "/c.jpg"]
        >>> config = {"cover_limit": 2}
        >>> is_cover_image("/a.jpg", group, config)
        True
        >>> is_cover_image("/c.jpg", group, config)
        False
    """
    cover_limit = config.get("cover_limit", 0)
    if cover_limit == 0:
        return False

    if not hasattr(group, "files"):
        return False

    try:
        idx = group.files.index(file_path)
        return idx < cover_limit
    except ValueError:
        logger.debug(f"File {file_path} not found in group files")
        return False


# ============================================================================
# Progress Callback Helpers
# ============================================================================


def create_progress_callback(progress_callback: Callable) -> Callable:
    """
    Create standard progress callback wrapper for multipart uploads.

    Wraps progress_callback to handle multipart upload monitoring objects
    that have .bytes_read and .len attributes.

    Args:
        progress_callback: User's progress callback function

    Returns:
        Wrapped callback that works with multipart monitoring

    Example:
        >>> def user_callback(progress):
        ...     print(f"Progress: {progress*100:.1f}%")
        >>> wrapped = create_progress_callback(user_callback)
        >>> # Can now be used in lambda: wrapped(monitor)
    """
    return lambda m: progress_callback(m.bytes_read / m.len) if m.len > 0 else None


# ============================================================================
# Upload Execution Helpers
# ============================================================================


def prepare_upload_headers(headers: Dict[str, str], data) -> Dict[str, str]:
    """
    Prepare upload headers, adding Content-Length if needed.

    Args:
        headers: Existing headers dictionary
        data: Upload data object (may have .len attribute)

    Returns:
        Headers dictionary with Content-Length added if applicable

    Example:
        >>> headers = {"Authorization": "Bearer token"}
        >>> # data with len attribute
        >>> prepare_upload_headers(headers, data)
        {'Authorization': 'Bearer token', 'Content-Length': '12345'}
    """
    if "Content-Length" not in headers and hasattr(data, "len"):
        headers["Content-Length"] = str(data.len)
    return headers


def execute_upload(
    client,
    url: str,
    headers: Dict[str, str],
    data,
    timeout: int = 300,
    parse_json: bool = True,
) -> Any:
    """
    Execute standard upload POST request.

    Args:
        client: HTTP client object
        url: Upload URL
        headers: Request headers
        data: Upload data/payload
        timeout: Request timeout in seconds (default: 300)
        parse_json: If True, parse response as JSON (default: True)

    Returns:
        Response object or parsed JSON (depending on parse_json)

    Raises:
        Exception: If upload fails

    Example:
        >>> response = execute_upload(
        ...     client, url, headers, data,
        ...     timeout=300, parse_json=True
        ... )
        >>> response["success"]
        True
    """
    try:
        r = client.post(url, headers=headers, data=data, timeout=timeout)
        return r.json() if parse_json else r
    except Exception as e:
        logger.error(f"Upload request failed: {e}")
        raise


# ============================================================================
# Config Helpers
# ============================================================================


def get_standard_config(config: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Get standard configuration value with fallback.

    Supports legacy key names for backward compatibility.

    Args:
        config: Configuration dictionary
        key: Standard key name to retrieve
        default: Default value if key not found

    Returns:
        Configuration value or default

    Example:
        >>> config = {"thumbnail_size": "180"}
        >>> get_standard_config(config, "thumbnail_size", "100")
        '180'
        >>> get_standard_config(config, "missing_key", "default")
        'default'
    """
    return config.get(key, default)


def normalize_boolean(value: Any) -> bool:
    """
    Convert various boolean representations to True/False.

    Handles: bool, int (0/1), str ("true"/"false"/"yes"/"no"/"1"/"0")

    Args:
        value: Value to convert to boolean

    Returns:
        Boolean representation

    Example:
        >>> normalize_boolean(True)
        True
        >>> normalize_boolean("yes")
        True
        >>> normalize_boolean(0)
        False
        >>> normalize_boolean("false")
        False
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "on")
    return bool(value)


def normalize_int(value: Any, default: int = 0) -> int:
    """
    Safely convert value to integer.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Integer representation or default

    Example:
        >>> normalize_int("42")
        42
        >>> normalize_int("invalid", default=0)
        0
        >>> normalize_int(None, default=10)
        10
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# ============================================================================
# Error Handling Helpers
# ============================================================================


def format_upload_error(plugin_name: str, exception: Exception) -> str:
    """
    Format standardized upload error message.

    Args:
        plugin_name: Name of the plugin
        exception: Exception that occurred

    Returns:
        Formatted error message

    Example:
        >>> error = format_upload_error("Imgur", ValueError("Bad request"))
        >>> "Imgur upload failed" in error
        True
    """
    return f"{plugin_name} upload failed: {str(exception)}"


def log_upload_success(plugin_name: str, url: str) -> None:
    """
    Log standardized upload success message.

    Args:
        plugin_name: Name of the plugin
        url: Upload result URL

    Example:
        >>> log_upload_success("Imgur", "https://imgur.com/abc123")
        # Logs: "✓ Imgur upload successful: https://imgur.com/abc123"
    """
    logger.info(f"✓ {plugin_name} upload successful: {url}")


def log_upload_error(plugin_name: str, exception: Exception) -> None:
    """
    Log standardized upload error message.

    Args:
        plugin_name: Name of the plugin
        exception: Exception that occurred

    Example:
        >>> log_upload_error("Imgur", ValueError("Bad request"))
        # Logs: "✗ Imgur upload failed: Bad request"
    """
    logger.error(f"✗ {plugin_name} upload failed: {exception}")


# ============================================================================
# Gallery/Album Helpers
# ============================================================================


def should_create_gallery(config: Dict[str, Any]) -> bool:
    """
    Determine if auto-gallery creation is enabled.

    Args:
        config: Plugin configuration

    Returns:
        True if auto_gallery is enabled, False otherwise

    Example:
        >>> should_create_gallery({"auto_gallery": True})
        True
        >>> should_create_gallery({"auto_gallery": False})
        False
        >>> should_create_gallery({})
        False
    """
    return config.get("auto_gallery", False)


def get_gallery_id(config: Dict[str, Any], group=None) -> Optional[str]:
    """
    Get gallery ID from config or group object.

    Checks:
    1. group.gallery_id (if group has one from auto-creation)
    2. config["gallery_id"] (user-specified)

    Args:
        config: Plugin configuration
        group: Optional group object

    Returns:
        Gallery ID string or None

    Example:
        >>> config = {"gallery_id": "abc123"}
        >>> get_gallery_id(config)
        'abc123'
        >>> group = type('obj', (object,), {'gallery_id': 'xyz789'})()
        >>> get_gallery_id(config, group)
        'xyz789'
    """
    # Check group object first (from auto-creation)
    if group and hasattr(group, "gallery_id"):
        return group.gallery_id

    # Fall back to config
    return config.get("gallery_id") or None
