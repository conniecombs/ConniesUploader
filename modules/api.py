"""API wrappers for image hosting services via Go sidecar."""

from typing import Dict, Optional, Tuple, Any
from modules.sidecar import SidecarBridge

# --- Generic Helpers ---


def verify_login(service: str, creds: Dict[str, str]) -> Tuple[bool, str]:
    """Verify login credentials for a service.

    Args:
        service: Name of the service (e.g., "imx.to", "vipr.im")
        creds: Dictionary of credentials (username, password, api_key, etc.)

    Returns:
        Tuple of (success: bool, message: str)
    """
    payload = {"action": "verify", "service": service, "creds": creds}
    resp = SidecarBridge.get().request_sync(payload, timeout=15)
    if resp.get("status") == "success":
        return True, resp.get("msg", "OK")
    return False, resp.get("msg", "Failed")


# --- Service Specific Wrappers (Delegating to Go) ---


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
    payload = {"action": "list_galleries", "service": "vipr.im", "creds": creds}
    resp = SidecarBridge.get().request_sync(payload, timeout=30)

    if resp.get("status") == "success":
        # Expecting Go to return: { "data": [ {"id": "1", "name": "Folder"}, ... ] }
        return {"galleries": resp.get("data", [])}

    return {"galleries": []}


def create_imx_gallery(user: str, pwd: str, name: str, client: Any = None) -> Optional[str]:
    """Create a gallery on IMX service.

    Args:
        user: IMX username
        pwd: IMX password
        name: Name for the new gallery
        client: Optional HTTP client (unused, kept for compatibility)

    Returns:
        Gallery ID if successful, None otherwise
    """
    payload = {
        "action": "create_gallery",
        "service": "imx.to",
        "creds": {"imx_user": user, "imx_pass": pwd},
        "config": {"gallery_name": name},
    }

    # Increase timeout as gallery creation might involve redirects/parsing
    resp = SidecarBridge.get().request_sync(payload, timeout=30)

    if resp.get("status") == "success":
        # The 'msg' or 'data' field from Go should contain the new ID
        return resp.get("data")

    return None


def create_pixhost_gallery(name: str, client: Any = None) -> Optional[Dict[str, str]]:
    """Create a Pixhost gallery.

    Args:
        name: Name for the gallery
        client: Optional HTTP client (unused, kept for compatibility)

    Returns:
        Dictionary with gallery_hash and gallery_upload_hash if successful, None otherwise
    """
    payload = {
        "action": "create_gallery",
        "service": "pixhost.to",
        "config": {"gallery_name": name},
    }

    resp = SidecarBridge.get().request_sync(payload, timeout=30)

    if resp.get("status") == "success":
        # Return gallery data containing hashes
        return resp.get("data")

    return None


def finalize_pixhost_gallery(gallery_upload_hash: str, gallery_hash: str, client: Any = None) -> bool:
    """Finalize a Pixhost gallery (set title and make it visible).

    Args:
        gallery_upload_hash: The upload hash returned when creating the gallery
        gallery_hash: The gallery hash (ID) for the gallery
        client: Optional HTTP client (unused, kept for compatibility)

    Returns:
        True if successful, False otherwise
    """
    if not gallery_upload_hash or not gallery_hash:
        return False

    payload = {
        "action": "finalize_gallery",
        "service": "pixhost.to",
        "config": {
            "gallery_upload_hash": gallery_upload_hash,
            "gallery_hash": gallery_hash,
        },
    }

    resp = SidecarBridge.get().request_sync(payload, timeout=15)

    return resp.get("status") == "success"
