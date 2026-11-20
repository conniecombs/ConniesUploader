# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

# modules/settings_manager.py
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger
from . import config
from .exceptions import InvalidConfigException

try:
    from jsonschema import Draft7Validator, validate, ValidationError as JsonSchemaValidationError

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not installed - configuration validation disabled")

# Secrets live in the keyring, never in the settings file. An older bug wrote
# the IMX API key here as "api_key".
_SECRET_KEYS = ("api_key",)
_UNREPAIRABLE = object()


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
                "description": "Sidecar job-pool size (how many batch jobs can run); not the per-file concurrency",
            },
            "global_thread_limit": {
                "type": "integer",
                "minimum": config.MIN_THREAD_COUNT,
                "maximum": config.MAX_THREAD_COUNT,
                "description": "Simultaneous file uploads per host job (primary speed control)",
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
            "imagebam_gallery_id": {"type": "string"},
        },
        "additionalProperties": True,  # Allow extra fields for forward compatibility
    }

    def __init__(self):
        self.filepath = config.SETTINGS_FILE
        # Set by load(): details of an unreadable settings file that was
        # backed up and replaced by defaults, for a notice at startup.
        self.recovery_issue: Optional[Dict[str, Any]] = None
        # Notes on the values repaired by the last load() or save().
        self.repairs: List[str] = []
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
            "turbo_thumb": "200",
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
                shutil.move(legacy_path, target_path)
                logger.warning(
                    "Migrated legacy repo-local settings file to user data directory: "
                    f"{target_path}"
                )
                return

            backup_path = self._unique_backup_path(target_dir)
            shutil.move(legacy_path, backup_path)
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
                if isinstance(cover_count, bool) or not isinstance(cover_count, (int, float)):
                    continue  # wrong type: reported by the JSON schema check
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

    @staticmethod
    def _coerce_value(value: Any, schema: Dict[str, Any]) -> Any:
        """Convert a wrongly typed value to the schema's type, if unambiguous."""
        expected = schema.get("type")
        if isinstance(value, bool):
            return _UNREPAIRABLE
        if expected == "integer":
            if isinstance(value, float) and value.is_integer():
                number = int(value)
            elif isinstance(value, str) and re.fullmatch(r"\s*[+-]?[0-9]+\s*", value):
                number = int(value)
            elif isinstance(value, int):
                number = value
            else:
                return _UNREPAIRABLE
            if "minimum" in schema:
                number = max(schema["minimum"], number)
            if "maximum" in schema:
                number = min(schema["maximum"], number)
            return number
        if expected == "string" and isinstance(value, (int, float)):
            return str(value)
        if expected == "boolean" and isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "false"):
                return lowered == "true"
        return _UNREPAIRABLE

    def _repair_settings(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Fix only the keys that are invalid; keep everything else.

        A wrong value is converted when that is unambiguous ("3" -> 3, 11 -> 10
        for a 0-10 count, 350 -> "350"), otherwise reset to its default, or
        dropped when it has none. Secrets are always removed.
        """
        repaired = dict(data)
        notes = []
        for key in _SECRET_KEYS:
            if key in repaired:
                del repaired[key]
                notes.append(f"{key}: removed (secrets are kept in the keyring)")
        if not JSONSCHEMA_AVAILABLE:
            return repaired, notes

        for key, schema in self.SETTINGS_SCHEMA["properties"].items():
            if key not in repaired:
                continue
            value = repaired[key]
            validator = Draft7Validator(schema)
            if validator.is_valid(value):
                continue
            coerced = self._coerce_value(value, schema)
            if coerced is not _UNREPAIRABLE and validator.is_valid(coerced):
                repaired[key] = coerced
                notes.append(f"{key}: {value!r} -> {coerced!r}")
            elif key in self.defaults:
                repaired[key] = self.defaults[key]
                notes.append(f"{key}: {value!r} reset to default {self.defaults[key]!r}")
            else:
                del repaired[key]
                notes.append(f"{key}: {value!r} removed")
        return repaired, notes

    def _log_repairs(self, action: str) -> None:
        if self.repairs:
            logger.warning(
                f"Repaired settings while {action} {self.filepath}: " + "; ".join(self.repairs)
            )

    def get_recovery_issue(self) -> Optional[Dict[str, Any]]:
        """Details of a settings file that could not be read at load, if any."""
        if not self.recovery_issue:
            return None
        return dict(self.recovery_issue)

    def _backup_unreadable_file(self) -> Optional[str]:
        try:
            folder = os.path.dirname(os.path.abspath(self.filepath))
            base_name = os.path.basename(os.fspath(self.filepath))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = os.path.join(folder, f"{base_name}.broken-{stamp}.bak")
            counter = 1
            while os.path.exists(backup_path):
                backup_path = os.path.join(folder, f"{base_name}.broken-{stamp}-{counter}.bak")
                counter += 1
            shutil.copy2(self.filepath, backup_path)
            return backup_path
        except OSError as e:
            logger.error(f"Could not back up unreadable settings file: {e}")
            return None

    def _recover_unreadable_file(self, error: Exception) -> Dict[str, Any]:
        """Back up an unreadable settings file and start over from defaults."""
        logger.error(f"Settings file {self.filepath} could not be read ({error}); using defaults.")
        backup_path = self._backup_unreadable_file()
        if backup_path:
            # Only overwrite once the original is safely copied.
            try:
                self._write_atomic(json.dumps(self.defaults, indent=4))
            except OSError as e:
                logger.error(f"Could not replace unreadable settings file: {e}")
        self.recovery_issue = {
            "filepath": os.path.abspath(self.filepath),
            "backup_path": backup_path,
            "error": str(error),
        }
        return dict(self.defaults)

    def _write_atomic(self, text: str) -> None:
        """Write the settings file via a temp file in the same folder + os.replace."""
        target = os.fspath(self.filepath)
        folder = os.path.dirname(os.path.abspath(target))
        os.makedirs(folder, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(target)}.", suffix=".tmp", dir=folder
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self):
        """Load settings from file with validation.

        Never raises for a bad file: invalid values are repaired key by key
        (see _repair_settings) and an unreadable file is backed up and replaced
        by defaults, with the details in get_recovery_issue().

        Returns:
            Settings dictionary (defaults merged with loaded settings)
        """
        self.recovery_issue = None
        self.repairs = []
        if not os.path.exists(self.filepath):
            return dict(self.defaults)

        try:
            # utf-8-sig also reads files an editor saved with a byte order mark.
            with open(self.filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"expected a JSON object, found {type(data).__name__}")
        except (OSError, ValueError) as e:  # JSONDecodeError/UnicodeDecodeError are ValueErrors
            return self._recover_unreadable_file(e)

        try:
            # Merge with defaults. Older settings files did not have a global
            # thread limit, so seed it from the previous representative value.
            merged_input = {**self.defaults, **data}
            merged_input["service"] = config.normalize_service_id(merged_input.get("service", ""))
            if "global_thread_limit" not in data:
                merged_input["global_thread_limit"] = data.get(
                    "imx_threads", self.defaults["global_thread_limit"]
                )
            merged = self.normalize_numeric_ranges(merged_input)
            merged, self.repairs = self._repair_settings(merged)
            self._log_repairs("loading")

            validation_errors = self.validate_settings(merged)
            if validation_errors:
                raise InvalidConfigException("\n".join(validation_errors))
        except Exception as e:
            return self._recover_unreadable_file(e)

        if any(key in data for key in _SECRET_KEYS):
            # Remove the stored secret from disk now, not at the next save.
            try:
                self._write_atomic(json.dumps(merged, indent=4))
            except (OSError, TypeError, ValueError) as e:
                logger.error(f"Could not remove stored secret from settings file: {e}")
        return merged

    def save(self, data):
        """Save settings to file with validation.

        Invalid values are repaired first (secrets are never written); the file
        is replaced atomically, so a failed save leaves the old file intact.

        Args:
            data: Settings dictionary to save

        Raises:
            InvalidConfigException: If data contains invalid configuration
        """
        data = dict(data or {})
        data["service"] = config.normalize_service_id(data.get("service", ""))
        data = self.normalize_numeric_ranges(data)
        data, self.repairs = self._repair_settings(data)
        self._log_repairs("saving")

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
            # Serialise before touching the file: an unserialisable value must
            # not leave a truncated settings file behind.
            payload = json.dumps(data, indent=4)
            self._write_atomic(payload)
            logger.info(f"Settings saved to {self.filepath}")
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to save settings: {e}")
            raise InvalidConfigException(f"Failed to save settings: {e}") from e
