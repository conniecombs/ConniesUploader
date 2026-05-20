# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from loguru import logger
from .widgets import CollapsibleGroupFrame


class DragDropMixin:
    """
    Mixin class that handles drag-and-drop operations, context menus,
    and row/group reordering for UploaderApp.
    Requires the host class to have:
      - self.groups
      - self.file_widgets
      - self.drag_data
      - self.context_menu
      - self.thumb_executor
      - self.var_show_previews
    """

    def drop_files(self, event):
        """Handle external file/folder drops from the file system."""
        logger.info(f"🎯 DROP EVENT RECEIVED!")
        logger.info(f"   Raw event.data: {event.data}")
        logger.info(f"   Event coordinates: ({event.x_root}, {event.y_root})")

        try:
            files = self.tk.splitlist(event.data)
            logger.info(f"   Parsed {len(files)} file(s)/folder(s): {files}")
        except Exception as e:
            logger.error(f"   ✗ Failed to parse drop data: {e}", exc_info=True)
            messagebox.showerror("Drop Error", f"Failed to parse dropped files: {e}")
            return

        if not files:
            logger.warning("   ⚠ No files in drop event")
            return

        x, y = event.x_root, event.y_root
        target_group = None

        try:
            widget = self.winfo_containing(x, y)
            logger.debug(f"   Drop target widget: {widget}")
            while widget and widget != self:
                for g in self.groups:
                    if widget in (g, g.header, g.content_frame) or str(g) in str(widget):
                        target_group = g
                        break
                if target_group:
                    break
                widget = widget.master

            if target_group:
                logger.info(f"   Target group: {target_group.title}")
            else:
                logger.info(f"   No specific group targeted, will create new group(s)")

        except AttributeError as e:
            logger.warning(f"   Could not find target group for drop: {e}")

        logger.info(f"   Calling _process_files()...")
        self._process_files(files, target_group)

    def _clear_highlights(self, event=None):
        if self.highlighted_row:
            try:
                self.highlighted_row.configure(fg_color="transparent")
            except (tk.TclError, AttributeError) as e:
                logger.debug(f"Could not clear highlight: {e}")
            self.highlighted_row = None

    def _on_group_drag_start(self, event, group):
        self.drag_data["item"] = group
        self.drag_data["type"] = "group"
        self.drag_data["widget_start"] = group
        group.header.configure(fg_color="#555555")
        self.configure(cursor="fleur")

    def _on_group_drag_motion(self, event):
        if self.drag_data["type"] != "group":
            return
        y_root = event.y_root

        for target in self.groups:
            if target == self.drag_data["item"]:
                continue
            t_y = target.winfo_rooty()
            t_h = target.winfo_height()
            if y_root > t_y and y_root < t_y + t_h:
                idx_src = self.groups.index(self.drag_data["item"])
                idx_dst = self.groups.index(target)
                self.groups[idx_src], self.groups[idx_dst] = (
                    self.groups[idx_dst],
                    self.groups[idx_src],
                )

                for g in self.groups:
                    g.pack_forget()
                for g in self.groups:
                    g.pack(fill="x", pady=2, padx=2)
                break

    def _on_group_drag_end(self, event):
        if self.drag_data["widget_start"]:
            self.drag_data["widget_start"].header.configure(fg_color="transparent")
        self.drag_data = {"item": None, "type": None}
        self.configure(cursor="")

    def _on_row_drag_start(self, event, row_widget, filepath):
        self.drag_data["item"] = filepath
        self.drag_data["type"] = "file"
        self.drag_data["widget_start"] = row_widget
        row_widget.configure(
            fg_color="#3A7EBF" if ctk.get_appearance_mode() == "Light" else "#1F538D"
        )
        self.configure(cursor="hand2")

    def _on_row_drag_motion(self, event):
        pass

    def _on_row_drag_end(self, event):
        self.configure(cursor="")
        if self.drag_data["widget_start"]:
            self.drag_data["widget_start"].configure(fg_color="transparent")

        fp = self.drag_data["item"]
        if not fp:
            return

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        target_group, target_row_widget = self._find_target_row_and_group(target_widget)

        if target_group:
            with self.lock:
                current_group = self.file_widgets[fp]["group"]

            if target_group == current_group:
                if target_row_widget and target_row_widget != self.drag_data["widget_start"]:
                    target_fp = None
                    with self.lock:
                        for f, w in self.file_widgets.items():
                            if w["row"] == target_row_widget:
                                target_fp = f
                                break
                    if target_fp:
                        current_group.files.remove(fp)
                        idx = current_group.files.index(target_fp)
                        current_group.files.insert(idx, fp)
                        with self.lock:
                            self.file_widgets[fp]["row"].pack(before=target_row_widget)
            else:
                self._move_file_to_group(
                    fp, current_group, target_group, before_widget=target_row_widget
                )

        self.drag_data = {"item": None, "type": None}

    def _find_target_row_and_group(self, widget):
        if widget is None:
            return None, None
        if isinstance(widget, str):
            try:
                widget = self.nametowidget(widget)
            except Exception:
                return None, None

        curr = widget
        found_group = None
        found_row = None

        while curr and curr != self:
            if isinstance(curr, CollapsibleGroupFrame):
                found_group = curr
            if not found_row:
                with self.lock:
                    for data in self.file_widgets.values():
                        if data["row"] == curr:
                            found_row = curr
                            break
            if found_group:
                break
            try:
                curr = curr.master
            except AttributeError:
                break

        return found_group, found_row

    def _move_file_to_group(self, fp, old_group, new_group, before_widget=None):
        old_group.remove_file(fp)
        if before_widget:
            target_fp = None
            with self.lock:
                for f, w in self.file_widgets.items():
                    if w["row"] == before_widget:
                        target_fp = f
                        break
            if target_fp and target_fp in new_group.files:
                idx = new_group.files.index(target_fp)
                new_group.files.insert(idx, fp)
            else:
                new_group.add_file(fp)
        else:
            new_group.add_file(fp)

        with self.lock:
            w_data = self.file_widgets[fp]
            old_row = w_data["row"]
        old_row.destroy()

        self._create_row(fp, None, new_group)
        with self.lock:
            new_row = self.file_widgets[fp]["row"]

        if before_widget:
            try:
                new_row.pack(before=before_widget)
            except (tk.TclError, AttributeError) as e:
                logger.debug(f"Could not pack row before widget: {e}")

        if self.var_show_previews.get():
            self.thumb_executor.submit(self._thumb_worker, [fp], new_group, True)

    def _show_group_context(self, event, group):
        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="Delete Batch", command=lambda: self._delete_group(group)
        )
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _show_row_context(self, event, filepath):
        self._clear_highlights()
        with self.lock:
            row = self.file_widgets[filepath]["row"]
        self.highlighted_row = row
        row.configure(fg_color="#E0E0E0" if ctk.get_appearance_mode() == "Light" else "#404040")

        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="Delete Image", command=lambda: self._delete_file(filepath)
        )
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _delete_group(self, group):
        if messagebox.askyesno("Confirm", f"Delete batch '{group.title}'?"):
            for fp in list(group.files):
                with self.lock:
                    if fp in self.file_widgets:
                        # Clean up image reference to prevent memory leak
                        img_ref = self.file_widgets[fp].get("image_ref")
                        if img_ref and img_ref in self.image_refs:
                            self.image_refs.remove(img_ref)
                        del self.file_widgets[fp]
            if group in self.groups:
                self.groups.remove(group)
            group.destroy()

    def _delete_file(self, filepath):
        with self.lock:
            if filepath not in self.file_widgets:
                self._clear_highlights()
                return
            group = self.file_widgets[filepath]["group"]
            row = self.file_widgets[filepath]["row"]
            # Clean up image reference to prevent memory leak
            img_ref = self.file_widgets[filepath].get("image_ref")
            if img_ref and img_ref in self.image_refs:
                self.image_refs.remove(img_ref)
        if group.winfo_exists():
            group.remove_file(filepath)
        row.destroy()
        with self.lock:
            del self.file_widgets[filepath]
        self._clear_highlights()
