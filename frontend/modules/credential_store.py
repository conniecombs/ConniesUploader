# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""JSON credential storage for the Docker/web runtime."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from loguru import logger

from . import config
from .credential_schema import credential_fields, credential_keys


class JsonCredentialStore:
    """Store web-runtime credentials in a sensitive JSON file under /data."""

    def __init__(self, filepath: str | None = None) -> None:
        self.filepath = filepath or os.path.join(config.USER_DATA_DIR, "credentials.json")
        self._known_keys = set(credential_keys())

    def metadata(self) -> List[Dict[str, Any]]:
        return credential_fields()

    def load_all(self) -> Dict[str, str]:
        data = self._read()
        return {key: str(data.get(key) or "") for key in sorted(self._known_keys)}

    def status(self) -> Dict[str, Any]:
        values = self.load_all()
        return {
            "storage": "file",
            "fields": [
                {
                    **field,
                    "present": bool(values.get(field["key"])),
                }
                for field in self.metadata()
            ],
        }

    def update(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        current = self.load_all()
        for key, value in credentials.items():
            if key not in self._known_keys:
                continue
            current[key] = str(value or "").strip()
        self._write(current)
        return self.status()

    def _read(self) -> Dict[str, str]:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            logger.error(f"Could not parse web credential store: {exc}")
            return {}
        except OSError as exc:
            logger.error(f"Could not read web credential store: {exc}")
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: Dict[str, str]) -> None:
        directory = os.path.dirname(self.filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f"{self.filepath}.tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, self.filepath)
        try:
            os.chmod(self.filepath, 0o600)
        except OSError:
            pass
