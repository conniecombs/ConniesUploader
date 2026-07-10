# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Persistent local account storage for the web runtime."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any

from modules import config

HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 390000
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]+$")


class AccountValidationError(ValueError):
    """Raised when a web account setup request is invalid."""


class WebAccountStore:
    """Read and write the single local web account."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or config.WEB_AUTH_FILE).expanduser()

    def exists(self) -> bool:
        return bool(self._read().get("account"))

    def username(self) -> str:
        account = self._read().get("account") or {}
        return str(account.get("username") or "")

    def create_account(self, username: str, password: str) -> dict[str, Any]:
        username = validate_username(username)
        validate_password(password)
        data = self._read()
        if data.get("account"):
            raise AccountValidationError("A web account already exists.")

        now = datetime.now(timezone.utc).isoformat()
        data["account"] = {
            "username": username,
            "algorithm": HASH_ALGORITHM,
            "iterations": HASH_ITERATIONS,
            "salt": _encode(secrets.token_bytes(24)),
            "created_at": now,
            "updated_at": now,
        }
        data["account"]["password_hash"] = _hash_password(
            password,
            data["account"]["salt"],
            data["account"]["iterations"],
        )
        data.setdefault("session_secret", _encode(secrets.token_bytes(32)))
        self._write(data)
        return {"username": username}

    def verify_password(self, username: str, password: str) -> bool:
        account = self._read().get("account") or {}
        if account.get("algorithm") != HASH_ALGORITHM:
            return False
        if not hmac.compare_digest(str(username or ""), str(account.get("username") or "")):
            return False
        try:
            expected = str(account["password_hash"])
            actual = _hash_password(
                password,
                str(account["salt"]),
                int(account["iterations"]),
            )
        except (KeyError, TypeError, ValueError):
            return False
        return hmac.compare_digest(actual, expected)

    def session_secret(self) -> bytes | None:
        secret = self._read().get("session_secret")
        if not secret:
            return None
        try:
            return base64.urlsafe_b64decode(str(secret).encode("ascii"))
        except (ValueError, TypeError):
            return None

    def _read(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        temp = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(temp, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.write(b"\n")
            os.replace(temp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                temp.unlink()
            except OSError:
                pass
            raise


def validate_username(username: str) -> str:
    clean = str(username or "").strip()
    if not clean:
        raise AccountValidationError("Username is required.")
    if len(clean) > 64:
        raise AccountValidationError("Username must be 64 characters or fewer.")
    if not USERNAME_PATTERN.fullmatch(clean):
        raise AccountValidationError(
            "Username can use letters, numbers, dots, dashes, underscores, and @."
        )
    return clean


def validate_password(password: str) -> None:
    if len(str(password or "")) < MIN_PASSWORD_LENGTH:
        raise AccountValidationError("Password must be at least 8 characters.")


def _hash_password(password: str, salt: str, iterations: int) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        base64.urlsafe_b64decode(salt.encode("ascii")),
        iterations,
    )
    return _encode(digest)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")
