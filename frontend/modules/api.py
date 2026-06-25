# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""API wrappers for image hosting services via Go sidecar.

All operations are dispatched as generic HTTP request specs — the Go sidecar
executes them as a dumb HTTP runner with no host-specific knowledge.
"""

from typing import Dict, Optional, Tuple, Any
from modules.sidecar import SidecarBridge
from loguru import logger


# ---------------------------------------------------------------------------
# Generic helper
# ---------------------------------------------------------------------------


def execute_generic_request(
    spec: Dict[str, Any], timeout: float = 30.0, service: str = ""
) -> Dict[str, Any]:
    """Send a generic HTTP request spec to the Go sidecar for execution.

    Args:
        spec: A GenericHttpRequestSpec dictionary.
        timeout: Seconds to wait for the sidecar response.
        service: Optional service identifier for rate-limiting.

    Returns:
        The sidecar response dict. On success, extracted values are in
        ``resp["data"]``.
    """
    payload: Dict[str, Any] = {
        "action": "http_request",
        "generic_spec": spec,
    }
    if service:
        payload["service"] = service
    return SidecarBridge.get().request_sync(payload, timeout=timeout)


# ---------------------------------------------------------------------------
# Login / credential verification
# ---------------------------------------------------------------------------


def verify_login(service: str, creds: Dict[str, str]) -> Tuple[bool, str]:
    """Verify login credentials for a service.

    Args:
        service: Name of the service (e.g., "imx.to", "vipr.im")
        creds: Dictionary of credentials (username, password, api_key, etc.)

    Returns:
        Tuple of (success: bool, message: str)
    """
    logger.warning(f"Generic login verification is not available for {service}")
    return False, "Use the service-specific credential check for this host."


# ---------------------------------------------------------------------------
# Pixhost gallery operations
# ---------------------------------------------------------------------------


def create_pixhost_gallery(name: str) -> Optional[Dict[str, str]]:
    """Create a Pixhost gallery via generic HTTP request.

    Args:
        name: Name for the gallery

    Returns:
        Dictionary with gallery_hash and gallery_upload_hash if successful,
        None otherwise.
    """
    spec = {
        "url": "https://api.pixhost.to/galleries",
        "method": "POST",
        "headers": {
            "Accept": "application/json",
        },
        "form_fields": {
            "gallery_name": name,
        },
        "response_type": "json",
        "extract_fields": {
            "gallery_name": "gallery_name",
            "gallery_hash": "gallery_hash",
            "gallery_url": "gallery_url",
            "gallery_upload_hash": "gallery_upload_hash",
        },
        "success_check": {
            "field": "gallery_hash",
            "type": "not_empty",
        },
    }

    resp = execute_generic_request(spec, timeout=30, service="pixhost.to")

    if resp.get("status") == "success":
        data = resp.get("data")
        if isinstance(data, dict) and data.get("gallery_hash"):
            return {
                "gallery_name": data.get("gallery_name", name),
                "gallery_hash": data["gallery_hash"],
                "gallery_url": data.get("gallery_url", ""),
                "gallery_upload_hash": data.get("gallery_upload_hash", ""),
            }

    logger.warning(f"Failed to create Pixhost gallery: {resp.get('msg', 'unknown error')}")
    return None


def finalize_pixhost_gallery(
    gallery_upload_hash: str, gallery_hash: str
) -> bool:
    """Finalize a Pixhost gallery.

    Args:
        gallery_upload_hash: The upload hash returned when creating the gallery.
        gallery_hash: The gallery hash (ID) for the gallery.

    Returns:
        True if successful, False otherwise.
    """
    if not gallery_upload_hash or not gallery_hash:
        return False

    spec = {
        "url": f"https://api.pixhost.to/galleries/{gallery_hash}/finalize",
        "method": "POST",
        "headers": {
            "Accept": "application/json",
        },
        "form_fields": {
            "gallery_upload_hash": gallery_upload_hash,
        },
        "response_type": "json",
    }

    resp = execute_generic_request(spec, timeout=15, service="pixhost.to")
    return resp.get("status") == "success"


# ---------------------------------------------------------------------------
# IMX gallery operations
# ---------------------------------------------------------------------------


def create_imx_gallery(
    user: str, pwd: str, name: str, client: Any = None
) -> Optional[str]:
    """Create a gallery on IMX service.

    Args:
        user: IMX username
        pwd: IMX password
        name: Name for the new gallery
        client: Unused, kept for backward compatibility.

    Returns:
        Gallery ID if successful, None otherwise.
    """
    spec = {
        "url": "https://imx.to/user/gallery/add",
        "method": "POST",
        "form_fields": {
            "gal_name": name,
            "gal_descr": "",
        },
        "use_cookies": True,
        "response_type": "html",
        "extract_fields": {
            "gallery_id": "regex:gal_id=(\\d+)",
        },
        "pre_request": {
            "action": "imx_login",
            "url": "https://imx.to/login.php",
            "method": "POST",
            "form_fields": {
                "op": "login",
                "login": user,
                "password": pwd,
            },
            "use_cookies": True,
            "response_type": "html",
            "extract_fields": {},
        },
    }

    resp = execute_generic_request(spec, timeout=30, service="imx.to")

    if resp.get("status") == "success":
        data = resp.get("data")
        if isinstance(data, dict):
            return data.get("gallery_id")

    logger.warning(f"Failed to create IMX gallery: {resp.get('msg', 'unknown error')}")
    return None


# ---------------------------------------------------------------------------
# Vipr helpers
# ---------------------------------------------------------------------------


def vipr_login(user: str, password: str, client: Any = None) -> Dict[str, str]:
    """Create credentials dictionary for Vipr service.

    Note: Actual authentication happens in the Go sidecar per request/session.

    Args:
        user: Username for Vipr
        password: Password for Vipr
        client: Optional HTTP client (unused, kept for compatibility)

    Returns:
        Dictionary with Vipr credentials
    """
    return {"vipr_user": user, "vipr_pass": password}


def get_vipr_metadata(creds: Dict[str, str]) -> Dict[str, Any]:
    """Get gallery metadata from Vipr service.

    Args:
        creds: Credentials dictionary containing vipr_user and vipr_pass

    Returns:
        Dictionary with "galleries" key containing list of gallery dicts
    """
    # Vipr gallery listing requires login + HTML scraping.
    spec = {
        "url": "https://vipr.im/?op=my_files",
        "method": "GET",
        "use_cookies": True,
        "response_type": "html",
        "extract_fields": {
            "response_body": "regex:(<body[\\s\\S]*</body>)",
        },
        "pre_request": {
            "action": "vipr_login",
            "url": "https://vipr.im/",
            "method": "POST",
            "form_fields": {
                "op": "login",
                "login": creds.get("vipr_user", ""),
                "password": creds.get("vipr_pass", ""),
            },
            "use_cookies": True,
            "response_type": "html",
            "extract_fields": {},
        },
    }

    resp = execute_generic_request(spec, timeout=30, service="vipr.im")

    # Parse gallery links from the response body in Python.
    galleries = []
    if resp.get("status") == "success":
        data = resp.get("data", {})
        body = data.get("response_body", "") if isinstance(data, dict) else ""
        import re

        for match in re.finditer(r'fld_id=(\d+)[^>]*>([^<]+)', body):
            galleries.append({"id": match.group(1), "name": match.group(2).strip()})

    return {"galleries": galleries}
