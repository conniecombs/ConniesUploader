# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""ViperGirls Tk windows: posting-target manager and posting history."""

import json
import os
import threading
import webbrowser
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk
import pyperclip
from tkinter import filedialog, messagebox
from loguru import logger

from modules import viper_client, viper_storage
from modules.credentials_manager import CredentialsManager


def open_supported_url(url: str) -> bool:
    """Open ``url`` in the browser only when it is a ViperGirls link."""
    clean_url = str(url or "").strip()
    if not clean_url or viper_storage.safe_target_url(clean_url, "") != clean_url:
        logger.warning(f"Refusing to open a non-ViperGirls URL: {clean_url!r}")
        return False
    webbrowser.open(clean_url)
    return True


class ViperToolsWindow(ctk.CTkToplevel):
    """Manage saved ViperGirls posting targets."""

    def __init__(self, parent, creds=None, callback=None):
        super().__init__(parent)
        self.parent = parent
        self.creds = creds or {}
        self.callback = callback
        self.saved_threads = viper_storage.load_saved_threads()
        self.editing_name: Optional[str] = None
        self.search_var = ctk.StringVar(value="")
        self.sort_var = ctk.StringVar(value="Name")
        self.selected_targets: Dict[str, Any] = {}
        self.expanded_targets: Dict[str, bool] = {}

        self.title("ViperGirls Posting Targets")
        self.geometry("1180x700")
        self.minsize(960, 560)
        self.resizable(True, True)
        self.transient(parent)
        self.lift()
        self.focus_force()

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self._build_health_bar()
        self._build_target_list()
        self._build_controls()
        self.refresh_list()

    def _build_health_bar(self) -> None:
        self.health_bar = ctk.CTkFrame(self)
        self.health_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))
        self.health_bar.grid_columnconfigure(2, weight=1)

        self.credentials_label = ctk.CTkLabel(self.health_bar, text="")
        self.credentials_label.grid(row=0, column=0, padx=(10, 12), pady=8, sticky="w")

        self.target_count_label = ctk.CTkLabel(self.health_bar, text="")
        self.target_count_label.grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        self.path_label = ctk.CTkLabel(
            self.health_bar,
            text=viper_storage.THREADS_FILE,
            text_color="gray",
            anchor="w",
        )
        self.path_label.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="ew")

        ctk.CTkButton(
            self.health_bar,
            text="Set Credentials",
            width=120,
            command=self.open_credentials,
        ).grid(row=0, column=3, padx=4, pady=8)

        self.test_login_button = ctk.CTkButton(
            self.health_bar,
            text="Test Login",
            width=95,
            command=self.test_login,
        )
        self.test_login_button.grid(row=0, column=4, padx=4, pady=8)

        ctk.CTkButton(
            self.health_bar,
            text="Open Data Folder",
            width=130,
            command=self.open_data_folder,
        ).grid(row=0, column=5, padx=(4, 10), pady=8)

        ctk.CTkButton(
            self.health_bar,
            text="History",
            width=85,
            command=self.open_history,
        ).grid(row=0, column=6, padx=(0, 10), pady=8)

    def _build_target_list(self) -> None:
        self.list_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.list_panel.grid(row=1, column=0, sticky="nsew", padx=(10, 8), pady=(0, 10))
        self.list_panel.grid_columnconfigure(0, weight=1)
        self.list_panel.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self.list_panel)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(toolbar, text="Search").grid(row=0, column=0, sticky="w", padx=(10, 6), pady=8)
        search_entry = ctk.CTkEntry(toolbar, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=8)
        self.search_var.trace_add("write", lambda *_: self.refresh_list())

        ctk.CTkLabel(toolbar, text="Sort").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=8)
        self.sort_menu = ctk.CTkOptionMenu(
            toolbar,
            variable=self.sort_var,
            values=["Name", "Last Used", "Thread ID"],
            command=lambda _choice: self.refresh_list(),
            width=115,
        )
        self.sort_menu.grid(row=0, column=3, padx=(0, 8), pady=8)

        ctk.CTkButton(toolbar, text="Import", width=76, command=self.import_targets).grid(
            row=0, column=4, padx=3, pady=8
        )
        ctk.CTkButton(toolbar, text="Export All", width=92, command=self.export_all_targets).grid(
            row=0, column=5, padx=3, pady=8
        )
        self.refresh_names_button = ctk.CTkButton(
            toolbar,
            text="Refresh Names",
            width=115,
            command=self.refresh_target_names,
        )
        self.refresh_names_button.grid(row=0, column=6, padx=3, pady=8)
        ctk.CTkButton(
            toolbar,
            text="Export Selected",
            width=120,
            command=self.export_selected_targets,
        ).grid(row=0, column=7, padx=3, pady=8)
        ctk.CTkButton(
            toolbar,
            text="Delete Selected",
            width=120,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=self.bulk_delete_selected,
        ).grid(row=0, column=8, padx=(3, 10), pady=8)

        self.scroll = ctk.CTkScrollableFrame(self.list_panel, label_text="Saved Posting Targets")
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def _build_controls(self) -> None:
        self.controls = ctk.CTkFrame(self, width=310)
        self.controls.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=(0, 10))
        self.controls.grid_propagate(False)
        self.controls.grid_columnconfigure(0, weight=1)

        self.form_title_label = ctk.CTkLabel(
            self.controls,
            text="Add Posting Target",
            font=("Segoe UI", 15, "bold"),
        )
        self.form_title_label.grid(row=0, column=0, sticky="w", padx=14, pady=(14, 8))

        ctk.CTkLabel(self.controls, text="Fallback Name").grid(row=1, column=0, sticky="w", padx=14)
        self.ent_name = ctk.CTkEntry(
            self.controls,
            placeholder_text="Optional if title fetch fails",
        )
        self.ent_name.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 10))

        ctk.CTkLabel(self.controls, text="Thread URL or ID").grid(
            row=3, column=0, sticky="w", padx=14
        )
        self.ent_url = ctk.CTkEntry(
            self.controls,
            placeholder_text="URL, threads/12345, or 12345",
        )
        self.ent_url.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 10))

        ctk.CTkLabel(self.controls, text="Tags").grid(row=5, column=0, sticky="w", padx=14)
        self.ent_tags = ctk.CTkEntry(
            self.controls,
            placeholder_text="comma, separated, labels",
        )
        self.ent_tags.grid(row=6, column=0, sticky="ew", padx=14, pady=(2, 10))

        ctk.CTkLabel(self.controls, text="Notes").grid(row=7, column=0, sticky="w", padx=14)
        self.ent_notes = ctk.CTkEntry(
            self.controls,
            placeholder_text="Optional reminder or workflow note",
        )
        self.ent_notes.grid(row=8, column=0, sticky="ew", padx=14, pady=(2, 10))

        self.save_button = ctk.CTkButton(
            self.controls,
            text="Save Target",
            command=self.save_target,
        )
        self.save_button.grid(row=9, column=0, sticky="ew", padx=14, pady=(4, 6))

        self.cancel_edit_button = ctk.CTkButton(
            self.controls,
            text="Cancel Edit",
            command=self.cancel_edit,
            fg_color="gray",
            hover_color="#666666",
        )
        self.cancel_edit_button.grid(row=10, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.cancel_edit_button.configure(state="disabled")

        ctk.CTkButton(
            self.controls,
            text="Refresh List",
            command=self.refresh_list,
        ).grid(row=11, column=0, sticky="ew", padx=14, pady=(12, 6))

    def _update_health(self) -> None:
        self.creds = CredentialsManager.load_all_credentials()
        has_credentials = bool(self.creds.get("vg_user") and self.creds.get("vg_pass"))
        self.credentials_label.configure(
            text=f"Credentials: {'Set' if has_credentials else 'Missing'}",
            text_color="#2FA572" if has_credentials else "#D9534F",
        )
        self.target_count_label.configure(text=f"Targets: {len(self.saved_threads)}")

    def _filtered_sorted_targets(self) -> List[Tuple[str, Dict[str, object]]]:
        query = self.search_var.get().strip().lower()
        items = []
        for name, data in self.saved_threads.items():
            haystack = " ".join(
                [
                    name,
                    str(data.get("thread_id") or ""),
                    str(data.get("url") or ""),
                    str(data.get("notes") or ""),
                    str(data.get("site_title") or ""),
                    viper_storage.format_tags(data.get("tags")),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            items.append((name, data))

        sort_by = self.sort_var.get()
        if sort_by == "Last Used":
            return sorted(
                items,
                key=lambda item: (
                    str(item[1].get("last_used_at") or ""),
                    item[0].lower(),
                ),
                reverse=True,
            )
        if sort_by == "Thread ID":
            return sorted(
                items,
                key=lambda item: (
                    str(item[1].get("thread_id") or ""),
                    item[0].lower(),
                ),
            )
        return sorted(items, key=lambda item: item[0].lower())

    def refresh_list(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()

        selected_names = set(self._selected_target_names())
        self.saved_threads = viper_storage.load_saved_threads()
        self.expanded_targets = {
            name: is_expanded
            for name, is_expanded in getattr(self, "expanded_targets", {}).items()
            if name in self.saved_threads
        }
        self.selected_targets = {}
        self._update_health()
        visible_targets = self._filtered_sorted_targets()

        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=3)
        header.grid_columnconfigure(3, weight=1)
        header.grid_columnconfigure(4, weight=3)
        header.grid_columnconfigure(5, weight=0)
        headers = ("", "Sel", "Name / Tags", "Thread / Last Used", "Notes", "Actions")
        for column, text in enumerate(headers):
            ctk.CTkLabel(header, text=text, font=("Segoe UI", 12, "bold")).grid(
                row=0, column=column, sticky="w", padx=6
            )

        if not self.saved_threads:
            ctk.CTkLabel(
                self.scroll,
                text=(
                    "No saved posting targets yet. Add a target with a ViperGirls thread "
                    "URL or raw thread ID, or import a saved targets JSON file."
                ),
                text_color="gray",
                wraplength=760,
                justify="left",
            ).grid(row=1, column=0, sticky="w", padx=12, pady=18)
            return

        if not visible_targets:
            ctk.CTkLabel(
                self.scroll,
                text="No saved posting targets match the current search.",
                text_color="gray",
            ).grid(row=1, column=0, sticky="w", padx=12, pady=18)
            return

        for row_index, (name, data) in enumerate(visible_targets, start=1):
            self._add_target_row(row_index, name, data, selected=name in selected_names)

    def _add_target_row(
        self,
        row_index: int,
        name: str,
        data: Dict[str, object],
        selected: bool = False,
    ) -> None:
        row = ctk.CTkFrame(self.scroll)
        row.grid(row=row_index, column=0, sticky="ew", padx=4, pady=3)
        row.grid_columnconfigure(0, weight=0)
        row.grid_columnconfigure(1, weight=0)
        row.grid_columnconfigure(2, weight=3)
        row.grid_columnconfigure(3, weight=1)
        row.grid_columnconfigure(4, weight=3)
        row.grid_columnconfigure(5, weight=0)

        thread_id = str(data.get("thread_id") or "")
        url = str(data.get("url") or "")
        tags = viper_storage.format_tags(data.get("tags"))
        notes = str(data.get("notes") or "")
        last_used = str(data.get("last_used_at") or "Never")
        expanded = bool(getattr(self, "expanded_targets", {}).get(name))

        ctk.CTkButton(
            row,
            text="-" if expanded else "+",
            width=28,
            height=24,
            command=lambda n=name: self.toggle_target_expanded(n),
        ).grid(row=0, column=0, rowspan=3, sticky="nw", padx=(6, 0), pady=8)

        var = ctk.BooleanVar(value=selected)
        self.selected_targets[name] = var
        ctk.CTkCheckBox(row, text="", variable=var, width=24).grid(
            row=0, column=1, rowspan=3, sticky="nw", padx=(6, 0), pady=8
        )

        name_frame = ctk.CTkFrame(row, fg_color="transparent")
        name_frame.grid(row=0, column=2, sticky="nsew", padx=6, pady=(6, 6))
        name_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            name_frame,
            text=self._display_target_name(name, data),
            anchor="w",
            font=("Segoe UI", 12, "bold"),
        ).pack(fill="x", anchor="w")
        if expanded:
            self._add_target_url_link(name_frame, url)
        ctk.CTkLabel(
            name_frame,
            text=tags or "No tags",
            anchor="w",
            text_color="gray",
        ).pack(fill="x", anchor="w", pady=(2, 0))

        ctk.CTkLabel(row, text=thread_id or "Missing", anchor="w", text_color="gray").grid(
            row=0, column=3, sticky="ew", padx=6, pady=(6, 0)
        )
        ctk.CTkLabel(row, text=f"Last used: {last_used}", anchor="w", text_color="gray").grid(
            row=1, column=3, sticky="ew", padx=6, pady=(0, 6)
        )
        ctk.CTkLabel(
            row,
            text=self._shorten(notes, 72) if notes else "No notes",
            anchor="w",
            text_color="gray",
            wraplength=360,
        ).grid(row=0, column=4, rowspan=2, sticky="ew", padx=6, pady=(6, 6))

        validation_errors = viper_storage.validate_saved_thread_record(name, data)
        if validation_errors:
            ctk.CTkLabel(
                row,
                text="; ".join(validation_errors),
                anchor="w",
                text_color="#D9534F",
            ).grid(row=2, column=2, columnspan=3, sticky="ew", padx=6, pady=(0, 6))

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=5, rowspan=2, sticky="e", padx=6, pady=4)
        ctk.CTkButton(
            actions, text="Edit", width=52, command=lambda n=name: self.edit_thread(n)
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions, text="Open", width=55, command=lambda n=name: self.open_thread(n)
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Validate",
            width=70,
            command=lambda n=name: self.validate_thread(n),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Delete",
            width=60,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=lambda n=name: self.delete_thread(n),
        ).pack(side="left", padx=2)

    @staticmethod
    def _display_target_name(name: str, data: Optional[Dict[str, object]] = None) -> str:
        if isinstance(data, dict):
            site_title = viper_client.clean_thread_title(str(data.get("site_title") or ""))
            if site_title:
                return site_title
        return str(name or "").strip() or "Untitled target"

    def _add_target_url_link(self, parent: Any, url: str) -> None:
        if not url:
            ctk.CTkLabel(
                parent,
                text="No URL saved",
                anchor="w",
                text_color="gray",
            ).pack(fill="x", anchor="w", pady=(2, 0))
            return

        link_label = ctk.CTkLabel(
            parent,
            text=url,
            anchor="w",
            text_color="#2B78D6",
            wraplength=500,
            cursor="hand2",
        )
        link_label.pack(fill="x", anchor="w", pady=(2, 0))
        link_label.bind("<Button-1>", lambda _event, link=url: self.open_url(link))

    def toggle_target_expanded(self, name: str) -> None:
        expanded_targets = getattr(self, "expanded_targets", {})
        expanded_targets[name] = not expanded_targets.get(name, False)
        self.expanded_targets = expanded_targets
        self.refresh_list()

    @staticmethod
    def open_url(url: str) -> None:
        if not open_supported_url(url):
            messagebox.showerror("Open Target", "Only ViperGirls links can be opened from here.")

    @staticmethod
    def _shorten(value: str, max_len: int) -> str:
        if len(value) <= max_len:
            return value
        return f"{value[: max_len - 3]}..."

    def _selected_target_names(self) -> List[str]:
        selected = []
        for name, variable in self.selected_targets.items():
            try:
                if variable.get():
                    selected.append(name)
            except Exception:
                continue
        return selected

    def _busy_buttons(self) -> List[Any]:
        return [
            button
            for button in (
                getattr(self, "save_button", None),
                getattr(self, "refresh_names_button", None),
            )
            if button is not None
        ]

    def _run_in_background(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run network work on a worker thread; apply its result on the Tk thread.

        Title fetches go through the sidecar and can take several seconds per
        target, so they must never block the UI thread.
        """
        buttons = self._busy_buttons()
        for button in buttons:
            button.configure(state="disabled")

        def _finish(result: Any, error: Optional[BaseException]) -> None:
            for button in buttons:
                button.configure(state="normal")
            if error is not None:
                logger.error(f"ViperGirls target task failed: {error}")
                messagebox.showerror("Posting Targets", f"Operation failed:\n{error}")
                return
            done(result)

        def _task() -> None:
            try:
                result = work()
            except BaseException as exc:  # surfaced on the Tk thread
                self.after(0, lambda exc=exc: _finish(None, exc))
                return
            self.after(0, lambda: _finish(result, None))

        threading.Thread(target=_task, name="ViperTargetsWorker", daemon=True).start()

    def save_target(self) -> None:
        fallback_name = self.ent_name.get().strip()
        target = self.ent_url.get().strip()
        tags = self.ent_tags.get().strip()
        notes = self.ent_notes.get().strip()
        old_name = self.editing_name
        existing = self.saved_threads.get(old_name or fallback_name, {})
        existing_names = list(self.saved_threads.keys())

        def _work():
            try:
                return viper_client.build_site_named_thread_record(
                    fallback_name,
                    target,
                    existing=existing,
                    notes=notes,
                    tags=tags,
                    existing_names=existing_names,
                    exclude=old_name,
                )
            except viper_storage.ThreadTargetError as exc:
                return exc

        def _done(result):
            if isinstance(result, viper_storage.ThreadTargetError):
                messagebox.showerror("Invalid Target", str(result))
                return
            name, record, fetched_title = result
            self._apply_saved_target(name, record, fetched_title, old_name)

        self._run_in_background(_work, _done)

    def _apply_saved_target(
        self, name: str, record: Dict[str, object], fetched_title: str, old_name: Optional[str]
    ) -> None:
        if not fetched_title:
            logger.warning(
                f"Saved ViperGirls target '{name}' without a live site title; using fallback name."
            )

        duplicate_thread = self._find_duplicate_thread_id(
            str(record["thread_id"]), exclude=old_name
        )
        if duplicate_thread and not messagebox.askyesno(
            "Duplicate Thread ID",
            (
                f"'{duplicate_thread}' already uses thread ID {record['thread_id']}.\n\n"
                "Save this target anyway?"
            ),
        ):
            return

        updated = dict(self.saved_threads)
        if old_name and old_name != name:
            updated.pop(old_name, None)
        updated[name] = record

        try:
            viper_storage.save_saved_threads(updated)
        except OSError as exc:
            messagebox.showerror("Save Failed", f"Failed to save posting targets:\n{exc}")
            return

        self.saved_threads = updated
        self.cancel_edit(clear_fields=True)
        self.refresh_list()
        self._notify_changed()

    def refresh_target_names(self) -> None:
        names = self._selected_target_names() or list(self.saved_threads)
        if not names:
            messagebox.showwarning("Refresh Names", "No saved targets are available to refresh.")
            return

        snapshot = dict(self.saved_threads)
        editing_name = self.editing_name
        expanded_targets = dict(getattr(self, "expanded_targets", {}))

        def _work():
            updated = dict(snapshot)
            renamed = 0
            failed = 0
            current_editing = editing_name
            expanded = dict(expanded_targets)
            for current_name in names:
                record = updated.get(current_name)
                if not isinstance(record, dict):
                    failed += 1
                    continue

                target = viper_storage._import_record_target(record)
                try:
                    new_name, new_record, fetched_title = (
                        viper_client.build_site_named_thread_record(
                            current_name,
                            target,
                            existing=record,
                            notes=record.get("notes"),
                            tags=record.get("tags"),
                            existing_names=updated.keys(),
                            exclude=current_name,
                            fetch_title=True,
                        )
                    )
                except viper_storage.ThreadTargetError:
                    failed += 1
                    continue

                if not fetched_title:
                    failed += 1
                    continue

                if new_name != current_name:
                    updated.pop(current_name, None)
                    if current_editing == current_name:
                        current_editing = new_name
                    if current_name in expanded:
                        expanded[new_name] = expanded.pop(current_name)
                updated[new_name] = new_record
                renamed += 1
            return updated, renamed, failed, current_editing, expanded

        def _done(result):
            updated, renamed, failed, current_editing, expanded = result
            if renamed:
                try:
                    viper_storage.save_saved_threads(updated)
                except OSError as exc:
                    messagebox.showerror(
                        "Refresh Names Failed", f"Failed to save refreshed targets:\n{exc}"
                    )
                    return
                self.saved_threads = updated
                self.editing_name = current_editing
                self.expanded_targets = expanded
                self.refresh_list()
                self._notify_changed()

            messagebox.showinfo(
                "Refresh Names",
                f"Updated {renamed} target name(s). Failed to fetch {failed} title(s).",
            )

        self._run_in_background(_work, _done)

    def _find_duplicate_thread_id(
        self, thread_id: str, exclude: Optional[str] = None
    ) -> Optional[str]:
        for name, data in self.saved_threads.items():
            if name == exclude:
                continue
            if str(data.get("thread_id") or "") == thread_id:
                return name
        return None

    def edit_thread(self, name: str) -> None:
        data = self.saved_threads.get(name)
        if not data:
            return
        self.editing_name = name
        self.form_title_label.configure(text="Edit Posting Target")
        self.save_button.configure(text="Update Target")
        self.cancel_edit_button.configure(state="normal")
        self.ent_name.delete(0, "end")
        self.ent_name.insert(0, name)
        self.ent_url.delete(0, "end")
        self.ent_url.insert(0, str(data.get("url") or ""))
        self.ent_tags.delete(0, "end")
        self.ent_tags.insert(0, viper_storage.format_tags(data.get("tags")))
        self.ent_notes.delete(0, "end")
        self.ent_notes.insert(0, str(data.get("notes") or ""))

    def cancel_edit(self, clear_fields: bool = True) -> None:
        self.editing_name = None
        self.form_title_label.configure(text="Add Posting Target")
        self.save_button.configure(text="Save Target")
        self.cancel_edit_button.configure(state="disabled")
        if clear_fields:
            self.ent_name.delete(0, "end")
            self.ent_url.delete(0, "end")
            self.ent_tags.delete(0, "end")
            self.ent_notes.delete(0, "end")

    def open_thread(self, name: str) -> None:
        data = self.saved_threads.get(name, {})
        url = str(data.get("url") or "")
        if not url:
            messagebox.showerror("Open Target", "This target does not have a URL.")
            return
        self.open_url(url)

    def validate_thread(self, name: str) -> None:
        data = self.saved_threads.get(name, {})
        errors = viper_storage.validate_saved_thread_record(name, data)
        if errors:
            messagebox.showerror("Invalid Target", f"'{name}' is invalid:\n\n" + "\n".join(errors))
            return
        thread_id = str(
            data.get("thread_id")
            or viper_storage.extract_thread_id(str(data.get("url") or ""))
            or ""
        )
        messagebox.showinfo("Target Valid", f"'{name}' resolves to thread ID {thread_id}.")

    def delete_thread(self, name: str) -> None:
        if name not in self.saved_threads:
            return
        if not messagebox.askyesno("Delete Target", f"Delete '{name}'?"):
            return

        updated = dict(self.saved_threads)
        updated.pop(name, None)
        try:
            viper_storage.save_saved_threads(updated)
        except OSError as exc:
            messagebox.showerror("Delete Failed", f"Failed to save posting targets:\n{exc}")
            return

        self.saved_threads = updated
        if self.editing_name == name:
            self.cancel_edit(clear_fields=True)
        self.refresh_list()
        self._notify_changed()

    def bulk_delete_selected(self) -> None:
        names = self._selected_target_names()
        if not names:
            messagebox.showwarning("Delete Selected", "Select one or more targets to delete.")
            return
        if not messagebox.askyesno("Delete Selected", f"Delete {len(names)} selected target(s)?"):
            return

        updated = dict(self.saved_threads)
        for name in names:
            updated.pop(name, None)
        try:
            viper_storage.save_saved_threads(updated)
        except OSError as exc:
            messagebox.showerror("Delete Failed", f"Failed to save posting targets:\n{exc}")
            return

        self.saved_threads = updated
        if self.editing_name in names:
            self.cancel_edit(clear_fields=True)
        self.refresh_list()
        self._notify_changed()

    def import_targets(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Import ViperGirls Targets",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return

        overwrite = True
        duplicates = self._duplicate_names_in_import(filepath)
        if duplicates:
            overwrite = messagebox.askyesno(
                "Import Targets",
                (
                    f"{len(duplicates)} imported target name(s) already exist.\n\n"
                    "Overwrite matching saved targets?"
                ),
            )

        try:
            merged, imported, skipped = viper_storage.import_saved_threads_file(
                filepath,
                existing=self.saved_threads,
                overwrite=overwrite,
            )
            viper_storage.save_saved_threads(merged)
        except Exception as exc:
            messagebox.showerror("Import Failed", f"Could not import targets:\n{exc}")
            return

        self.saved_threads = merged
        self.refresh_list()
        self._notify_changed()
        messagebox.showinfo(
            "Import Complete",
            f"Imported {imported} target(s). Skipped {skipped} target(s).",
        )

    def _duplicate_names_in_import(self, filepath: str) -> List[str]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            raw_targets = viper_storage._targets_from_import_payload(raw_data)
        except Exception:
            return []
        return [
            str(name).strip() for name in raw_targets if str(name).strip() in self.saved_threads
        ]

    def export_all_targets(self) -> None:
        self._export_targets(sorted(self.saved_threads))

    def export_selected_targets(self) -> None:
        names = self._selected_target_names()
        if not names:
            messagebox.showwarning("Export Selected", "Select one or more targets to export.")
            return
        self._export_targets(names)

    def _export_targets(self, names: List[str]) -> None:
        if not names:
            messagebox.showwarning("Export Targets", "No saved targets are available to export.")
            return
        filepath = filedialog.asksaveasfilename(
            title="Export ViperGirls Targets",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return
        try:
            exported = viper_storage.export_saved_threads_file(
                filepath, self.saved_threads, names=names
            )
        except OSError as exc:
            messagebox.showerror("Export Failed", f"Could not export targets:\n{exc}")
            return
        messagebox.showinfo("Export Complete", f"Exported {exported} target(s).")

    def open_credentials(self) -> None:
        def _after_save():
            if hasattr(self.parent, "_load_credentials"):
                self.parent._load_credentials()
            self._update_health()

        CredentialsManager.create_credentials_dialog(parent=self, on_save_callback=_after_save)

    def test_login(self) -> None:
        creds = CredentialsManager.load_all_credentials()
        user = creds.get("vg_user", "")
        pwd = creds.get("vg_pass", "")
        if not user or not pwd:
            messagebox.showerror(
                "Missing Credentials", "Set ViperGirls credentials before testing login."
            )
            self._update_health()
            return

        self.test_login_button.configure(state="disabled", text="Testing...")

        def _task():
            ok = viper_client.ViperGirlsAPI().login(user, pwd)

            def _finish():
                self.test_login_button.configure(state="normal", text="Test Login")
                if ok:
                    messagebox.showinfo("Login Successful", "ViperGirls login succeeded.")
                else:
                    messagebox.showerror("Login Failed", "ViperGirls login failed.")

            try:
                self.after(0, _finish)
            except Exception:
                logger.debug("ViperGirls target window closed before login test completed.")

        threading.Thread(target=_task, daemon=True).start()

    def open_data_folder(self) -> None:
        os.makedirs(viper_storage._USER_DATA_DIR, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(viper_storage._USER_DATA_DIR)
            else:
                webbrowser.open(viper_storage._USER_DATA_DIR)
        except Exception as exc:
            messagebox.showerror(
                "Open Folder Failed", f"Could not open:\n{viper_storage._USER_DATA_DIR}\n\n{exc}"
            )

    def open_history(self) -> None:
        PostingHistoryWindow(self)

    def _notify_changed(self) -> None:
        if self.callback:
            self.callback()


class PostingHistoryWindow(ctk.CTkToplevel):
    """View and manage ViperGirls posting history."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.history: List[Dict[str, str]] = []

        self.title("ViperGirls Posting History")
        self.geometry("1040x640")
        self.minsize(880, 480)
        self.resizable(True, True)
        self.transient(parent)
        self.lift()
        self.focus_force()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_history_list()
        self.refresh_history()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Posting History",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=8)

        self.history_count_label = ctk.CTkLabel(header, text="", text_color="gray")
        self.history_count_label.grid(row=0, column=1, sticky="w", padx=(4, 10), pady=8)

        ctk.CTkButton(
            header,
            text="Refresh",
            width=90,
            command=self.refresh_history,
        ).grid(row=0, column=2, padx=4, pady=8)
        ctk.CTkButton(
            header,
            text="Clear History",
            width=120,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=self.clear_history,
        ).grid(row=0, column=3, padx=(4, 10), pady=8)

    def _build_history_list(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(self, label_text="Recent Posting Attempts")
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.scroll.grid_columnconfigure(0, weight=1)

    def refresh_history(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()

        self.history = list(reversed(viper_storage.load_posting_history()))
        self.history_count_label.configure(
            text=f"{len(self.history)} saved attempt(s) - {viper_storage.POSTING_HISTORY_FILE}"
        )

        if not self.history:
            ctk.CTkLabel(
                self.scroll,
                text="No ViperGirls posting history yet.",
                text_color="gray",
            ).grid(row=0, column=0, sticky="w", padx=12, pady=18)
            return

        for row_index, entry in enumerate(self.history):
            self._add_history_row(row_index, entry)

    def _add_history_row(self, row_index: int, entry: Dict[str, str]) -> None:
        row = ctk.CTkFrame(self.scroll)
        row.grid(row=row_index, column=0, sticky="ew", padx=4, pady=3)
        row.grid_columnconfigure(1, weight=1)

        status = str(entry.get("status") or "unknown").lower()
        status_color = "#2FA572" if status == "success" else "#D9534F"
        ctk.CTkLabel(
            row,
            text=status.upper(),
            text_color=status_color,
            width=70,
            anchor="w",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, rowspan=2, sticky="nw", padx=8, pady=8)

        title = (
            f"{entry.get('batch_name', 'Batch')} -> "
            f"{entry.get('target_name', 'Unknown target')} "
            f"(thread {entry.get('thread_id') or 'unknown'})"
        )
        ctk.CTkLabel(row, text=title, anchor="w", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=1, sticky="ew", padx=6, pady=(7, 1)
        )

        detail = entry.get("timestamp", "")
        error = str(entry.get("error") or "")
        if error:
            detail = f"{detail} - {error}"
        ctk.CTkLabel(
            row,
            text=detail,
            anchor="w",
            text_color="gray",
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=(0, 7))

        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=2, sticky="e", padx=8, pady=6)
        ctk.CTkButton(
            actions,
            text="Copy Post",
            width=82,
            command=lambda e=entry: self.copy_post_text(e),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Copy Error",
            width=84,
            command=lambda e=entry: self.copy_error(e),
            state="normal" if error else "disabled",
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="Open",
            width=58,
            command=lambda e=entry: self.open_target(e),
            state="normal" if entry.get("target_url") else "disabled",
        ).pack(side="left", padx=2)

    def copy_post_text(self, entry: Dict[str, str]) -> None:
        self._copy_text(entry.get("post_text", ""), "Post text copied.")

    def copy_error(self, entry: Dict[str, str]) -> None:
        self._copy_text(entry.get("error", ""), "Error copied.")

    def _copy_text(self, text: str, success_message: str) -> None:
        if not text:
            messagebox.showwarning("Copy", "No text is available to copy.")
            return
        try:
            pyperclip.copy(text)
            messagebox.showinfo("Copy", success_message)
        except (OSError, pyperclip.PyperclipException) as exc:
            messagebox.showerror("Copy Failed", f"Could not copy text:\n{exc}")

    def open_target(self, entry: Dict[str, str]) -> None:
        url = viper_storage.safe_target_url(
            str(entry.get("target_url") or ""), str(entry.get("thread_id") or "")
        )
        if not url:
            messagebox.showerror("Open Target", "No ViperGirls target URL is available.")
            return
        open_supported_url(url)

    def clear_history(self) -> None:
        if not self.history:
            return
        if not messagebox.askyesno("Clear Posting History", "Clear all posting history?"):
            return
        try:
            viper_storage.clear_posting_history()
        except OSError as exc:
            messagebox.showerror("Clear Failed", f"Could not clear posting history:\n{exc}")
            return
        self.refresh_history()
