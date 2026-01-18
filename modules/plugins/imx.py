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
                "values": ["100", "150", "180", "250", "300", "600"],
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
        Creates a gallery with the folder name if auto_gallery is enabled and no manual gallery_id is specified.
        """
        # If user manually specified a gallery_id, use it
        manual_gid = config.get("gallery_id", "").strip()
        if manual_gid:
            logger.info(f"Using manual gallery ID: {manual_gid}")
            return

        # Only create gallery if auto_gallery setting is enabled
        if not config.get("auto_gallery"):
            logger.debug(f"Auto-gallery disabled, skipping gallery creation for: {group.title}")
            return

        # Create a gallery with the folder name
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
            logger.warning("IMX credentials (username/password) not set - cannot create gallery")

    # NEW: Generic HTTP request builder (replaces hardcoded Go service logic)
    def build_http_request(self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build HTTP request specification for IMX.to upload.
        This replaces the hardcoded uploadImx() function in Go.
        """
        # DIAGNOSTIC: Log what we receive from UI
        logger.info(f"IMX build_http_request called with config keys: {list(config.keys())}")
        logger.info(f"IMX thumbnail_size from config: {repr(config.get('thumbnail_size'))} (type: {type(config.get('thumbnail_size')).__name__})")

        # Map thumbnail size to IMX API ID (matching old working code)
        size_map = {"100": "1", "150": "6", "180": "2", "250": "3", "300": "4", "600": "5"}

        # Support both new (thumbnail_size) and legacy (imx_thumb) keys
        thumb_size_raw = config.get("thumbnail_size") or config.get("imx_thumb")
        # Convert to string in case UI passes integer or other type
        thumb_size_value = str(thumb_size_raw) if thumb_size_raw else "180"
        thumb_size = size_map.get(thumb_size_value, "2")
        logger.info(f"IMX thumbnail mapping: raw={repr(thumb_size_raw)} → '{thumb_size_value}' → API ID '{thumb_size}'")

        # Map thumbnail format to IMX API ID
        format_map = {
            "Fixed Width": "1",
            "Fixed Height": "4",
            "Proportional": "2",
            "Square": "3"
        }
        # Support both new (thumbnail_format) and legacy (imx_format) keys
        thumb_format_raw = config.get("thumbnail_format") or config.get("imx_format")
        thumb_format_value = str(thumb_format_raw) if thumb_format_raw else "Fixed Width"
        thumb_format = format_map.get(thumb_format_value, "1")

        # Build multipart fields
        multipart_fields = {
            "image": {"type": "file", "value": file_path},
            "format": {"type": "text", "value": "json"},
            "adult": {"type": "text", "value": "1"},
            "upload_type": {"type": "text", "value": "file"},
            "simple_upload": {"type": "text", "value": "Upload"},
            "thumbnail_size": {"type": "text", "value": thumb_size},
            "thumb_size_contaner": {"type": "text", "value": thumb_size},  # Legacy name
            "thumbnail_format": {"type": "text", "value": thumb_format},
        }

        # Add gallery ID if specified
        gallery_id = config.get("gallery_id", "").strip()
        if gallery_id:
            multipart_fields["gallery_id"] = {"type": "text", "value": gallery_id}

        return {
            "url": "https://api.imx.to/v1/upload.php",
            "method": "POST",
            "headers": {
                "X-API-KEY": creds.get("imx_api", ""),
            },
            "multipart_fields": multipart_fields,
            "response_parser": {
                "type": "json",
                "url_path": "data.image_url",
                "thumb_path": "data.thumbnail_url",
                "status_path": "status",
                "success_value": "success"
            }
        }

    # Go-based upload - stubs for abstract methods (uploads handled by Go sidecar)
    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def upload_file(self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback):
        """Stub - Go sidecar handles file uploads via build_http_request()."""
        pass
