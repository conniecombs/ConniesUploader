# modules/plugins/imx.py
"""
IMX.to plugin - Schema-based implementation.

Go-based upload plugin (upload handled by Go sidecar).
Python side only manages UI and gallery creation.
"""

from typing import Dict, Any, List
from .base import ImageHostPlugin
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
                "key": "imx_thumb_id",
                "label": "Thumbnail Size",
                "values": ["100", "180", "250", "300", "600"],
                "default": "180",
                "required": True,
            },
            {
                "type": "dropdown",
                "key": "imx_format_id",
                "label": "Image Format",
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
                        "key": "imx_cover_count",
                        "values": [str(i) for i in range(11)],
                        "default": "0",
                        "width": 80,
                    },
                ],
            },
            {
                "type": "checkbox",
                "key": "imx_links",
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

        # Convert cover_count to int
        try:
            config["imx_cover_count"] = int(config.get("imx_cover_count", 0))
        except (ValueError, TypeError):
            errors.append("Cover count must be a valid number")

        return errors

    def prepare_group(
        self, group, config: Dict[str, Any], context: Dict[str, Any], creds: Dict[str, Any]
    ) -> None:
        """
        Called before the batch upload starts.
        Checks if 'auto_gallery' is on, and if so, calls Go Sidecar to create one.
        """
        if config.get("auto_gallery"):
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

    # REMOVED: initialize_session, upload_file (Go handles this now)
