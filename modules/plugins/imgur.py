# modules/plugins/imgur.py
"""
Imgur plugin - Schema-based implementation.

Python-based upload plugin with anonymous and authenticated uploads.
Demonstrates standard config keys and auto-discovery.
"""

import os
from typing import Dict, Any, List
from .base import ImageHostPlugin
from .. import api
from loguru import logger


class ImgurPlugin(ImageHostPlugin):
    """Imgur image hosting plugin using schema-based UI."""

    @property
    def id(self) -> str:
        return "imgur.com"

    @property
    def name(self) -> str:
        return "Imgur"

    @property
    def metadata(self) -> Dict[str, Any]:
        """Plugin metadata for Imgur"""
        return {
            "version": "2.0.0",
            "author": "Connie's Uploader Team",
            "description": "Upload images to Imgur with anonymous or authenticated uploads, album support, and automatic thumbnail generation",
            "website": "https://imgur.com",
            "implementation": "python",
            "features": {
                "galleries": True,  # Imgur calls them "albums"
                "covers": False,  # Imgur doesn't have cover images
                "authentication": "optional",
                "direct_links": True,
                "custom_thumbnails": True,
                "anonymous_upload": True,  # Can upload without account
            },
            "credentials": [
                {
                    "key": "imgur_client_id",
                    "label": "Client ID",
                    "required": False,
                    "description": "Imgur API Client ID (optional for anonymous uploads)",
                },
                {
                    "key": "imgur_access_token",
                    "label": "Access Token",
                    "required": False,
                    "secret": True,
                    "description": "Imgur OAuth2 access token for authenticated uploads",
                },
            ],
            "limits": {
                "max_file_size": 20 * 1024 * 1024,  # 20MB for free accounts
                "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".apng", ".tiff", ".mp4", ".webm"],
                "rate_limit": "1250 uploads per day (free account)",
                "max_resolution": (None, None),  # No specific limit
                "min_resolution": (1, 1),
            },
        }

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """Declarative UI schema for Imgur settings."""
        return [
            {
                "type": "label",
                "text": "ℹ️ Anonymous Upload Available (no credentials needed)",
                "color": "green",
            },
            {
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": ["s", "b", "t", "m", "l", "h"],
                "default": "m",
                "required": True,
                "help": "s=90x90, b=160x160, t=160x160, m=320x320, l=640x640, h=1024x1024",
            },
            {
                "type": "dropdown",
                "key": "content_type",
                "label": "Content Type",
                "values": ["Safe", "NSFW"],
                "default": "Safe",
                "required": True,
                "help": "Mark content as safe or NSFW (mature)",
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
                "key": "album_id",
                "label": "Album ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for no album",
                "help": "Imgur album ID to add images to",
            },
            {
                "type": "text",
                "key": "title",
                "label": "Image Title (Optional)",
                "default": "",
                "placeholder": "Leave blank for filename",
                "help": "Title for uploaded images",
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Imgur configuration."""
        errors = []

        # Validate thumbnail size
        valid_sizes = ["s", "b", "t", "m", "l", "h"]
        if config.get("thumbnail_size") not in valid_sizes:
            errors.append(f"Invalid thumbnail size. Must be one of: {', '.join(valid_sizes)}")

        # Convert content type to Imgur's mature flag
        content = config.get("content_type", "Safe")
        config["mature"] = content == "NSFW"

        return errors

    # --- Upload Implementation ---

    def initialize_session(
        self, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Initialize upload session for Imgur.

        Imgur supports both anonymous and authenticated uploads.
        """
        client = api.create_resilient_client()
        context = {
            "client": client,
            "client_id": creds.get("imgur_client_id"),
            "access_token": creds.get("imgur_access_token"),
        }

        # Determine upload mode
        if context["access_token"]:
            logger.info("Imgur: Using authenticated upload")
        elif context["client_id"]:
            logger.info("Imgur: Using anonymous upload with Client ID")
        else:
            logger.warning("Imgur: No credentials provided - uploads may fail")

        return context

    def upload_file(
        self, file_path: str, group, config: Dict[str, Any], context: Dict[str, Any], progress_callback
    ):
        """
        Upload a single file to Imgur.

        Args:
            file_path: Path to image file
            group: Group object containing files
            config: Plugin configuration from UI
            context: Session context from initialize_session
            progress_callback: Function to report upload progress

        Returns:
            Tuple of (viewer_url, thumb_url)
        """
        client = context["client"]

        # Build headers
        headers = {}
        if context.get("access_token"):
            headers["Authorization"] = f"Bearer {context['access_token']}"
        elif context.get("client_id"):
            headers["Authorization"] = f"Client-ID {context['client_id']}"
        else:
            raise ValueError("Imgur upload requires either Client ID or Access Token")

        # Build upload data
        upload_data = {}

        # Title (use config title or filename)
        if config.get("title"):
            upload_data["title"] = config["title"]
        else:
            upload_data["title"] = os.path.splitext(os.path.basename(file_path))[0]

        # Album (if specified)
        if config.get("album_id"):
            upload_data["album"] = config["album_id"]

        # Mature flag
        if config.get("mature", False):
            upload_data["mature"] = "1"

        # Open file and upload
        with open(file_path, "rb") as f:
            files = {"image": f}

            # Call progress callback at start
            progress_callback(0.1)

            try:
                # Upload to Imgur API
                r = client.post(
                    "https://api.imgur.com/3/image",
                    headers=headers,
                    data=upload_data,
                    files=files,
                    timeout=300,
                )

                # Call progress callback at completion
                progress_callback(1.0)

                # Parse response
                response = r.json()

                if response.get("success"):
                    data = response.get("data", {})

                    # Get image link
                    image_link = data.get("link")

                    # Build thumbnail link based on size
                    thumb_size = config.get("thumbnail_size", "m")
                    if image_link:
                        # Imgur thumbnail format: replace extension with suffix + extension
                        # e.g., https://i.imgur.com/abc123.jpg -> https://i.imgur.com/abc123m.jpg
                        base, ext = os.path.splitext(image_link)
                        thumb_link = f"{base}{thumb_size}{ext}"
                    else:
                        thumb_link = None

                    logger.info(f"Imgur upload successful: {image_link}")
                    return image_link, thumb_link
                else:
                    error_msg = response.get("data", {}).get("error", "Unknown error")
                    raise ValueError(f"Imgur upload failed: {error_msg}")

            except Exception as e:
                logger.error(f"Imgur upload error: {e}")
                raise
