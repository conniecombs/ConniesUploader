# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import customtkinter as ctk
import threading
import webbrowser
from tkinter import messagebox
from modules.credentials_manager import CredentialsManager
from modules.gallery_cache import GalleryCache
from modules.sidecar import SidecarBridge
from . import config
from .gallery_service import (
    CREATE_SUPPORTED,
    DELETE_SUPPORTED,
    GalleryRecord,
    GalleryResult,
    GalleryService,
    GalleryStatus,
    parse_pixhost_gallery_import,
)


PIXHOST_SERVICE = "pixhost.to"
IMX_SERVICE = "imx.to"

GALLERY_CACHE_FALLBACK_STATUSES = {
    GalleryStatus.LOGIN_FAILED,
    GalleryStatus.PARSE_FAILED,
    GalleryStatus.ERROR,
}


class GalleryManager(ctk.CTkToplevel):
    def __init__(self, parent, creds, callback=None):
        super().__init__(parent)
        self.parent = parent
        self.creds = creds
        self.callback = callback
        self.bridge = SidecarBridge.get()
        self.gallery_service = GalleryService(self.bridge, self.creds)
        self.gallery_cache = GalleryCache()

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
        self._delete_request_id = 0
        self._sync_request_id = 0
        self._imx_all_synced = False

        self._init_ui()
        self.after(config.UI_GALLERY_REFRESH_DELAY_MS, self._load_cached_or_refresh)

    def _init_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(top, text="Service:").pack(side="left", padx=(0, 5))
        self.cb_service = ctk.CTkOptionMenu(
            top,
            variable=self.service_var,
            values=["imx.to", "pixhost.to", "vipr.im"],
            command=lambda _choice: self._on_service_changed(),
        )
        self.cb_service.pack(side="left")

        self.btn_refresh = ctk.CTkButton(
            top,
            text="Refresh from host",
            width=132,
            command=self._refresh_list,
        )
        self.btn_refresh.pack(side="right")

        self.btn_sync_all = ctk.CTkButton(
            top,
            text="Sync All",
            width=92,
            command=self._sync_all_galleries,
        )
        self.btn_sync_all.pack(side="right", padx=(0, 6))

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

        self.pixhost_import_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        ctk.CTkLabel(
            self.pixhost_import_frame,
            text="Import Pixhost Gallery URL/hash:",
        ).pack(anchor="w", padx=5, pady=(8, 2))
        self.ent_pixhost_import = ctk.CTkEntry(
            self.pixhost_import_frame,
            placeholder_text="https://pixhost.to/gallery/abc123 or abc123",
        )
        self.ent_pixhost_import.pack(fill="x", padx=5, pady=(0, 5))
        ctk.CTkButton(
            self.pixhost_import_frame,
            text="Import Gallery",
            command=self._import_pixhost_gallery,
            fg_color="#3B8ED0",
        ).pack(fill="x", padx=5, pady=(0, 5))
        self._update_service_mode()

    def _on_service_changed(self):
        self._update_service_mode()
        self._load_cached_or_refresh()

    def _update_service_mode(self):
        service = self.service_var.get()
        try:
            self.btn_refresh.configure(text=self._list_action_label(service))
        except Exception:
            pass
        try:
            self.btn_sync_all.configure(
                state="normal" if service == IMX_SERVICE else "disabled"
            )
        except Exception:
            pass

        import_frame = getattr(self, "pixhost_import_frame", None)
        if import_frame is None:
            return
        try:
            if service == PIXHOST_SERVICE:
                import_frame.pack(fill="x", padx=0, pady=(4, 0))
            else:
                import_frame.pack_forget()
        except Exception:
            pass

    def _list_action_label(self, service: str = "") -> str:
        service = service or self.service_var.get()
        return "Show saved" if service == PIXHOST_SERVICE else "Refresh from host"

    def _ask_cookies_dialog(self):
        dialog = ctk.CTkInputDialog(text="Paste your 'PHPSESSID' cookie value:", title="Cookie 1/3")
        sess = dialog.get_input()
        if not sess:
            return
        self.gallery_service.set_imx_php_session(sess.strip())
        self._set_status("Manual IMX cookie saved for this Gallery Manager session.")
        self._refresh_list()

    def _load_cached_or_refresh(self):
        self._update_service_mode()
        service = self.service_var.get()
        if service == PIXHOST_SERVICE:
            self._render_pixhost_local_result(self._refresh_request_id)
            return

        records = self.gallery_cache.records_for_service(service)
        if records:
            message = (
                f"Showing {len(records)} cached gallery record(s). "
                "Use Refresh from host to reload live data."
            )
            if service == IMX_SERVICE:
                message = (
                    f"Showing {len(records)} cached IMX gallery record(s). "
                    "Search and sort use this local cache. Use Sync All to refresh the full index."
                )
            result = GalleryResult(
                status=GalleryStatus.SUCCESS,
                message=message,
                service=service,
                records=records,
                cached=True,
            )
            self._render_list_result(self._refresh_request_id, service, result)
            return
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
        if service == PIXHOST_SERVICE:
            self._render_pixhost_local_result(request_id)
            return

        ctk.CTkLabel(self.scroll, text="Loading...").pack(pady=20)

        def _task():
            result = self.gallery_service.list_galleries(service, page=1)
            self.after(0, lambda: self._render_list_result(request_id, service, result))

        threading.Thread(target=_task, daemon=True).start()

    def _sync_all_galleries(self):
        service = self.service_var.get()
        if service != IMX_SERVICE:
            self._set_status("Sync All is only available for IMX.to.", is_error=True)
            return

        self._sync_request_id += 1
        request_id = self._sync_request_id
        self._set_status("Syncing all IMX.to galleries...")
        self._clear_scroll()
        ctk.CTkLabel(self.scroll, text="Syncing all IMX.to galleries...").pack(pady=20)

        def _progress(page: int, total: int):
            self.after(
                0,
                lambda page=page, total=total: self._set_status(
                    f"Syncing IMX.to galleries... page {page}, {total} found."
                ),
            )

        def _task():
            result = self.gallery_service.sync_all_galleries(
                service, progress_callback=_progress
            )
            self.after(0, lambda: self._handle_sync_all_result(request_id, service, result))

        threading.Thread(target=_task, daemon=True).start()

    def _render_pixhost_local_result(self, request_id: int):
        records = self.gallery_cache.records_for_service(PIXHOST_SERVICE)
        if records:
            result = GalleryResult(
                status=GalleryStatus.SUCCESS,
                message=(
                    f"Showing {len(records)} saved Pixhost gallery record(s). "
                    "Pixhost has no remote account gallery listing."
                ),
                service=PIXHOST_SERVICE,
                records=records,
                cached=True,
            )
        else:
            result = GalleryResult(
                status=GalleryStatus.EMPTY,
                message=(
                    "No saved Pixhost galleries. Create a Pixhost gallery here or import "
                    "an existing gallery URL/hash."
                ),
                service=PIXHOST_SERVICE,
                cached=True,
            )
        self._render_list_result(request_id, PIXHOST_SERVICE, result)

    def _load_more_pages(self):
        """Fetch the next IMX page and append it to the local cache."""
        page = self.current_page + 1
        self._refresh_request_id += 1
        request_id = self._refresh_request_id

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

        if not result.ok:
            if (
                service == IMX_SERVICE
                and result.status == GalleryStatus.EMPTY
                and result.page > 1
            ):
                records = self.gallery_cache.records_for_service(service)
                if records:
                    self.current_page = max(1, result.page - 1)
                    self._records = records
                    self._imx_all_synced = True
                    self._set_status(
                        f"No more IMX.to galleries after page {self.current_page}. "
                        f"Showing {len(records)} cached gallery record(s)."
                    )
                    self._render_current_records()
                    return
            cached_result = self._cached_result_for_failure(service, result)
            if result.status in GALLERY_CACHE_FALLBACK_STATUSES and cached_result:
                self.current_page = cached_result.page
                self._records = cached_result.records
                self._set_status(cached_result.message, is_warning=True)
                self._render_current_records()
                return
            self._records = []
            self._render_result_message(result)
            return

        self._records = result.records
        status_message = result.message
        if not result.cached and result.records:
            self.gallery_cache.upsert_records(service, result.records)
            if service == IMX_SERVICE:
                self._records = self.gallery_cache.records_for_service(service)
                if result.page > 1:
                    status_message = (
                        f"Loaded IMX.to page {result.page}; showing "
                        f"{len(self._records)} cached gallery record(s)."
                    )
                else:
                    status_message = (
                        f"Refreshed IMX.to page 1; showing "
                        f"{len(self._records)} cached gallery record(s)."
                    )
            else:
                self._records = self._records_with_cache_metadata(service, result.records)
        self._set_status(status_message, is_warning=result.cached)
        self._render_current_records()

    def _handle_sync_all_result(
        self, request_id: int, service: str, result: GalleryResult
    ):
        if self._is_stale_sync(request_id, service):
            return

        self._clear_scroll()
        if not result.ok:
            cached_result = self._cached_result_for_failure(service, result)
            if result.status in GALLERY_CACHE_FALLBACK_STATUSES and cached_result:
                self.current_page = cached_result.page
                self._records = cached_result.records
                self._set_status(cached_result.message, is_warning=True)
                self._render_current_records()
                return
            self._set_status(result.message, is_error=True)
            self._render_result_message(result)
            return

        if result.records:
            self.gallery_cache.upsert_records(service, result.records)

        self.current_page = result.page
        self._records = self.gallery_cache.records_for_service(service)
        self._imx_all_synced = True
        self._set_status(
            f"Sync complete: fetched {len(result.records)} IMX.to gallery record(s); "
            f"showing {len(self._records)} cached gallery record(s)."
        )
        self._render_current_records()

    def _records_with_cache_metadata(self, service: str, records):
        cached_by_id = {
            record.id: record
            for record in self.gallery_cache.records_for_service(service)
        }
        merged = []
        for record in records:
            cached = cached_by_id.get(record.id)
            if cached:
                record.raw["pinned"] = cached.raw.get("pinned")
                record.raw["last_used_at"] = cached.raw.get("last_used_at")
                record.raw["cached_at"] = cached.raw.get("cached_at")
            merged.append(record)
        return merged

    def _cached_result_for_failure(self, service: str, result: GalleryResult):
        records = self.gallery_cache.records_for_service(service)
        if not records:
            return None
        return GalleryResult(
            status=GalleryStatus.SUCCESS,
            message=(
                f"{result.message} Showing {len(records)} cached gallery record(s) instead."
            ),
            service=service,
            records=records,
            page=result.page,
            raw=result.raw,
            cached=True,
        )

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
        if self.service_var.get() == IMX_SERVICE and not self._imx_all_synced:
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
        if self._record_is_pinned(record):
            meta_parts.append("Pinned")
        if self._record_is_cached(record):
            meta_parts.append("Cached")
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
            if self._can_assign_selected_batches():
                ctk.CTkButton(
                    actions,
                    text="Assign Batches",
                    width=106,
                    height=26,
                    command=lambda r=record: self._assign_selected_batches(r),
                ).pack(side="left", padx=2)

        pin_text = "Unpin" if self._record_is_pinned(record) else "Pin"
        ctk.CTkButton(
            actions,
            text=pin_text,
            width=62,
            height=26,
            command=lambda r=record: self._toggle_pin(r),
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

        if record.service in DELETE_SUPPORTED:
            ctk.CTkButton(
                actions,
                text="Delete",
                width=64,
                height=26,
                fg_color="#a83232",
                hover_color="#7f2424",
                command=lambda r=record: self._delete_gallery(r),
            ).pack(side="left", padx=2)
        elif record.service == PIXHOST_SERVICE:
            ctk.CTkButton(
                actions,
                text="Remove",
                width=72,
                height=26,
                fg_color="#6b7280",
                hover_color="#4b5563",
                command=lambda r=record: self._remove_saved_gallery(r),
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
        records = sorted(records, key=self._record_sort_key, reverse=reverse)
        return sorted(records, key=lambda record: 0 if self._record_is_pinned(record) else 1)

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

    def _record_is_pinned(self, record: GalleryRecord) -> bool:
        return bool(record.raw.get("pinned"))

    def _record_is_cached(self, record: GalleryRecord) -> bool:
        return bool(record.raw.get("_cached"))

    def _select(self, record: GalleryRecord):
        self._mark_used(record)
        if self.callback:
            try:
                self.callback(record.service, record.id, record)
            except TypeError:
                self.callback(record.service, record.id)
        self.destroy()

    def _can_assign_selected_batches(self) -> bool:
        selected_count = getattr(self.parent, "gallery_selected_batch_count", None)
        return callable(selected_count) and selected_count() > 0

    def _assign_selected_batches(self, record: GalleryRecord):
        self._mark_used(record)
        assign = getattr(self.parent, "on_gallery_assign_to_selected_batches", None)
        if callable(assign):
            assign(record.service, record.id, record)
        self.destroy()

    def _mark_used(self, record: GalleryRecord):
        used_at = self.gallery_cache.mark_used(record)
        record.raw["last_used_at"] = used_at
        record.raw.pop("_cached", None)

    def _toggle_pin(self, record: GalleryRecord):
        is_pinned = self.gallery_cache.toggle_pinned(record)
        record.raw["pinned"] = is_pinned
        state = "Pinned" if is_pinned else "Unpinned"
        self._set_status(f"{state} {record.name}.")
        self._render_current_records()

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
            self.gallery_cache.upsert_record(record)
            self._render_created_gallery(record)
        else:
            self._render_result_message(result)

    def _import_pixhost_gallery(self):
        raw_value = self.ent_pixhost_import.get().strip()
        display_name = self.ent_name.get().strip()
        record = parse_pixhost_gallery_import(raw_value, display_name)
        if not record:
            self._set_status("Enter a valid Pixhost gallery URL or hash.", is_error=True)
            return

        self.gallery_cache.upsert_record(record)
        self._set_status(f"Imported Pixhost gallery '{record.name}' ({record.id}).")
        self._render_created_gallery(record)

    def _remove_saved_gallery(self, record: GalleryRecord):
        confirmed = messagebox.askyesno(
            "Remove Saved Gallery",
            f"Remove '{record.name}' ({record.id}) from Gallery Manager?\n\n"
            "This only removes the saved local record; it does not delete anything on Pixhost.",
            parent=self,
        )
        if not confirmed:
            return

        removed = self.gallery_cache.remove_record(record.service, record.id)
        self._records = [
            existing
            for existing in self._records
            if not (existing.service == record.service and existing.id == record.id)
        ]
        if removed:
            self._set_status(f"Removed saved gallery '{record.name}' ({record.id}).")
        else:
            self._set_status(f"Saved gallery '{record.name}' was already removed.", is_warning=True)

        if self._records:
            self._render_current_records()
        else:
            self._render_pixhost_local_result(self._refresh_request_id)

    def _delete_gallery(self, record: GalleryRecord):
        if record.service not in DELETE_SUPPORTED:
            self._set_status(
                f"{record.service} does not support gallery deletion.", is_error=True
            )
            return

        confirmed = messagebox.askyesno(
            "Delete Gallery",
            f"Delete '{record.name}' ({record.id}) from {record.service}?\n\n"
            "This removes the host folder and all images inside it.",
            parent=self,
        )
        if not confirmed:
            return

        self._delete_request_id += 1
        request_id = self._delete_request_id
        service = record.service
        self._set_status(f"Deleting gallery '{record.name}'...")

        def _task():
            result = self.gallery_service.delete_gallery(service, record)
            self.after(
                0, lambda: self._handle_delete_result(request_id, service, record, result)
            )

        threading.Thread(target=_task, daemon=True).start()

    def _handle_delete_result(
        self,
        request_id: int,
        service: str,
        record: GalleryRecord,
        result: GalleryResult,
    ):
        if self._is_stale_delete(request_id, service):
            return

        if not result.ok:
            self._set_status(result.message, is_error=True)
            return

        self.gallery_cache.remove_record(record.service, record.id)
        self._records = [
            existing
            for existing in self._records
            if not (existing.service == record.service and existing.id == record.id)
        ]
        self._set_status(result.message)
        self._render_current_records()

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
                (self._list_action_label(record.service), self._refresh_list),
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

        if result.service == PIXHOST_SERVICE:
            actions = [
                (self._list_action_label(result.service), self._refresh_list),
                ("Import Gallery", self._focus_import_gallery),
            ]
        else:
            actions = [("Refresh from host", self._refresh_list)]
            if result.service == IMX_SERVICE:
                actions.append(("Sync All", self._sync_all_galleries))
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
            ctk.CTkButton(frame, text=label, width=145, command=command).pack(
                side="left", padx=4
            )

    def _clear_search(self):
        self.search_var.set("")

    def _focus_create_gallery(self):
        try:
            self.ent_name.focus_set()
        except Exception:
            pass

    def _focus_import_gallery(self):
        try:
            self.ent_pixhost_import.focus_set()
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

    def _set_status(self, message: str, is_error: bool = False, is_warning: bool = False):
        if is_error:
            text_color = "#ff6b6b"
        elif is_warning:
            text_color = "#FFB340"
        else:
            text_color = self._status_default_text_color
        self.status_label.configure(text=message, text_color=text_color)

    def _is_stale_refresh(self, request_id: int, service: str) -> bool:
        return request_id != self._refresh_request_id or service != self.service_var.get()

    def _is_stale_create(self, request_id: int, service: str) -> bool:
        return request_id != self._create_request_id or service != self.service_var.get()

    def _is_stale_delete(self, request_id: int, service: str) -> bool:
        return request_id != self._delete_request_id or service != self.service_var.get()

    def _is_stale_sync(self, request_id: int, service: str) -> bool:
        return request_id != self._sync_request_id or service != self.service_var.get()
