# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Shared credential field definitions for desktop and web runtimes."""

from __future__ import annotations

from typing import Any, Dict, List

from modules import config


SERVICE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "imx.to": {
        "label": "imx.to",
        "fields": [
            {
                "key": "imx_api",
                "label": "IMX API Key:",
                "keyring_service": config.KEYRING_SERVICE_API,
                "keyring_username": "api",
                "show": "*",
                "section": "API",
            },
            {
                "key": "imx_user",
                "label": "Username:",
                "keyring_service": config.KEYRING_SERVICE_USER,
                "keyring_username": "user",
                "section": "Gallery Manager",
            },
            {
                "key": "imx_pass",
                "label": "Password:",
                "keyring_service": config.KEYRING_SERVICE_PASS,
                "keyring_username": "pass",
                "show": "*",
                "section": "Gallery Manager",
            },
        ],
    },
    "ViperGirls": {
        "label": "ViperGirls",
        "fields": [
            {
                "key": "vg_user",
                "label": "Username:",
                "keyring_service": config.KEYRING_SERVICE_VG_USER,
                "keyring_username": "user",
                "section": "Forum Credentials",
            },
            {
                "key": "vg_pass",
                "label": "Password:",
                "keyring_service": config.KEYRING_SERVICE_VG_PASS,
                "keyring_username": "pass",
                "show": "*",
                "section": "Forum Credentials",
            },
        ],
    },
    "Turbo": {
        "label": "Turbo",
        "fields": [
            {
                "key": "turbo_user",
                "label": "Username:",
                "keyring_service": "ImageUploader:turbo_user",
                "keyring_username": "user",
            },
            {
                "key": "turbo_pass",
                "label": "Password:",
                "keyring_service": "ImageUploader:turbo_pass",
                "keyring_username": "pass",
                "show": "*",
            },
        ],
    },
    "Vipr": {
        "label": "Vipr",
        "fields": [
            {
                "key": "vipr_user",
                "label": "Username:",
                "keyring_service": config.KEYRING_SERVICE_VIPR_USER,
                "keyring_username": "user",
            },
            {
                "key": "vipr_pass",
                "label": "Password:",
                "keyring_service": config.KEYRING_SERVICE_VIPR_PASS,
                "keyring_username": "pass",
                "show": "*",
            },
        ],
    },
    "ImageBam": {
        "label": "ImageBam",
        "fields": [
            {
                "key": "imagebam_user",
                "label": "Email/User:",
                "keyring_service": config.KEYRING_SERVICE_IB_USER,
                "keyring_username": "user",
            },
            {
                "key": "imagebam_pass",
                "label": "Password:",
                "keyring_service": config.KEYRING_SERVICE_IB_PASS,
                "keyring_username": "pass",
                "show": "*",
            },
        ],
    },
    "Imgur": {
        "label": "Imgur",
        "fields": [
            {
                "key": "imgur_client_id",
                "label": "Client ID:",
                "keyring_service": config.KEYRING_SERVICE_IMGUR_CLIENT_ID,
                "keyring_username": "client_id",
                "section": "API",
            },
            {
                "key": "imgur_access_token",
                "label": "Access Token:",
                "keyring_service": config.KEYRING_SERVICE_IMGUR_ACCESS_TOKEN,
                "keyring_username": "access_token",
                "show": "*",
                "section": "API",
            },
        ],
    },
}


def credential_fields() -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    for service, service_config in SERVICE_CONFIGS.items():
        for field in service_config["fields"]:
            fields.append(
                {
                    "service": service,
                    "service_label": service_config["label"],
                    "key": field["key"],
                    "label": field["label"],
                    "secret": bool(field.get("show")),
                    "section": field.get("section", ""),
                }
            )
    return fields


def credential_keys() -> List[str]:
    return [field["key"] for field in credential_fields()]
