# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""API wrappers for image hosting services via Go sidecar.

All operations are dispatched as generic HTTP request specs — the Go sidecar
executes them as a dumb HTTP runner with no host-specific knowledge.
"""

import json
from typing import Dict, Optional, Tuple, Any
from modules import config
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
        f"{config.PIXHOST_API_BASE_URL}/galleries",
        method="POST",
        headers={"Accept": "application/json"},
        form_fields={"gallery_name": name},
        use_cookies=True,
    )

    resp = execute_transport_request(spec, timeout=30, service=config.PIXHOST_SERVICE_ID)

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


def finalize_pixhost_gallery(gallery_upload_hash: str, gallery_hash: str) -> bool:
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
        f"{config.PIXHOST_API_BASE_URL}/galleries/{gallery_hash}/finalize",
        method="POST",
        headers={"Accept": "application/json"},
        form_fields={"gallery_upload_hash": gallery_upload_hash},
        use_cookies=True,
        include_response_body=False,
    )

    resp = execute_transport_request(spec, timeout=15, service=config.PIXHOST_SERVICE_ID)
    return resp.ok


# ---------------------------------------------------------------------------
# IMX gallery operations
# ---------------------------------------------------------------------------


def create_imx_gallery(
    user: str, pwd: str, name: str, client: Any = None, *, api_key: str = ""
) -> Optional[str]:
    """Create a gallery on IMX service using the live account form contract.

    Args:
        user: IMX username
        pwd: IMX password
        name: Name for the new gallery
        client: Unused, kept for backward compatibility.
        api_key: Required by the application's gallery-management policy.

    Returns:
        Gallery ID if successful, None otherwise.
    """
    from modules.gallery_service import GalleryService

    service = GalleryService(
        bridge=None,
        creds={
            "imx_user": user,
            "imx_pass": pwd,
            "imx_api": api_key,
        },
    )
    result = service.create_gallery("imx.to", name)
    if result.ok and result.record:
        return result.record.id

    logger.warning(f"Failed to create IMX gallery: {result.message}")
    return None


def delete_imx_gallery(
    user: str, pwd: str, gallery_id: str, client: Any = None, *, api_key: str = ""
) -> bool:
    """Delete an IMX gallery through the live account edit form."""
    from modules.gallery_service import GalleryService

    service = GalleryService(
        bridge=None,
        creds={
            "imx_user": user,
            "imx_pass": pwd,
            "imx_api": api_key,
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


def _vipr_gallery_service(creds: Dict[str, str]) -> Any:
    """GalleryService owns the Vipr login check and folder parsing."""
    from modules.gallery_service import GalleryService

    return GalleryService(
        bridge=SidecarBridge.get(),
        creds={
            "vipr_user": creds.get("vipr_user", ""),
            "vipr_pass": creds.get("vipr_pass", ""),
        },
    )


def get_vipr_metadata(creds: Dict[str, str]) -> Dict[str, Any]:
    """Get gallery metadata from Vipr service.

    Args:
        creds: Credentials dictionary containing vipr_user and vipr_pass

    Returns:
        Dictionary with "galleries" key containing list of gallery dicts.
        The list is empty when the login is not accepted.
    """
    result = _vipr_gallery_service(creds).list_galleries("vipr.im")
    if not result.ok:
        logger.warning(f"Vipr gallery list: {result.message}")
        return {"galleries": []}
    return {"galleries": [dict(record.raw) for record in result.records]}


def create_vipr_gallery(creds: Dict[str, str], name: str) -> Optional[Dict[str, str]]:
    """Create a named Vipr gallery/folder and return the folder it created."""
    name = (name or "").strip()
    if not name:
        return None

    result = _vipr_gallery_service(creds).create_gallery("vipr.im", name)
    if not result.ok or not result.record:
        logger.warning(f"Failed to create Vipr gallery: {result.message}")
        return None

    record = result.record
    return {
        "id": record.id,
        "name": record.name,
        "url": record.url,
        "gallery_id": record.id,
        "gallery_name": record.name,
        "gallery_url": record.url,
    }


def delete_vipr_gallery(creds: Dict[str, str], gallery_id: str) -> bool:
    """Delete a Vipr gallery/folder and confirm it is no longer listed."""
    gallery_id = (gallery_id or "").strip()
    if not gallery_id:
        return False

    result = _vipr_gallery_service(creds).delete_gallery("vipr.im", gallery_id)
    if not result.ok:
        logger.warning(f"Failed to delete Vipr gallery {gallery_id}: {result.message}")
    return result.ok
