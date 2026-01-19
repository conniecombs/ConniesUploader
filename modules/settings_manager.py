# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/settings_manager.py
import json
import os
from typing import Dict, Any, List
from loguru import logger
from . import config
from .exceptions import InvalidConfigException

try:
    from jsonschema import validate, ValidationError as JsonSchemaValidationError

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not installed - configuration validation disabled")


class SettingsManager:
    # JSON Schema for settings validation
    SETTINGS_SCHEMA = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "enum": ["imx.to", "pixhost.to", "turboimagehost", "vipr.im", "imagebam.com"],
                "description": "Selected image hosting service",
            },
            "global_worker_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Number of concurrent upload workers",
            },
            # IMX settings
            "imx_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "imx_format": {"type": "string"},
            "imx_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "imx_links": {"type": "boolean"},
            "imx_threads": {"type": "integer", "minimum": 1, "maximum": 20},
            # Pixhost settings
            "pix_content": {"type": "string", "enum": ["Safe", "Adult"]},
            "pix_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "pix_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "pix_links": {"type": "boolean"},
            "pix_mk_gal": {"type": "boolean"},
            "pix_threads": {"type": "integer", "minimum": 1, "maximum": 20},
            # TurboImageHost settings
            "turbo_content": {"type": "string"},
            "turbo_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "turbo_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "turbo_threads": {"type": "integer", "minimum": 1, "maximum": 20},
            # Output settings
            "output_format": {"type": "string"},
            "auto_copy": {"type": "boolean"},
            "separate_batches": {"type": "boolean"},
            "show_previews": {"type": "boolean"},
            # Vipr settings
            "vipr_thumb": {"type": "string"},
            "vipr_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "vipr_threads": {"type": "integer", "minimum": 1, "maximum": 20},
            # ImageBam settings
            "imagebam_content": {"type": "string"},
            "imagebam_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "imagebam_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "imagebam_threads": {"type": "integer", "minimum": 1, "maximum": 20},
            # Optional fields (for future expansion)
            "auto_gallery": {"type": "boolean"},
            "gallery_id": {"type": "string"},
            "pix_gallery_hash": {"type": "string"},
        },
        "additionalProperties": True,  # Allow extra fields for forward compatibility
    }

    def __init__(self):
        self.filepath = config.SETTINGS_FILE
        # UPDATED: Changed booleans (*_cover) to integers (*_cover_count)
        self.defaults = {
            "service": "imx.to",
            "global_worker_count": 8,  # Main job queue dispatcher workers
            "imx_thumb": "180",
            "imx_format": "Fixed Width",
            "imx_cover_count": 0,  # Was imx_cover
            "imx_links": False,
            "imx_threads": 5,
            "pix_content": "Safe",
            "pix_thumb": "200",
            "pix_cover_count": 0,  # Was pix_cover
            "pix_links": False,
            "pix_mk_gal": False,
            "pix_threads": 3,
            "turbo_content": "Safe",
            "turbo_thumb": "180",
            "turbo_cover_count": 0,  # Was turbo_cover
            "turbo_threads": 2,
            "output_format": "BBCode",
            "auto_copy": False,
            "separate_batches": False,
            "show_previews": True,
            # Viper/ImageBam Defaults
            "vipr_thumb": "170x170",
            "vipr_cover_count": 0,  # Was vipr_cover
            "vipr_threads": 1,
            "imagebam_content": "Safe",
            "imagebam_thumb": "180",
            # ImageBam doesn't typically have a specific "Cover" setting in API,
            # but we'll add the key for consistency if needed later.
            "imagebam_cover_count": 0,
            "imagebam_threads": 2,
        }

    def validate_settings(self, data: Dict[str, Any]) -> List[str]:
        """Validate settings against the JSON schema.

        Args:
            data: Settings dictionary to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not JSONSCHEMA_AVAILABLE:
            # Skip validation if jsonschema not installed
            return errors

        try:
            validate(instance=data, schema=self.SETTINGS_SCHEMA)
        except JsonSchemaValidationError as e:
            # Extract user-friendly error message
            error_path = " -> ".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
            errors.append(f"Configuration error at '{error_path}': {e.message}")

        # Additional custom validation
        errors.extend(self._custom_validation(data))

        return errors

    def _custom_validation(self, data: Dict[str, Any]) -> List[str]:
        """Perform custom validation beyond JSON schema.

        Args:
            data: Settings dictionary to validate

        Returns:
            List of validation error messages
        """
        errors = []

        # Validate thread counts are consistent
        if data.get("global_worker_count", 0) > config.MAX_THREAD_COUNT:
            errors.append(
                f"global_worker_count ({data['global_worker_count']}) exceeds maximum ({config.MAX_THREAD_COUNT})"
            )

        # Validate cover counts don't exceed total
        for service_prefix in ["imx", "pix", "turbo", "vipr", "imagebam"]:
            cover_key = f"{service_prefix}_cover_count"
            if cover_key in data:
                cover_count = data[cover_key]
                if cover_count < 0:
                    errors.append(f"{cover_key} cannot be negative")
                elif cover_count > 10:
                    errors.append(f"{cover_key} cannot exceed 10")

        return errors

    def load(self):
        """Load settings from file with validation.

        Returns:
            Settings dictionary (defaults merged with loaded settings)

        Raises:
            InvalidConfigException: If settings file contains invalid configuration
        """
        if not os.path.exists(self.filepath):
            return self.defaults

        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)

            # Merge with defaults
            merged = {**self.defaults, **data}

            # Validate the loaded settings
            validation_errors = self.validate_settings(merged)
            if validation_errors:
                error_msg = "\n".join(validation_errors)
                logger.error(f"Invalid configuration in {self.filepath}:\n{error_msg}")

                # Raise exception if validation fails
                if JSONSCHEMA_AVAILABLE:
                    raise InvalidConfigException(
                        f"Configuration file '{self.filepath}' contains errors:\n{error_msg}"
                    )
                else:
                    # Just warn if jsonschema not available
                    logger.warning("Configuration validation skipped (jsonschema not installed)")

            return merged

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {self.filepath}: {e}")
            raise InvalidConfigException(
                f"Configuration file '{self.filepath}' contains invalid JSON: {e}"
            )
        except InvalidConfigException:
            # Re-raise config exceptions
            raise
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return self.defaults

    def save(self, data):
        """Save settings to file with validation.

        Args:
            data: Settings dictionary to save

        Raises:
            InvalidConfigException: If data contains invalid configuration
        """
        # Validate before saving
        validation_errors = self.validate_settings(data)
        if validation_errors:
            error_msg = "\n".join(validation_errors)
            logger.error(f"Cannot save invalid configuration:\n{error_msg}")

            if JSONSCHEMA_AVAILABLE:
                raise InvalidConfigException(f"Cannot save invalid configuration:\n{error_msg}")
            else:
                logger.warning("Saving without validation (jsonschema not installed)")

        try:
            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=4)
            logger.info(f"Settings saved to {self.filepath}")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise InvalidConfigException(f"Failed to save settings: {e}")
