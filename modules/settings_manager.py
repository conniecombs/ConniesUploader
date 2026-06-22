# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/settings_manager.py
import json
import os
from datetime import datetime
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
                "minLength": 1,
                "description": "Selected image hosting service",
            },
            "global_worker_count": {
                "type": "integer",
                "minimum": config.MIN_WORKER_COUNT,
                "maximum": config.MAX_WORKER_COUNT,
                "description": "Number of concurrent upload workers",
            },
            "global_thread_limit": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
                "description": "Maximum concurrent file uploads inside each sidecar job",
            },
            # IMX settings
            "imx_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "imx_format": {"type": "string"},
            "imx_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "imx_links": {"type": "boolean"},
            "imx_threads": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
            },
            # Pixhost settings
            "pix_content": {"type": "string", "enum": ["Safe", "Adult"]},
            "pix_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "pix_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "pix_links": {"type": "boolean"},
            "pix_mk_gal": {"type": "boolean"},
            "pix_threads": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
            },
            # TurboImageHost settings
            "turbo_content": {"type": "string"},
            "turbo_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "turbo_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "turbo_threads": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
            },
            # Output settings
            "output_format": {"type": "string"},
            "auto_copy": {"type": "boolean"},
            "confirm_before_posting": {"type": "boolean"},
            "separate_batches": {"type": "boolean"},
            "show_previews": {"type": "boolean"},
            # Vipr settings
            "vipr_thumb": {"type": "string"},
            "vipr_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "vipr_threads": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
            },
            # ImageBam settings
            "imagebam_content": {"type": "string"},
            "imagebam_thumb": {"type": "string", "pattern": "^[0-9]+$"},
            "imagebam_cover_count": {"type": "integer", "minimum": 0, "maximum": 10},
            "imagebam_threads": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
            },
            # Imgur settings
            "imgur_content": {"type": "string"},
            "imgur_thumb": {"type": "string"},
            "imgur_links": {"type": "boolean"},
            "imgur_album_id": {"type": "string"},
            "imgur_title": {"type": "string"},
            "imgur_threads": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
            },
            # Optional fields (for future expansion)
            "auto_gallery": {"type": "boolean"},
            "gallery_id": {"type": "string"},
            "imx_gallery_id": {"type": "string"},
            "pix_gallery_hash": {"type": "string"},
            "turbo_gallery_id": {"type": "string"},
        },
        "additionalProperties": True,  # Allow extra fields for forward compatibility
    }

    def __init__(self):
        self.filepath = config.SETTINGS_FILE
        self._migrate_legacy_repo_settings()
        # UPDATED: Changed booleans (*_cover) to integers (*_cover_count)
        self.defaults = {
            "service": "imx.to",
            "global_worker_count": config.DEFAULT_WORKER_COUNT,  # Main job queue dispatcher workers
            "global_thread_limit": config.DEFAULT_THREAD_COUNT,
            "imx_thumb": "180",
            "imx_format": "Fixed Width",
            "imx_cover_count": 0,  # Was imx_cover
            "imx_links": False,
            "imx_threads": config.DEFAULT_THREAD_COUNT,
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
            "confirm_before_posting": False,
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
            "imgur_content": "Safe",
            "imgur_thumb": "m",
            "imgur_links": False,
            "imgur_album_id": "",
            "imgur_title": "",
            "imgur_threads": 2,
            "imx_gallery_id": "",
            "turbo_gallery_id": "",
        }

    @staticmethod
    def _unique_backup_path(directory: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = os.path.join(directory, f"user_settings.repo-local-{timestamp}.json")
        if not os.path.exists(base):
            return base
        counter = 1
        while True:
            candidate = os.path.join(
                directory,
                f"user_settings.repo-local-{timestamp}-{counter}.json",
            )
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _migrate_legacy_repo_settings(self) -> None:
        """Move a legacy repo-local settings file into the user data directory."""
        legacy_path = getattr(config, "LEGACY_SETTINGS_FILE", None)
        if not legacy_path:
            return

        target_path = os.fspath(self.filepath)
        legacy_path = os.fspath(legacy_path)
        if os.path.abspath(legacy_path) == os.path.abspath(target_path):
            return
        if not os.path.exists(legacy_path):
            return

        target_dir = os.path.dirname(target_path)
        os.makedirs(target_dir, exist_ok=True)

        try:
            if not os.path.exists(target_path):
                os.replace(legacy_path, target_path)
                logger.warning(
                    "Migrated legacy repo-local settings file to user data directory: "
                    f"{target_path}"
                )
                return

            backup_path = self._unique_backup_path(target_dir)
            os.replace(legacy_path, backup_path)
            logger.warning(
                "Moved legacy repo-local settings file out of the repository without "
                f"overwriting existing settings: {backup_path}"
            )
        except OSError as e:
            logger.error(f"Failed to migrate legacy settings file out of repository: {e}")

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

        # Validate worker and upload thread counts are consistent with the UI.
        worker_count = data.get("global_worker_count", config.DEFAULT_WORKER_COUNT)
        try:
            worker_count = int(worker_count)
        except (TypeError, ValueError):
            worker_count = None
        if worker_count is not None:
            if worker_count < config.MIN_WORKER_COUNT:
                errors.append(
                    f"global_worker_count ({worker_count}) is below minimum ({config.MIN_WORKER_COUNT})"
                )
            elif worker_count > config.MAX_WORKER_COUNT:
                errors.append(
                    f"global_worker_count ({worker_count}) exceeds maximum ({config.MAX_WORKER_COUNT})"
                )

        global_thread_limit = data.get("global_thread_limit", config.DEFAULT_THREAD_COUNT)
        try:
            global_thread_limit = int(global_thread_limit)
        except (TypeError, ValueError):
            global_thread_limit = None
        if global_thread_limit is not None:
            if global_thread_limit < config.MIN_THREAD_COUNT:
                errors.append(
                    "global_thread_limit "
                    f"({global_thread_limit}) is below minimum ({config.MIN_THREAD_COUNT})"
                )
            elif global_thread_limit > config.MAX_THREAD_COUNT:
                errors.append(
                    "global_thread_limit "
                    f"({global_thread_limit}) exceeds maximum ({config.MAX_THREAD_COUNT})"
                )

        for thread_key in self._thread_count_keys():
            if thread_key not in data:
                continue
            thread_count = data[thread_key]
            try:
                thread_count = int(thread_count)
            except (TypeError, ValueError):
                continue
            if thread_count < config.MIN_THREAD_COUNT:
                errors.append(
                    f"{thread_key} ({thread_count}) is below minimum ({config.MIN_THREAD_COUNT})"
                )
            elif thread_count > config.MAX_THREAD_COUNT:
                errors.append(
                    f"{thread_key} ({thread_count}) exceeds maximum ({config.MAX_THREAD_COUNT})"
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

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    @staticmethod
    def _thread_count_keys() -> List[str]:
        return [
            "imx_threads",
            "pix_threads",
            "turbo_threads",
            "vipr_threads",
            "imagebam_threads",
            "imgur_threads",
        ]

    def normalize_numeric_ranges(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Return settings with worker and thread counts clamped to supported ranges."""
        normalized = data.copy()
        normalized["global_worker_count"] = self._clamp_int(
            normalized.get("global_worker_count"),
            config.DEFAULT_WORKER_COUNT,
            config.MIN_WORKER_COUNT,
            config.MAX_WORKER_COUNT,
        )
        normalized["global_thread_limit"] = self._clamp_int(
            normalized.get("global_thread_limit"),
            config.DEFAULT_THREAD_COUNT,
            config.MIN_THREAD_COUNT,
            config.MAX_THREAD_COUNT,
        )
        for thread_key in self._thread_count_keys():
            default = self.defaults.get(thread_key, config.DEFAULT_THREAD_COUNT)
            normalized[thread_key] = self._clamp_int(
                normalized.get(thread_key),
                default,
                config.MIN_THREAD_COUNT,
                config.MAX_THREAD_COUNT,
            )
        return normalized

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

            # Merge with defaults. Older settings files did not have a global
            # thread limit, so seed it from the previous representative value.
            merged_input = {**self.defaults, **data}
            if "global_thread_limit" not in data:
                merged_input["global_thread_limit"] = data.get(
                    "imx_threads", self.defaults["global_thread_limit"]
                )
            merged = self.normalize_numeric_ranges(merged_input)

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
        data = self.normalize_numeric_ranges(data)

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
            settings_dir = os.path.dirname(os.fspath(self.filepath))
            if settings_dir:
                os.makedirs(settings_dir, exist_ok=True)
            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=4)
            logger.info(f"Settings saved to {self.filepath}")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise InvalidConfigException(f"Failed to save settings: {e}")
