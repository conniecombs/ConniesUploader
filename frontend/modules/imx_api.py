# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""IMX's documented first-image gallery API (no website login required)."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Mapping

import requests

from modules import config


class ImxApiError(RuntimeError):
    """An actionable failure; creation requests must not be blindly retried."""


def require_upload_credentials(creds: Mapping[str, str]) -> None:
    """Enforce the application's upload policy before constructing any request."""
    missing = [
        label for key, label in (
            ("imx_user", "username"), ("imx_pass", "password"), ("imx_api", "API key")
        ) if not str(creds.get(key) or "").strip()
    ]
    if missing:
        raise ImxApiError(
            f"IMX uploads require {' and '.join(missing)}. Set these in Credentials before uploading."
        )


@dataclass(frozen=True)
class ImxGalleryUpload:
    gallery_id: str
    gallery_name: str
    image_url: str
    thumbnail_url: str


def validate_gallery_name(name: str) -> str:
    name = str(name or "").strip()
    if (
        not name
        or len(name) > 100
        or not re.fullmatch(r"[A-Za-z0-9 .,_()\[\]-]+", name)
    ):
        raise ImxApiError(
            "IMX gallery names must be 1–100 characters: letters A–Z, numbers, "
            "spaces, or - _ . , ( ) [ ]. Rename the batch or enter a valid gallery name."
        )
    return name


def create_gallery_with_image(
    api_key: str, name: str, image_path: str, *, fields: Mapping[str, str] | None = None
) -> ImxGalleryUpload:
    """Upload exactly one image and require a confirmed new gallery ID.

    IMX creates a gallery for *every* create_gallery request. Never automatically
    retry a timeout, redirect, malformed response, or server error here.
    """
    api_key = str(api_key or "").strip()
    if not api_key:
        raise ImxApiError(
            "Set the IMX API key in Credentials before creating a gallery."
        )
    name = validate_gallery_name(name)
    path = Path(image_path)
    if not path.is_file() or path.suffix.lower() not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
    }:
        raise ImxApiError(
            "Choose an existing JPG, PNG, or GIF as the first gallery image."
        )
    if not 0 < path.stat().st_size <= 100 * 1024 * 1024:
        raise ImxApiError(
            "The first IMX gallery image must be nonempty and at most 100 MB."
        )

    # Only documented options are forwarded. A selected gallery must never
    # compete with create_gallery, and the response must always be JSON.
    data = {
        k: str(v)
        for k, v in (fields or {}).items()
        if k in {"thumbnail_size", "thumbnail_format", "adult"}
    }
    data.update(format="json", create_gallery="1", gallery_name=name)
    uncertain = "Check your IMX account before retrying; the first image may already have uploaded."
    try:
        with path.open("rb") as image, requests.Session() as session:
            response = session.post(
                config.IMX_URL,
                headers={"X-API-Key": api_key, "User-Agent": config.USER_AGENT},
                data=data,
                files={"image": (path.name, image)},
                timeout=(10, 120),
                allow_redirects=False,
            )
    except requests.RequestException:
        raise ImxApiError(
            f"IMX gallery upload lost its connection or timed out. {uncertain}"
        ) from None
    except OSError:
        raise ImxApiError(
            "Could not read the first gallery image. Check that it is still accessible."
        ) from None

    if response.status_code in {401, 403}:
        raise ImxApiError(
            "IMX rejected API authentication. Check the IMX API key in Credentials."
        )
    if response.status_code == 429:
        raise ImxApiError("IMX is rate limiting uploads. Wait before trying again.")
    if response.status_code >= 300:
        raise ImxApiError(
            f"IMX gallery upload returned HTTP {response.status_code}. {uncertain}"
        )
    try:
        payload = response.json()
    except ValueError:
        raise ImxApiError(
            f"IMX returned an unreadable gallery response. {uncertain}"
        ) from None
    if not isinstance(payload, dict):
        raise ImxApiError(f"IMX returned an invalid gallery response. {uncertain}")
    if payload.get("status") != "success":
        message = str(payload.get("message") or "Upload was rejected.").replace(
            api_key, "[redacted]"
        )
        raise ImxApiError(f"IMX gallery creation failed: {message[:400]}")
    result = payload.get("data")
    if not isinstance(result, dict):
        raise ImxApiError(f"IMX reported success without gallery data. {uncertain}")
    gallery_id = str(result.get("gallery_id") or "")
    image_url = str(result.get("image_url") or "")
    thumbnail_url = str(result.get("thumbnail_url") or "")
    if (
        not re.fullmatch(r"[A-Za-z0-9]+", gallery_id)
        or not image_url
        or not thumbnail_url
    ):
        raise ImxApiError(
            f"IMX did not confirm both the new gallery and first image. {uncertain}"
        )
    return ImxGalleryUpload(
        gallery_id, str(result.get("gallery_name") or name), image_url, thumbnail_url
    )
