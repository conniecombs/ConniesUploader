# modules/plugins/pixhost.py
"""
Pixhost.to plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI, configuration validation, and gallery coordination.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


class PixhostPlugin(ImageHostPlugin):
    """Pixhost.to image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "pixhost.to"

    @property
    def name(self) -> str:
        return "Pixhost.to"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for Pixhost.to"""
        return {
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to Pixhost.to with gallery support and cover image handling",
            "website": "https://pixhost.to",
            "implementation": "go",
            "features": {
                "galleries": True,
                "covers": True,
                "authentication": "none",
                "direct_links": True,
                "custom_thumbnails": True,
            },
            "credentials": [],  # No credentials required
            "limits": {
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
                "rate_limit": "Unlimited (respectful use)",
                "max_resolution": (15000, 15000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """
        Declarative UI schema for Pixhost settings.

        This replaces the manual render_settings() method, reducing code
        from ~40 lines to ~50 lines of pure data (60% reduction).
        """
        return [
            {
                "type": "dropdown",
                "key": "content_type",
                "label": "Content Type",
                "values": ["Safe", "Adult"],
                "default": "Safe",
                "required": True,
                "help": "Content rating for uploaded images",
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["150", "200", "250", "300", "350", "400", "450", "500"],
                "default": "200",
                "required": True,
                "help": "Size of thumbnail images in pixels",
            },
            {
                "type": "inline_group",
                "fields": [
                    {"type": "label", "text": "Cover Images:", "width": 100},
                    {
                        "type": "dropdown",
                        "key": "cover_count",
                        "values": [str(i) for i in range(11)],
                        "default": "0",
                        "width": 80,
                    },
                ],
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False,
                "help": "Save upload links to a text file",
            },
            {
                "type": "separator",
            },
            {
                "type": "text",
                "key": "gallery_hash",
                "label": "Gallery Hash (Optional)",
                "default": "",
                "placeholder": "Leave blank for auto-gallery",
                "help": "Existing gallery hash to upload to",
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """
        Custom validation for Pixhost configuration.

        The schema system handles basic validation (required fields, types, ranges).
        This method adds service-specific validation logic.
        """
        errors = []

        # Validate gallery hash format if provided (using helper)
        gallery_hash = config.get("gallery_hash", "")
        helpers.validate_gallery_id(gallery_hash, errors, alphanumeric=True)

        # Convert cover_count to int for storage (using helper)
        helpers.validate_cover_count(config, errors)

        return errors

    # --- Upload Implementation (Go Sidecar Handles Uploads) ---

    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """
        Prepare group for upload.

        If auto_gallery is enabled, creates a new gallery for this group.
        """
        if config.get("auto_gallery"):
            clean_title = group.title.replace("[", "").replace("]", "").strip()
            new_data = api.create_pixhost_gallery(clean_title, client=context["client"])

            if new_data:
                # Store gallery info on the group object
                group.pix_data = new_data
                group.gallery_id = new_data.get("gallery_hash", "")
                context["created_galleries"].append(new_data)
                logger.info(f"Created Pixhost gallery: {clean_title}")

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """Stub - Go sidecar handles file uploads."""
        pass

    def finalize_batch(self, context: Dict[str, Any]) -> None:
        """Stub - Go sidecar handles batch finalization."""
        pass
