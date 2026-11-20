# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/imgur.py
"""
Imgur plugin - Schema-based implementation with Go sidecar uploads.

Uploads run through the Go sidecar's transport; this plugin builds each
upload request and reads Imgur's JSON answer (the Python upload path). It
also manages UI, configuration validation, and API key handling.
"""

from typing import Dict, Any, List
from .base import ImageHostPlugin
from . import helpers
from ..upload_results import UploadResult, json_parser_options, parse_json_upload


class ImgurPlugin(ImageHostPlugin):
    """Imgur image hosting plugin using schema-based UI."""

    THUMBNAIL_SIZE_LABELS = {
        "s": "Small square (90x90)",
        "b": "Large square (160x160)",
        "t": "Small (160 px)",
        "m": "Medium (320 px)",
        "l": "Large (640 px)",
        "h": "Huge (1024 px)",
    }
    DEFAULT_THUMBNAIL_SIZE = "m"

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
            "version": "3.1.3",
            "author": "Connie's Uploader Team",
            "description": "Upload images to Imgur with anonymous or authenticated uploads, album support, and automatic thumbnail generation",
            "website": "https://imgur.com",
            "implementation": "python",  # Python upload path; the sidecar is its transport
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
                "allowed_formats": [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".apng",
                    ".tiff",
                    ".mp4",
                    ".webm",
                ],
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
                "type": "dropdown",
                "key": "thumbnail_size",
                "label": "Thumbnail Size",
                "values": list(self.THUMBNAIL_SIZE_LABELS),
                "value_labels": self.THUMBNAIL_SIZE_LABELS,
                "default": self.DEFAULT_THUMBNAIL_SIZE,
                "required": True,
                "help": "Controls the thumbnail size used in generated output.",
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
                "advanced": True,
            },
            {
                "type": "separator",
                "advanced": True,
            },
            {
                "type": "text",
                "key": "album_id",
                "label": "Album ID (Optional)",
                "default": "",
                "placeholder": "Leave blank for no album",
                "help": "Imgur album ID to add images to",
                "advanced": True,
            },
            {
                "type": "text",
                "key": "title",
                "label": "Image Title (Optional)",
                "default": "",
                "placeholder": "Leave blank for filename",
                "help": "Title for uploaded images",
                "advanced": True,
            },
        ]

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """Custom validation for Imgur configuration."""
        errors = []

        # Validate thumbnail size
        valid_sizes = list(self.THUMBNAIL_SIZE_LABELS)
        selected_size = str(config.get("thumbnail_size", ""))
        if selected_size in self.THUMBNAIL_SIZE_LABELS.values():
            selected_size = next(
                code for code, label in self.THUMBNAIL_SIZE_LABELS.items() if label == selected_size
            )
            config["thumbnail_size"] = selected_size

        if selected_size not in valid_sizes:
            errors.append(f"Invalid thumbnail size. Must be one of: {', '.join(valid_sizes)}")

        # Convert content type to Imgur's mature flag
        content = config.get("content_type", "Safe")
        config["mature"] = content == "NSFW"

        return errors

    # --- Upload Implementation ---

    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build an Imgur API upload request for the Go generic HTTP runner."""
        access_token = str(creds.get("imgur_access_token", "")).strip()
        client_id = str(creds.get("imgur_client_id", "")).strip()

        if access_token:
            authorization = f"Bearer {access_token}"
        elif client_id:
            authorization = f"Client-ID {client_id}"
        else:
            raise ValueError(
                "Imgur uploads require an imgur_client_id for anonymous uploads "
                "or an imgur_access_token for authenticated uploads."
            )

        multipart_fields: Dict[str, Dict[str, str]] = {
            "image": {"type": "file", "value": file_path},
            "type": {"type": "text", "value": "file"},
        }

        album_id = str(config.get("album_id", "")).strip()
        if album_id:
            multipart_fields["album"] = {"type": "text", "value": album_id}

        title = str(config.get("title", "")).strip()
        if title:
            multipart_fields["title"] = {"type": "text", "value": title}

        # Imgur serves thumbnails at the image link with a size letter appended
        # to the image id, before the extension (AbCd123.jpg -> AbCd123m.jpg).
        size = self._thumbnail_suffix(config.get("thumbnail_size") or config.get("imgur_thumb"))

        return {
            "url": "https://api.imgur.com/3/image",
            "method": "POST",
            "headers": {
                "Authorization": authorization,
                "Accept": "application/json",
            },
            "multipart_fields": multipart_fields,
            "response_parser": self._response_parser(size),
        }

    @staticmethod
    def _response_parser(size: str) -> Dict[str, str]:
        """How Imgur answers; shared by the legacy spec and the Python parser."""
        return {
            "type": "json",
            "url_path": "data.link",
            "thumb_path": "",
            "thumb_template": "{url_no_ext}" + size + "{url_dot_ext}",
            "status_path": "success",
            "success_value": "true",
        }

    # --- Python upload path ---

    def open_upload_session(self, transport, config: Dict[str, Any], creds: Dict[str, Any]):
        """No login: carry the job's thumbnail size letter to the parser."""
        return {
            "thumbnail_size": self._thumbnail_suffix(
                config.get("thumbnail_size") or config.get("imgur_thumb")
            )
        }

    def build_raw_upload_request(
        self,
        file_path: str,
        config: Dict[str, Any],
        session_values: Dict[str, str],
        creds: Dict[str, Any],
    ) -> Dict[str, Any]:
        """The same request as the legacy spec: Imgur's API needs no session."""
        return helpers.raw_request_from_spec(self.build_http_request(file_path, config, creds))

    def parse_upload_response(
        self, file_path, response, transport, session_values, session_state
    ) -> UploadResult:
        size = self._thumbnail_suffix(session_values.get("thumbnail_size"))
        return parse_json_upload(
            response,
            file_path=file_path,
            secrets=session_state.secrets,
            **json_parser_options(self._response_parser(size)),
        )

    @classmethod
    def _thumbnail_suffix(cls, value: Any) -> str:
        """Map a Thumbnail Size setting (letter or label) to Imgur's size letter."""
        text = str(value or "").strip()
        if text in cls.THUMBNAIL_SIZE_LABELS:
            return text
        for code, label in cls.THUMBNAIL_SIZE_LABELS.items():
            if text == label:
                return code
        return cls.DEFAULT_THUMBNAIL_SIZE

    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """Stub - Go sidecar handles session initialization."""
        return {}

    def upload_file(
        self,
        file_path: str,
        group,
        config: Dict[str, Any],
        context: Dict[str, Any],
        progress_callback,
    ):
        """Stub - Go sidecar handles file uploads."""
        pass
