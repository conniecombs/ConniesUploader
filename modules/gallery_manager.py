# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import customtkinter as ctk
import threading
import webbrowser
from modules.credentials_manager import CredentialsManager
from modules.sidecar import SidecarBridge
from . import config
from .gallery_service import (
    CREATE_SUPPORTED,
    GalleryRecord,
    GalleryResult,
    GalleryService,
    GalleryStatus,
)


class GalleryManager(ctk.CTkToplevel):
    def __init__(self, parent, creds, callback=None):
        super().__init__(parent)
        self.creds = creds
        self.callback = callback
        self.bridge = SidecarBridge.get()
        self.gallery_service = GalleryService(self.bridge, self.creds)

        self.title("Gallery Manager")
        self.geometry("820x720")
        self.minsize(720, 560)
        self.resizable(True, True)
        self.transient(parent)

        self.service_var = ctk.StringVar(value="imx.to")
        self.search_var = ctk.StringVar(value="")
        self.sort_var = ctk.StringVar(value="Name")
        self.current_page = 1  # Track current page
        self._records = []
        self._refresh_request_id = 0
        self._create_request_id = 0

        self._init_ui()
        self.after(config.UI_GALLERY_REFRESH_DELAY_MS, self._refresh_list)

    def _init_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(top, text="Service:").pack(side="left", padx=(0, 5))
        self.cb_service = ctk.CTkOptionMenu(
            top,
            variable=self.service_var,
            values=["imx.to", "pixhost.to", "vipr.im"],
            command=lambda x: self._refresh_list(),
        )
        self.cb_service.pack(side="left")

        # Refresh resets to Page 1
        ctk.CTkButton(top, text="Refresh", width=80, command=self._refresh_list).pack(side="right")

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(tools, text="Search:").pack(side="left", padx=(0, 5))
        self.search_entry = ctk.CTkEntry(tools, textvariable=self.search_var, width=260)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_var.trace_add("write", lambda *_: self._render_current_records())

        ctk.CTkLabel(tools, text="Sort:").pack(side="left", padx=(0, 5))
        self.sort_menu = ctk.CTkOptionMenu(
            tools,
            variable=self.sort_var,
            values=["Name", "ID/hash", "Last used"],
            width=130,
            command=lambda _choice: self._render_current_records(),
        )
        self.sort_menu.pack(side="left")

        self.status_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=760)
        self.status_label.pack(fill="x", padx=12, pady=(0, 5))
        self._status_default_text_color = self.status_label.cget("text_color")

        self.scroll = ctk.CTkScrollableFrame(self, label_text="Your Galleries")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=5)

        # Load More Button (Hidden initially)
        self.btn_load_more = None

        bottom = ctk.CTkFrame(self)
        bottom.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(bottom, text="New Gallery Name:").pack(anchor="w", padx=5, pady=2)
        self.ent_name = ctk.CTkEntry(bottom)
        self.ent_name.pack(fill="x", padx=5, pady=(0, 5))

        ctk.CTkButton(
            bottom, text="Create Gallery", command=self._create_gallery, fg_color="green"
        ).pack(fill="x", padx=5, pady=5)

    def _ask_cookies_dialog(self):
        dialog = ctk.CTkInputDialog(text="Paste your 'PHPSESSID' cookie value:", title="Cookie 1/3")
        sess = dialog.get_input()
        if not sess:
            return
        self.gallery_service.set_imx_php_session(sess.strip())
        self._set_status("Manual IMX cookie saved for this Gallery Manager session.")
        self._refresh_list()

    def _refresh_list(self):
        """Resets to Page 1 and clears the list"""
        self.current_page = 1
        self._refresh_request_id += 1
        request_id = self._refresh_request_id

        # Clear UI
        self._clear_scroll()

        service = self.service_var.get()
        self._set_status("")
        ctk.CTkLabel(self.scroll, text="Loading...").pack(pady=20)

        def _task():
            result = self.gallery_service.list_galleries(service, page=1)
            self.after(0, lambda: self._render_list_result(request_id, service, result))

        threading.Thread(target=_task, daemon=True).start()

    def _load_more_pages(self):
        """Fetches the next page and replaces current galleries"""
        page = self.current_page + 1
        self._refresh_request_id += 1
        request_id = self._refresh_request_id

        # Clear UI
        self._clear_scroll()

        service = self.service_var.get()
        self._set_status("")
        ctk.CTkLabel(self.scroll, text=f"Loading Page {page}...").pack(pady=20)

        def _task():
            result = self.gallery_service.list_galleries(service, page=page)
            self.after(0, lambda: self._render_list_result(request_id, service, result))

        threading.Thread(target=_task, daemon=True).start()

    def _render_list_result(self, request_id: int, service: str, result: GalleryResult):
        # --- FIX: RACE CONDITION CHECK ---
        # If the window was closed while the thread was running, self.scroll might be gone.
        try:
            if not self.winfo_exists() or not self.scroll.winfo_exists():
                return
        except Exception:
            return
        # ---------------------------------

        if self._is_stale_refresh(request_id, service):
            return

        self._clear_scroll()
        self.current_page = result.page
        self._records = result.records

        if not result.ok:
            self._render_result_message(result)
            return

        self._set_status(result.message)
        self._render_current_records()

    def _render_current_records(self):
        try:
            if not self.winfo_exists() or not self.scroll.winfo_exists():
                return
        except Exception:
            return

        self._clear_scroll()
        records = self._filtered_sorted_records()

        if not records:
            if self._records:
                self._render_inline_empty_state(
                    "No matching galleries",
                    "No gallery matches the current search.",
                    [("Clear Search", self._clear_search)],
                )
            return

        for record in records:
            self._render_record_row(record)

        # Append "Load More" button at the bottom if we found data
        # (Assuming if we found data, there *might* be another page)
        if self.service_var.get() == "imx.to":
            self.btn_load_more = ctk.CTkButton(
                self.scroll,
                text="Load Next Page",
                command=self._load_more_pages,
                fg_color="#3B8ED0",
            )
            self.btn_load_more.pack(pady=15)

    def _render_record_row(self, record: GalleryRecord, highlight: bool = False):
        row_color = ("#1f6aa5", "#1f6aa5") if highlight else "transparent"
        f = ctk.CTkFrame(self.scroll, fg_color=row_color)
        f.pack(fill="x", pady=3, padx=2)
        f.grid_columnconfigure(0, weight=1)

        text_frame = ctk.CTkFrame(f, fg_color="transparent")
        text_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        text_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(text_frame, text=record.name, font=("", 12, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew"
        )

        meta_parts = [f"ID/hash: {record.id}"]
        last_used = self._record_last_used(record)
        if last_used:
            meta_parts.append(f"Last used: {last_used}")
        ctk.CTkLabel(
            text_frame,
            text=" | ".join(meta_parts),
            text_color="gray",
            font=("", 11),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew")

        actions = ctk.CTkFrame(f, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=6, pady=6)

        if self.callback:
            ctk.CTkButton(
                actions,
                text="Select",
                width=62,
                height=26,
                command=lambda r=record: self._select(r),
            ).pack(side="left", padx=2)

        ctk.CTkButton(
            actions,
            text="Copy ID",
            width=72,
            height=26,
            command=lambda r=record: self._copy_text(r.id, "Gallery ID/hash"),
        ).pack(side="left", padx=2)

        url_state = "normal" if record.url else "disabled"
        ctk.CTkButton(
            actions,
            text="Copy URL",
            width=78,
            height=26,
            state=url_state,
            command=lambda r=record: self._copy_text(r.url, "Gallery URL"),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Open",
            width=58,
            height=26,
            state=url_state,
            command=lambda r=record: self._open_gallery(r),
        ).pack(side="left", padx=2)

    def _filtered_sorted_records(self):
        query = self.search_var.get().strip().lower()
        records = list(self._records)
        if query:
            records = [
                record
                for record in records
                if query in record.name.lower()
                or query in record.id.lower()
                or query in record.url.lower()
            ]

        reverse = self.sort_var.get() == "Last used"
        return sorted(records, key=self._record_sort_key, reverse=reverse)

    def _record_sort_key(self, record: GalleryRecord):
        sort_mode = self.sort_var.get()
        if sort_mode == "ID/hash":
            return (record.id.lower(), record.name.lower())
        if sort_mode == "Last used":
            last_used = self._record_last_used(record)
            return (bool(last_used), last_used.lower(), record.name.lower())
        return (record.name.lower(), record.id.lower())

    def _record_last_used(self, record: GalleryRecord) -> str:
        for key in ("last_used", "last_used_at", "last_used_ts"):
            value = str(record.raw.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _select(self, record: GalleryRecord):
        if self.callback:
            self.callback(record.service, record.id)
        self.destroy()

    def _create_gallery(self):
        name = self.ent_name.get().strip()
        if not name:
            self._set_status("Enter a gallery name.", is_error=True)
            return

        service = self.service_var.get()
        self._create_request_id += 1
        request_id = self._create_request_id
        self._set_status(f"Creating gallery '{name}'...")

        def _task():
            result = self.gallery_service.create_gallery(service, name)
            self.after(0, lambda: self._handle_create_result(request_id, service, result))

        threading.Thread(target=_task, daemon=True).start()

    def _handle_create_result(self, request_id: int, service: str, result: GalleryResult):
        if self._is_stale_create(request_id, service):
            return

        if not result.ok:
            self._set_status(result.message, is_error=True)
            self._render_result_message(result)
            return

        record = result.record
        self._set_status(result.message)
        if record:
            self._render_created_gallery(record)
        else:
            self._render_result_message(result)

    def _render_created_gallery(self, record: GalleryRecord):
        self._records = [record]
        self._clear_scroll()
        ctk.CTkLabel(self.scroll, text="Gallery created", font=("", 16, "bold")).pack(
            pady=(22, 4)
        )
        ctk.CTkLabel(
            self.scroll,
            text="Choose what to do with the new gallery.",
            text_color="gray",
        ).pack(pady=(0, 12))
        self._render_record_row(record, highlight=True)
        self._render_empty_actions(
            [
                ("Refresh List", self._refresh_list),
                ("Create Another", self._focus_create_gallery),
            ]
        )

    def _render_result_message(self, result: GalleryResult):
        self._clear_scroll()
        is_error = result.status != GalleryStatus.EMPTY
        self._set_status(result.message, is_error=is_error)

        title = {
            GalleryStatus.EMPTY: "No galleries found",
            GalleryStatus.MISSING_CREDENTIALS: "Missing credentials",
            GalleryStatus.LOGIN_FAILED: "Login failed",
            GalleryStatus.UNSUPPORTED: "Unsupported gallery operation",
            GalleryStatus.PARSE_FAILED: "Could not read galleries",
            GalleryStatus.ERROR: "Gallery operation failed",
        }.get(result.status, "Gallery Manager")

        ctk.CTkLabel(self.scroll, text=title, font=("", 14, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(self.scroll, text=result.message, wraplength=500, justify="center").pack(
            pady=(0, 12)
        )

        actions = [("Refresh", self._refresh_list)]
        if result.status in {GalleryStatus.MISSING_CREDENTIALS, GalleryStatus.LOGIN_FAILED}:
            actions.insert(0, ("Set Credentials", self._open_credentials))
        if result.service in CREATE_SUPPORTED:
            actions.append(("Create Gallery", self._focus_create_gallery))

        if result.status == GalleryStatus.LOGIN_FAILED and result.service == "imx.to":
            actions.append(("Set IMX Cookie", self._ask_cookies_dialog))

        self._render_empty_actions(actions)

    def _render_inline_empty_state(self, title: str, message: str, actions):
        ctk.CTkLabel(self.scroll, text=title, font=("", 14, "bold")).pack(pady=(24, 4))
        ctk.CTkLabel(self.scroll, text=message, wraplength=500, justify="center").pack(
            pady=(0, 12)
        )
        self._render_empty_actions(actions)

    def _render_empty_actions(self, actions):
        if not actions:
            return
        frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        frame.pack(pady=8)
        for label, command in actions:
            ctk.CTkButton(frame, text=label, width=120, command=command).pack(
                side="left", padx=4
            )

    def _clear_search(self):
        self.search_var.set("")

    def _focus_create_gallery(self):
        try:
            self.ent_name.focus_set()
        except Exception:
            pass

    def _open_credentials(self):
        CredentialsManager.create_credentials_dialog(
            parent=self,
            on_save_callback=self._reload_credentials_and_refresh,
        )

    def _reload_credentials_and_refresh(self):
        self.creds = CredentialsManager.load_all_credentials()
        self.gallery_service = GalleryService(self.bridge, self.creds)
        self._refresh_list()

    def _copy_text(self, text: str, label: str):
        if not text:
            self._set_status(f"No {label.lower()} is available.", is_error=True)
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._set_status(f"Copied {label}.")
        except Exception as exc:
            self._set_status(f"Could not copy {label}: {exc}", is_error=True)

    def _open_gallery(self, record: GalleryRecord):
        if not record.url:
            self._set_status("No gallery URL is available.", is_error=True)
            return
        webbrowser.open(record.url)
        self._set_status(f"Opened {record.name}.")

    def _clear_scroll(self):
        for widget in self.scroll.winfo_children():
            widget.destroy()

    def _set_status(self, message: str, is_error: bool = False):
        text_color = "#ff6b6b" if is_error else self._status_default_text_color
        self.status_label.configure(text=message, text_color=text_color)

    def _is_stale_refresh(self, request_id: int, service: str) -> bool:
        return request_id != self._refresh_request_id or service != self.service_var.get()

    def _is_stale_create(self, request_id: int, service: str) -> bool:
        return request_id != self._create_request_id or service != self.service_var.get()
