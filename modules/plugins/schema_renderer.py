# modules/plugins/schema_renderer.py
"""
Schema-based UI rendering for plugins.

This module provides automatic UI generation from declarative schemas,
eliminating the need for manual widget creation in plugins.
"""

from typing import Dict, List, Any, Optional, Tuple
import customtkinter as ctk
from loguru import logger
from ..widgets import MouseWheelComboBox


class ValidationError(Exception):
    """Raised when plugin configuration validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Validation failed: {', '.join(errors)}")


class SchemaRenderer:
    """
    Automatically generates UI widgets from plugin schema definitions.

    Schema Format:
        [
            {
                "type": "dropdown",      # Widget type
                "key": "thumb_size",     # Config key
                "label": "Thumbnail Size",
                "values": ["100", "200", "300"],
                "default": "200",
                "required": True,
                "help": "Optional tooltip"
            },
            {
                "type": "checkbox",
                "key": "save_links",
                "label": "Save Links.txt",
                "default": False
            },
            # ... more fields
        ]

    Supported Field Types:
        - dropdown: Combo box with predefined values
        - checkbox: Boolean checkbox
        - number: Number input with min/max validation
        - text: Text entry field
        - label: Information label (no config output)
        - separator: Visual separator line
    """

    def render(
        self, parent: ctk.CTkFrame, schema: List[Dict], current_settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Creates UI widgets from schema definition.

        Args:
            parent: Parent frame to render widgets into
            schema: List of field definitions
            current_settings: Current saved settings values

        Returns:
            Dictionary mapping field keys to Tkinter variables
        """
        ui_vars = {}

        for field in schema:
            field_type = field.get("type", "text")

            if field_type == "dropdown":
                self._render_dropdown(parent, field, current_settings, ui_vars)
            elif field_type == "checkbox":
                self._render_checkbox(parent, field, current_settings, ui_vars)
            elif field_type == "number":
                self._render_number(parent, field, current_settings, ui_vars)
            elif field_type == "text":
                self._render_text(parent, field, current_settings, ui_vars)
            elif field_type == "label":
                self._render_label(parent, field)
            elif field_type == "separator":
                self._render_separator(parent, field)
            elif field_type == "inline_group":
                self._render_inline_group(parent, field, current_settings, ui_vars)
            else:
                logger.warning(f"Unknown field type: {field_type}")

        return ui_vars

    def _render_dropdown(
        self,
        parent: ctk.CTkFrame,
        field: Dict,
        settings: Dict,
        ui_vars: Dict,
    ) -> None:
        """Render a dropdown/combobox field."""
        key = field["key"]
        label = field.get("label", key)
        values = field.get("values", [])
        default = field.get("default", values[0] if values else "")
        current = settings.get(key, default)

        # Label
        label_widget = ctk.CTkLabel(parent, text=label)
        label_widget.pack(anchor="w", pady=(5, 0))

        # Add help tooltip if provided
        if field.get("help"):
            self._add_tooltip(label_widget, field["help"])

        # Variable
        var = ctk.StringVar(value=str(current))
        ui_vars[key] = var

        # Widget
        combo = MouseWheelComboBox(parent, variable=var, values=values)
        combo.pack(fill="x", pady=(0, 5))

    def _render_checkbox(
        self,
        parent: ctk.CTkFrame,
        field: Dict,
        settings: Dict,
        ui_vars: Dict,
    ) -> None:
        """Render a checkbox field."""
        key = field["key"]
        label = field.get("label", key)
        default = field.get("default", False)
        current = settings.get(key, default)

        # Variable
        var = ctk.BooleanVar(value=bool(current))
        ui_vars[key] = var

        # Widget
        checkbox = ctk.CTkCheckBox(parent, text=label, variable=var)
        checkbox.pack(anchor="w", pady=5)

        if field.get("help"):
            self._add_tooltip(checkbox, field["help"])

    def _render_number(
        self,
        parent: ctk.CTkFrame,
        field: Dict,
        settings: Dict,
        ui_vars: Dict,
    ) -> None:
        """Render a number input field."""
        key = field["key"]
        label = field.get("label", key)
        default = field.get("default", 0)
        current = settings.get(key, default)
        min_val = field.get("min", 0)
        max_val = field.get("max", 100)

        # Create dropdown with numeric range
        values = [str(i) for i in range(min_val, max_val + 1)]

        # Label
        label_widget = ctk.CTkLabel(parent, text=label)
        label_widget.pack(anchor="w", pady=(5, 0))

        if field.get("help"):
            self._add_tooltip(label_widget, field["help"])

        # Variable
        var = ctk.StringVar(value=str(current))
        ui_vars[key] = var

        # Widget
        combo = MouseWheelComboBox(parent, variable=var, values=values)
        combo.pack(fill="x", pady=(0, 5))

    def _render_text(
        self,
        parent: ctk.CTkFrame,
        field: Dict,
        settings: Dict,
        ui_vars: Dict,
    ) -> None:
        """Render a text entry field."""
        key = field["key"]
        label = field.get("label", key)
        default = field.get("default", "")
        current = settings.get(key, default)
        placeholder = field.get("placeholder", "")

        # Label
        label_widget = ctk.CTkLabel(parent, text=label)
        label_widget.pack(anchor="w", pady=(5, 0))

        if field.get("help"):
            self._add_tooltip(label_widget, field["help"])

        # Variable
        var = ctk.StringVar(value=str(current))
        ui_vars[key] = var

        # Widget
        entry = ctk.CTkEntry(parent, textvariable=var, placeholder_text=placeholder)
        entry.pack(fill="x", pady=(0, 5))

    def _render_label(self, parent: ctk.CTkFrame, field: Dict) -> None:
        """Render an information label."""
        text = field.get("text", "")
        color = field.get("color", None)

        label = ctk.CTkLabel(parent, text=text)
        if color:
            label.configure(text_color=color)
        label.pack(pady=5)

    def _render_separator(self, parent: ctk.CTkFrame, field: Dict) -> None:
        """Render a visual separator."""
        ctk.CTkLabel(parent, text="─" * 40, text_color="gray").pack(pady=5)

    def _render_inline_group(
        self,
        parent: ctk.CTkFrame,
        field: Dict,
        settings: Dict,
        ui_vars: Dict,
    ) -> None:
        """Render multiple fields in a horizontal row."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=5)

        fields = field.get("fields", [])
        for i, subfield in enumerate(fields):
            subfield_type = subfield.get("type")
            key = subfield["key"]

            if subfield_type == "label":
                label_text = subfield.get("text", "")
                width = subfield.get("width", 60)
                ctk.CTkLabel(frame, text=label_text, width=width).pack(
                    side="left", padx=(0, 5)
                )

            elif subfield_type == "dropdown":
                values = subfield.get("values", [])
                default = subfield.get("default", values[0] if values else "")
                current = settings.get(key, default)
                width = subfield.get("width", 80)

                var = ctk.StringVar(value=str(current))
                ui_vars[key] = var

                MouseWheelComboBox(frame, variable=var, values=values, width=width).pack(
                    side="left", padx=5
                )

    def _add_tooltip(self, widget, text: str) -> None:
        """Add tooltip to widget (placeholder for future implementation)."""
        # TODO: Implement actual tooltip functionality
        pass

    def extract_config(
        self, ui_vars: Dict[str, Any], schema: List[Dict]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Extracts configuration from UI variables with validation.

        Args:
            ui_vars: Dictionary of Tkinter variables from render()
            schema: Original schema definition

        Returns:
            Tuple of (config dict, list of validation errors)
        """
        config = {}
        errors = []

        for field in schema:
            # Skip non-config fields
            if field.get("type") in ["label", "separator"]:
                continue

            # Handle inline groups
            if field.get("type") == "inline_group":
                for subfield in field.get("fields", []):
                    if subfield.get("type") != "label":
                        self._extract_field_value(
                            subfield, ui_vars, config, errors
                        )
                continue

            self._extract_field_value(field, ui_vars, config, errors)

        return config, errors

    def _extract_field_value(
        self, field: Dict, ui_vars: Dict, config: Dict, errors: List[str]
    ) -> None:
        """Extract and validate a single field value."""
        key = field["key"]
        field_type = field.get("type", "text")
        label = field.get("label", key)

        if key not in ui_vars:
            logger.warning(f"Field {key} not found in ui_vars")
            return

        # Get value from variable
        value = ui_vars[key].get()

        # Validate required fields
        if field.get("required", False):
            if not value or (isinstance(value, str) and not value.strip()):
                errors.append(f"{label} is required")

        # Type-specific validation
        if field_type == "number":
            try:
                num_val = int(value) if value else field.get("default", 0)
                min_val = field.get("min", 0)
                max_val = field.get("max", 999999)

                if num_val < min_val or num_val > max_val:
                    errors.append(
                        f"{label} must be between {min_val} and {max_val}"
                    )

                config[key] = num_val
            except (ValueError, TypeError):
                errors.append(f"{label} must be a valid number")
                config[key] = field.get("default", 0)

        elif field_type == "checkbox":
            config[key] = bool(value)

        else:
            # text, dropdown, etc
            config[key] = str(value) if value else ""

        # Custom validation function
        if "validate" in field:
            custom_errors = field["validate"](config[key])
            if custom_errors:
                errors.extend(custom_errors if isinstance(custom_errors, list) else [custom_errors])
