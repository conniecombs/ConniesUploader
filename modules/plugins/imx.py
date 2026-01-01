# modules/plugins/imx.py
"""
IMX.to plugin - Schema-based implementation.

Go-based upload plugin (upload handled by Go sidecar).
Python side only manages UI and gallery creation.
"""

from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from .. import api
from loguru import logger


class ImxPlugin(ImageHostPlugin):
    """IMX.to image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "imx.to"

    @property
    def name(self) -> str:
        return "IMX.to"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for IMX.to"""
        return {
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to IMX.to with gallery support, multiple thumbnail formats, and API-based uploads",
            "website": "https://imx.to",
            "implementation": "go",
            "features": {
                "galleries": True,
                "covers": True,
                "authentication": "required",
                "direct_links": True,
                "custom_thumbnails": True,
                "thumbnail_formats": True,  # Fixed Width, Height, Proportional, Square
            },
            "credentials": [
                {
                    "key": "imx_api",
                    "label": "API Key",
                    "required": True,
                    "description": "IMX.to API key for uploads",
                },
                {
                    "key": "imx_user",
                    "label": "Username",
                    "required": False,
                    "description": "Username for gallery creation (optional)",
                },
                {
                    "key": "imx_pass",
                    "label": "Password",
                    "required": False,
                    "secret": True,
                    "description": "Password for gallery creation (optional)",
                },
            ],
            "limits": {
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
                "rate_limit": "API rate limited (handled by service)",
                "max_resolution": (15000, 15000),
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for IMX settings."""
        return [
            {
                "type": "label",
                "text": "⚠️ Requires Credentials (set in Tools)",
                "color": "red",
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["100", "180", "250", "300", "600"],
                "default": "180",
                "required": True,
            },
            {
                "type": "dropdown",
                "key": "thumbnail_format",
                "label": "Thumbnail Format",
                "values": ["Fixed Width", "Fixed Height", "Proportional", "Square"],
                "default": "Fixed Width",
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
        """Custom validation for IMX configuration."""
        errors = []

        # Convert cover_count to int (using helper)
        helpers.validate_cover_count(config, errors)

        return errors

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """
        Called before the batch upload starts.
        Always creates a gallery with the folder name if no manual gallery_id is specified.
        """
        # If user manually specified a gallery_id, use it
        manual_gid = config.get("gallery_id", "").strip()
        if manual_gid:
            logger.info(f"Using manual gallery ID: {manual_gid}")
            return

        # Otherwise, always create a gallery with the folder name
        user = creds.get("imx_user")
        pwd = creds.get("imx_pass")

        if user and pwd:
            # Use the API wrapper which calls Sidecar action="create_gallery"
            gid = api.create_imx_gallery(user, pwd, group.title)

            if gid:
                # Store the new Gallery ID in the group object
                group.gallery_id = gid
                # Also update the config for this specific run so the uploader sees it
                config["gallery_id"] = gid
                logger.info(f"Created IMX gallery: {group.title}")
            else:
                logger.warning(f"Failed to create gallery for: {group.title}")
        else:
            logger.warning("IMX credentials not set - cannot create gallery, IMX will auto-create 'untitled' gallery")

    # Go-based upload - stubs for abstract methods (uploads handled by Go sidecar)
    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def upload_file(self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback):
        """Stub - Go sidecar handles file uploads."""
        pass
