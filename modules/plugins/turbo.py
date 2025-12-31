# modules/plugins/turbo.py
"""
TurboImageHost plugin - Schema-based implementation with Go sidecar uploads.

Go-based upload plugin (upload handled by Go sidecar).
Python side manages UI, configuration validation, and optional authentication.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


class TurboPlugin(ImageHostPlugin):
    """TurboImageHost image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "turboimagehost"

    @property
    def name(self) -> str:
        return "TurboImageHost"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for TurboImageHost"""
        return {
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to TurboImageHost with optional authentication, dynamic endpoint configuration, and cover image support",
            "website": "https://www.turboimagehost.com",
            "implementation": "go",
            "features": {
                "galleries": True,
                "covers": True,
                "authentication": "optional",
                "direct_links": True,
                "custom_thumbnails": True,
                "dynamic_endpoint": True,  # Fetches upload endpoint dynamically
            },
            "credentials": [
                {
                    "key": "turbo_user",
                    "label": "Username",
                    "required": False,
                    "description": "Optional login for enhanced features",
                },
                {
                    "key": "turbo_pass",
                    "label": "Password",
                    "required": False,
                    "secret": True,
                    "description": "Password for enhanced features",
                },
            ],
            "limits": {
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
                "rate_limit": "Moderate (respectful use)",
                "max_resolution": (15000, 15000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for Turbo settings."""
        return [
            {
                "type": "label",
                "text": "ℹ️ Login Optional",
                "color": "orange",
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["150", "200", "250", "300", "350", "400", "500", "600"],
                "default": "180",
                "required": True,
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
            },
            {
                "type": "separator",
            },
            {
                "type": "text",
                "key": "gallery_id",
                "label": "Gallery ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for auto-gallery",
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Turbo configuration."""
        errors = []

        # Convert cover_count to int (using helper)
        helpers.validate_cover_count(config, errors)

        # Content type - turbo uses "adult" or "all"
        # For now, default to "all" (safe)
        config["content_type"] = "all"

        return errors

    # --- Upload Implementation (Unchanged from original) ---

    def initialize_session(
        self, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """Stub - Go sidecar handles file uploads."""
        pass
