# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""API wrappers for image hosting services via Go sidecar.

All operations are dispatched as generic HTTP request specs — the Go sidecar
executes them as a dumb HTTP runner with no host-specific knowledge.
"""

import json
from typing import Dict, Optional, Tuple, Any
from modules.sidecar import SidecarBridge
from modules.transport import build_transport_spec, execute_transport_request
from loguru import logger


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
    spec = build_transport_spec(
        "https://api.pixhost.to/galleries",
        method="POST",
        headers={"Accept": "application/json"},
        form_fields={"gallery_name": name},
        use_cookies=True,
    )

    resp = execute_transport_request(spec, timeout=30, service="pixhost.to")

    if resp.ok:
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            logger.warning(f"Failed to parse Pixhost gallery response: {exc}")
            data = None
        if isinstance(data, dict) and data.get("gallery_hash"):
            return {
                "gallery_name": data.get("gallery_name", name),
                "gallery_hash": data["gallery_hash"],
                "gallery_url": data.get("gallery_url", ""),
                "gallery_upload_hash": data.get("gallery_upload_hash", ""),
            }

    logger.warning(f"Failed to create Pixhost gallery: {resp.message or 'unknown error'}")
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

    spec = build_transport_spec(
        f"https://api.pixhost.to/galleries/{gallery_hash}/finalize",
        method="POST",
        headers={"Accept": "application/json"},
        form_fields={"gallery_upload_hash": gallery_upload_hash},
        use_cookies=True,
        include_response_body=False,
    )

    resp = execute_transport_request(spec, timeout=15, service="pixhost.to")
    return resp.ok


# ---------------------------------------------------------------------------
# IMX gallery operations
# ---------------------------------------------------------------------------


def create_imx_gallery(
    user: str, pwd: str, name: str, client: Any = None
) -> Optional[str]:
    """Create a gallery on IMX service using the live account form contract.

    Args:
        user: IMX username
        pwd: IMX password
        name: Name for the new gallery
        client: Unused, kept for backward compatibility.

    Returns:
        Gallery ID if successful, None otherwise.
    """
    from modules.gallery_service import GalleryService

    service = GalleryService(
        bridge=None,
        creds={
            "imx_user": user,
            "imx_pass": pwd,
        },
    )
    result = service.create_gallery("imx.to", name)
    if result.ok and result.record:
        return result.record.id

    logger.warning(f"Failed to create IMX gallery: {result.message}")
    return None


def delete_imx_gallery(user: str, pwd: str, gallery_id: str, client: Any = None) -> bool:
    """Delete an IMX gallery through the live account edit form."""
    from modules.gallery_service import GalleryService

    service = GalleryService(
        bridge=None,
        creds={
            "imx_user": user,
            "imx_pass": pwd,
        },
    )
    result = service.delete_gallery("imx.to", gallery_id)
    if result.ok:
        return True

    logger.warning(f"Failed to delete IMX gallery {gallery_id}: {result.message}")
    return False


# ---------------------------------------------------------------------------
# Vipr helpers
# ---------------------------------------------------------------------------


def vipr_login(user: str, password: str, client: Any = None) -> Dict[str, str]:
    """Create credentials dictionary for Vipr service.

    Note: Python now performs Vipr authentication by issuing resolved transport
    requests through the Go sidecar.

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
    galleries = []
    bridge = SidecarBridge.get()
    if _login_vipr(creds, bridge=bridge, timeout=30):
        resp = _fetch_vipr_file_manager(bridge=bridge, timeout=30)
        body = resp.body if resp.ok else ""

        from modules.gallery_service import parse_vipr_gallery_html

        galleries = parse_vipr_gallery_html(body)

    return {"galleries": galleries}


def create_vipr_gallery(creds: Dict[str, str], name: str) -> Optional[Dict[str, str]]:
    """Create a named Vipr gallery/folder through the File Manager form."""
    name = (name or "").strip()
    if not name:
        return None

    bridge = SidecarBridge.get()
    if not _login_vipr(creds, bridge=bridge, timeout=30):
        logger.warning("Failed to create Vipr gallery: login failed")
        return None

    spec = build_transport_spec(
        "https://vipr.im/",
        method="POST",
        use_cookies=True,
        form_fields={
            "op": "my_files",
            "fld_id": "0",
            "sort_field": "file_created",
            "sort_order": "down",
            "export_mode": "",
            "domain": "vipr.im",
            "create_new_folder": name,
        },
    )

    resp = execute_transport_request(
        spec, timeout=30, service="vipr.im", bridge=bridge
    )
    if not resp.ok:
        logger.warning(f"Failed to create Vipr gallery: {resp.message or 'unknown error'}")
        return None

    from modules.gallery_service import parse_vipr_gallery_html

    raw_records = parse_vipr_gallery_html(resp.body)
    raw = next((record for record in raw_records if record.get("name") == name), None)
    if not raw or not raw.get("id"):
        logger.warning("Vipr gallery was created, but its folder ID could not be parsed")
        return None

    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or name),
        "url": str(raw.get("url") or ""),
        "gallery_id": str(raw.get("id") or ""),
        "gallery_name": str(raw.get("name") or name),
        "gallery_url": str(raw.get("url") or ""),
    }


def delete_vipr_gallery(creds: Dict[str, str], gallery_id: str) -> bool:
    """Delete a Vipr gallery/folder through the File Manager delete endpoint."""
    gallery_id = (gallery_id or "").strip()
    if not gallery_id:
        return False

    bridge = SidecarBridge.get()
    if not _login_vipr(creds, bridge=bridge, timeout=30):
        logger.warning("Failed to delete Vipr gallery: login failed")
        return False

    spec = build_transport_spec(
        f"https://vipr.im/?op=my_files&fld_id=0&del_folder={gallery_id}",
        method="GET",
        use_cookies=True,
    )

    resp = execute_transport_request(
        spec, timeout=30, service="vipr.im", bridge=bridge
    )
    if not resp.ok:
        logger.warning(f"Failed to delete Vipr gallery: {resp.message or 'unknown error'}")
        return False

    from modules.gallery_service import parse_vipr_gallery_html

    remaining = parse_vipr_gallery_html(resp.body)
    return not any(str(record.get("id") or "") == gallery_id for record in remaining)


def _login_vipr(
    creds: Dict[str, str],
    *,
    bridge: Any,
    timeout: float,
) -> bool:
    spec = build_transport_spec(
        "https://vipr.im/",
        method="POST",
        form_fields={
            "op": "login",
            "login": creds.get("vipr_user", ""),
            "password": creds.get("vipr_pass", ""),
        },
        use_cookies=True,
    )
    resp = execute_transport_request(
        spec, timeout=timeout, service="vipr.im", bridge=bridge
    )
    if not resp.ok:
        logger.warning(f"Vipr login failed: {resp.message or 'unknown error'}")
    return resp.ok


def _fetch_vipr_file_manager(*, bridge: Any, timeout: float):
    spec = build_transport_spec(
        "https://vipr.im/?op=my_files",
        method="GET",
        use_cookies=True,
    )
    return execute_transport_request(
        spec, timeout=timeout, service="vipr.im", bridge=bridge
    )
