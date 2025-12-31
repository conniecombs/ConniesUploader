# modules/plugins/imagebam.py
"""
ImageBam.com plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI and configuration validation.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


class ImageBamPlugin(ImageHostPlugin):
    """ImageBam.com image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "imagebam.com"

    @property
    def name(self) -> str:
        return "ImageBam"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for ImageBam.com"""
        return {
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to ImageBam.com with optional authentication and CSRF-protected uploads",
            "website": "https://imagebam.com",
            "implementation": "go",
            "features": {
                "galleries": True,
                "covers": False,
                "authentication": "optional",
                "direct_links": True,
                "custom_thumbnails": True,
            },
            "credentials": [
                {
                    "key": "imagebam_user",
                    "label": "Username",
                    "required": False,
                    "description": "Optional login for private galleries",
                },
                {
                    "key": "imagebam_pass",
                    "label": "Password",
                    "required": False,
                    "secret": True,
                    "description": "Password for private galleries",
                },
            ],
            "limits": {
                "max_file_size": 25 * 1024 * 1024,  # 25MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif"],
                "rate_limit": "Moderate (CSRF protection)",
                "max_resolution": (10000, 10000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for ImageBam settings."""
        return [
            {
                "type": "dropdown",
                "key": "content_type",
                "label": "Content Type",
                "values": ["Safe", "Adult"],
                "default": "Safe",
                "required": True,
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["100", "180", "250", "300"],
                "default": "180",
                "required": True,
            },
        ]

    # --- Upload Implementation (Unchanged from original) ---

    def initialize_session(
        self, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """
        Prepare group for upload.

        ImageBam requires a session token (upload_token) per group.
        """
        if context.get("csrf"):
            try:
                # Using main client from context
                token_client = context["client"]

                # Logic from old upload_manager:
                gal_title = group.title if config.get("auto_gallery") else None
                gal_id = "default"

                upload_token = api.get_imagebam_upload_token(
                    token_client,
                    context["csrf"],
                    config.get("content_type", "Safe"),
                    config.get("thumbnail_size", "180"),
                    gal_id,
                    gal_title,
                )
                group.ib_upload_token = upload_token
                logger.info(f"Got ImageBam upload token for group: {group.title}")
            except Exception as e:
                logger.error(f"ImageBam Token Error: {e}")

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """Stub - Go sidecar handles file uploads."""
        pass
