# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Credential management for image hosting services."""

import keyring
import customtkinter as ctk
from tkinter import messagebox
from typing import Dict, List, Callable, Optional
from modules import config


class CredentialsManager:
    """Manages service credentials using system keyring.

    Provides a centralized, data-driven approach to credential management
    with automatic dialog generation and secure storage.
    """

    # Service credential schema - defines all credential fields for each service
    SERVICE_CONFIGS = {
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
    }

    @classmethod
    def load_all_credentials(cls) -> Dict[str, str]:
        """Load credentials for all services from system keyring.

        Returns:
            Dictionary mapping credential keys to values
        """
        creds = {}
        for service_config in cls.SERVICE_CONFIGS.values():
            for field in service_config["fields"]:
                value = keyring.get_password(field["keyring_service"], field["keyring_username"])
                creds[field["key"]] = value or ""
        return creds

    @classmethod
    def save_all_credentials(cls, creds: Dict[str, str]) -> None:
        """Save credentials for all services to system keyring.

        Args:
            creds: Dictionary mapping credential keys to values
        """
        for service_config in cls.SERVICE_CONFIGS.values():
            for field in service_config["fields"]:
                key = field["key"]
                if key in creds:
                    keyring.set_password(
                        field["keyring_service"],
                        field["keyring_username"],
                        creds[key].strip(),
                    )

    @classmethod
    def create_credentials_dialog(
        cls, parent, on_save_callback: Optional[Callable[[], None]] = None
    ) -> None:
        """Create credentials dialog with tabs for each service.

        Args:
            parent: Parent window
            on_save_callback: Optional callback to run after saving credentials
        """
        # Load current credentials
        current_creds = cls.load_all_credentials()

        # Create dialog window
        dlg = ctk.CTkToplevel(parent)
        dlg.title("Service Credentials")
        dlg.geometry("450x450")
        dlg.transient(parent)

        # Create tabview
        nb = ctk.CTkTabview(dlg)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        # Store StringVars for all fields
        field_vars: Dict[str, ctk.StringVar] = {}

        # Create tab for each service
        for service_name, service_config in cls.SERVICE_CONFIGS.items():
            nb.add(service_config["label"])
            tab = nb.tab(service_config["label"])

            current_section = None
            for field in service_config["fields"]:
                # Add section header if specified
                if "section" in field and field["section"] != current_section:
                    current_section = field["section"]
                    ctk.CTkLabel(tab, text=current_section, font=("", 12, "bold")).pack(
                        anchor="w", pady=(10 if current_section != field.get("section") else 0, 0)
                    )

                # Add field label
                ctk.CTkLabel(tab, text=field["label"]).pack(anchor="w")

                # Create StringVar and entry
                var = ctk.StringVar(value=current_creds.get(field["key"], ""))
                field_vars[field["key"]] = var

                entry = ctk.CTkEntry(tab, textvariable=var, show=field.get("show", ""))
                entry.pack(fill="x", pady=(0, 5))

        def save_all():
            """Save all credentials and close dialog."""
            # Gather all values
            new_creds = {key: var.get() for key, var in field_vars.items()}

            # Save to keyring
            cls.save_all_credentials(new_creds)

            # Run callback if provided
            if on_save_callback:
                on_save_callback()

            messagebox.showinfo("Success", "All credentials updated!")
            dlg.destroy()

        # Button frame
        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=10)
        ctk.CTkButton(btn_frame, text="Save All", command=save_all).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="Cancel", command=dlg.destroy, fg_color="gray").pack(
            side="right"
        )
