# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/plugins/base.py
import abc
from typing import Dict, Any, Tuple, Optional, List
import customtkinter as ctk
from loguru import logger


class ImageHostPlugin(abc.ABC):
    @property
    @abc.abstractmethod
    def id(self) -> str:
        """Unique identifier (e.g., 'imx.to')"""
        pass

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Display name (e.g., 'IMX.to')"""
        pass

    # --- Phase 2: Plugin Metadata ---

    @property
    def metadata(self) -> Dict[str, Any]:
        """
        Plugin metadata for documentation, validation, and feature detection.

        Returns a dictionary containing plugin information:

        Example:
            {
                "version": "2.0.0",
                "author": "Plugin Developer",
                "description": "Upload images to ServiceName with gallery support",
                "website": "https://servicenam.com",
                "implementation": "python",  # "python" or "go"
                "features": {
                    "galleries": True,
                    "covers": True,
                    "authentication": "optional",  # "required", "optional", "none"
                    "direct_links": True,
                    "custom_thumbnails": True
                },
                "credentials": [
                    {
                        "key": "service_user",
                        "label": "Username",
                        "required": False,
                        "description": "Optional login for private galleries"
                    },
                    {
                        "key": "service_pass",
                        "label": "Password",
                        "required": False,
                        "secret": True
                    }
                ],
                "limits": {
                    "max_file_size": 50 * 1024 * 1024,  # 50MB in bytes
                    "allowed_formats": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
                    "rate_limit": "100/hour",
                    "max_resolution": (10000, 10000),  # (width, height)
                    "min_resolution": (100, 100)
                }
            }

        All fields are optional except version. Recommended fields:
            - version: Plugin version (semver recommended)
            - author: Plugin maintainer
            - description: One-line description
            - implementation: "python" or "go"
            - features: Dictionary of supported features
            - credentials: List of required/optional credentials
            - limits: Service limitations

        This metadata is used for:
            - Plugin documentation
            - Feature detection
            - File validation before upload
            - Credential validation
            - User guidance
        """
        return {
            "version": "1.0.0",
            "author": "Unknown",
            "description": "Image hosting plugin",
            "implementation": "python",
        }

    # --- NEW: Schema-Based Settings (Recommended) ---

    @property
    def settings_schema(self) -> List[Dict[str, Any]]:
        """
        Declarative UI schema for plugin settings.

        Returns a list of field definitions that will be auto-rendered.

        Example:
            [
                {
                    "type": "dropdown",
                    "key": "thumb_size",
                    "label": "Thumbnail Size",
                    "values": ["100", "200", "300"],
                    "default": "200",
                    "required": True,
                    "help": "Size of thumbnail images"
                },
                {
                    "type": "checkbox",
                    "key": "save_links",
                    "label": "Save Links.txt",
                    "default": False
                }
            ]

        Supported field types:
            - dropdown: Combo box with predefined values
            - checkbox: Boolean checkbox
            - number: Number input with min/max validation
            - text: Text entry field
            - label: Information label (no config output)
            - separator: Visual separator line
            - inline_group: Multiple fields in a row

        Field properties:
            - type: Widget type (required)
            - key: Configuration key (required for data fields)
            - label: Display label
            - default: Default value
            - required: Whether field is required
            - help: Tooltip text (future feature)
            - values: Available options (for dropdown)
            - min/max: Range limits (for number)
            - placeholder: Placeholder text (for text)
            - validate: Custom validation function

        If this returns an empty list, falls back to legacy render_settings().
        """
        return []

    def validate_configuration(self, config: Dict[str, Any]) -> List[str]:
        """
        Optional: Custom validation logic beyond schema validation.

        Args:
            config: Configuration dictionary extracted from UI

        Returns:
            List of error messages (empty if valid)

        Example:
            def validate_configuration(self, config):
                errors = []
                if config.get('gallery_id') and not config['gallery_id'].isalnum():
                    errors.append("Gallery ID must be alphanumeric")
                return errors
        """
        return []

    # --- LEGACY: Manual UI Methods (Backward Compatible) ---

    def render_settings(self, parent: ctk.CTkFrame, current_settings: Dict[str, Any]) -> Any:
        """
        Draws the settings widgets into 'parent'.
        Returns a 'ui_handle' (object/dict) containing the Tkinter variables
        needed to retrieve values later.

        NOTE: This method is LEGACY. New plugins should use settings_schema instead.

        If settings_schema is provided, this method is auto-generated.
        Only override this if you need custom UI logic that can't be expressed in schema.
        """
        # Check if plugin uses new schema-based approach
        if self.settings_schema:
            from .schema_renderer import SchemaRenderer

            renderer = SchemaRenderer()
            return renderer.render(parent, self.settings_schema, current_settings)
        else:
            # Legacy plugins must implement this
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement either settings_schema or render_settings"
            )

    def get_configuration(self, ui_handle: Any) -> Dict[str, Any]:
        """
        Called when Start Upload is clicked.
        Extracts values from the 'ui_handle' into a plain dictionary.

        NOTE: This method is LEGACY. New plugins should use settings_schema instead.

        If settings_schema is provided, this method is auto-generated with validation.
        Only override this if you need custom extraction logic.
        """
        # Check if plugin uses new schema-based approach
        if self.settings_schema:
            from .schema_renderer import SchemaRenderer, ValidationError

            renderer = SchemaRenderer()
            config, errors = renderer.extract_config(ui_handle, self.settings_schema)

            # Add custom validation
            custom_errors = self.validate_configuration(config)
            if custom_errors:
                errors.extend(custom_errors)

            # Raise if validation failed
            if errors:
                raise ValidationError(errors)

            return config
        else:
            # Legacy plugins must implement this
            raise NotImplementedError(
                f"{self.__class__.__name__} must implement either settings_schema or get_configuration"
            )

    # --- Worker Methods (Background Thread) ---

    @abc.abstractmethod
    def initialize_session(self, config: Dict[str, Any], creds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs once per batch start. Performs login, fetches global tokens.
        Returns a 'context' dict passed to subsequent methods.
        """
        pass

    def prepare_group(
        self,
        group_info: Any,
        config: Dict[str, Any],
        context: Dict[str, Any],
        creds: Dict[str, Any],
    ) -> None:
        """
        Optional: Runs before processing a specific group of files.
        Used for creating galleries per folder (e.g., IMX, Pixhost).
        Modifies 'context' or 'group_info' in place.
        """
        pass

    @abc.abstractmethod
    def upload_file(
        self,
        file_path: str,
        group_info: Any,
        config: Dict[str, Any],
        context: Dict[str, Any],
        progress_callback,
    ) -> Tuple[str, str]:
        """
        Uploads a single file.
        Returns: (viewer_url, thumb_url)
        """
        pass

    def build_http_request(
        self, file_path: str, config: Dict[str, Any], creds: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        NEW: Build a generic HTTP request specification for Go sidecar execution.

        This allows plugins to define uploads declaratively without hardcoding service
        logic in Go. The Go sidecar becomes a "dumb HTTP runner" that executes
        requests based on this spec.

        Returns a dictionary with the HTTP request specification:
        {
            "url": "https://api.example.com/upload",
            "method": "POST",
            "headers": {
                "X-API-KEY": "...",
                "User-Agent": "..."
            },
            "multipart_fields": {
                "image": {"type": "file", "value": "/path/to/file.jpg"},
                "format": {"type": "text", "value": "json"},
                "thumbnail_size": {"type": "text", "value": "180"}
            },
            "response_parser": {
                "type": "json",  # or "html"
                "url_path": "data.image_url",  # JSONPath for image URL
                "thumb_path": "data.thumbnail_url",  # JSONPath for thumbnail URL
                "status_path": "status",  # JSONPath for status field
                "success_value": "success"  # Expected value for success
            }
        }

        If this method returns None, the upload falls back to legacy upload_file() method.
        """
        return None

    def finalize_batch(self, context: Dict[str, Any]) -> None:
        """Optional: Runs after all uploads are finished."""
        pass
