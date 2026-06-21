# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import os

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from loguru import logger
from . import config
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

    _SHIFT_MASK = 0x0001
    _CTRL_MASK = 0x0004

    def drop_files(self, event):
        """Handle external file/folder drops from the file system."""
        logger.info("DROP EVENT RECEIVED!")
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
            logger.warning("   No files in drop event")
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
                logger.info("   No specific group targeted, will create new group(s)")

        except AttributeError as e:
            logger.warning(f"   Could not find target group for drop: {e}")

        logger.info("   Calling _process_files()...")
        self._process_files(files, target_group)

    def _clear_highlights(self, event=None):
        if self.highlighted_row:
            try:
                self._restore_row_color(self.highlighted_row)
            except (tk.TclError, AttributeError) as e:
                logger.debug(f"Could not clear highlight: {e}")
            self.highlighted_row = None

    def _queue_reorder_allowed(self):
        if vars(self).get("is_uploading", False):
            if hasattr(self, "add_activity"):
                self.add_activity(
                    "Wait for the current upload to finish before reordering.",
                    "warning",
                )
            return False
        return True

    def _selected_file_set(self):
        selection = vars(self).get("selected_files")
        if not isinstance(selection, set):
            selection = set(selection or [])
            self.selected_files = selection
        return selection

    def _ordered_filepaths(self):
        with self.lock:
            return [
                filepath
                for group in self.groups
                for filepath in getattr(group, "files", [])
                if filepath in self.file_widgets
            ]

    def _row_color_for_file(self, filepath):
        if filepath in self._selected_file_set():
            return "#CFE8FF" if ctk.get_appearance_mode() == "Light" else "#244B68"
        return "transparent"

    def _restore_row_color(self, row_widget):
        filepath = self._filepath_for_row(row_widget)
        self._configure_drop_color(row_widget, self._row_color_for_file(filepath))

    def _apply_file_selection_styles(self):
        with self.lock:
            rows = [
                (filepath, data.get("row"))
                for filepath, data in self.file_widgets.items()
                if data.get("row")
            ]

        for filepath, row in rows:
            self._configure_drop_color(row, self._row_color_for_file(filepath))

    def _set_selected_files(self, filepaths, anchor=None):
        ordered = self._ordered_filepaths()
        valid = set(ordered)
        selected = [filepath for filepath in ordered if filepath in filepaths and filepath in valid]
        selection = self._selected_file_set()
        selection.clear()
        selection.update(selected)

        if anchor in valid:
            self.selection_anchor = anchor
        elif selected:
            self.selection_anchor = selected[-1]
        else:
            self.selection_anchor = None

        self._apply_file_selection_styles()

    def _select_file_range(self, filepath, append=False):
        ordered = self._ordered_filepaths()
        if filepath not in ordered:
            return

        anchor = vars(self).get("selection_anchor")
        if anchor not in ordered:
            anchor = filepath
            self.selection_anchor = filepath

        start_index = ordered.index(anchor)
        end_index = ordered.index(filepath)
        if start_index > end_index:
            start_index, end_index = end_index, start_index

        selection = self._selected_file_set()
        if not append:
            selection.clear()
        selection.update(ordered[start_index: end_index + 1])
        self._apply_file_selection_styles()

    def _toggle_file_selection(self, filepath):
        if filepath not in self._ordered_filepaths():
            return

        selection = self._selected_file_set()
        if filepath in selection:
            selection.remove(filepath)
            if vars(self).get("selection_anchor") == filepath:
                self.selection_anchor = next(iter(selection), None)
        else:
            selection.add(filepath)
            self.selection_anchor = filepath

        self._apply_file_selection_styles()

    def _update_selection_from_click(self, event, filepath):
        state = int(getattr(event, "state", 0) or 0)
        is_ctrl = bool(state & self._CTRL_MASK)
        is_shift = bool(state & self._SHIFT_MASK)
        selection = self._selected_file_set()

        if is_shift:
            self._select_file_range(filepath, append=is_ctrl)
        elif is_ctrl:
            self._toggle_file_selection(filepath)
        elif filepath in selection and len(selection) > 1:
            self.selection_anchor = filepath
            self._apply_file_selection_styles()
        else:
            self._set_selected_files([filepath], anchor=filepath)

    def _ensure_context_selection(self, filepath):
        if filepath not in self._selected_file_set():
            self._set_selected_files([filepath], anchor=filepath)

    def _selected_files_for_action(self, filepath):
        selection = set(self._selected_file_set())
        with self.lock:
            row_data = self.file_widgets.get(filepath)
            active_group = row_data.get("group") if row_data else None
            if not active_group or filepath not in self.file_widgets:
                return []

            if filepath in selection:
                selected_in_group = [
                    fp
                    for fp in active_group.files
                    if fp in selection and fp in self.file_widgets
                ]
                if selected_in_group:
                    return selected_in_group

        return [filepath]

    def _prune_selection(self, filepaths):
        removed = set(filepaths)
        selection = self._selected_file_set()
        selection.difference_update(removed)
        if vars(self).get("selection_anchor") in removed:
            self.selection_anchor = next(iter(selection), None)

    def _reset_drag_data(self):
        self.drag_data = {
            "item": None,
            "items": [],
            "type": None,
            "y_start": 0,
            "widget_start": None,
            "target_row": None,
            "target_group": None,
        }

    def _configure_drop_color(self, widget, color):
        if not widget:
            return
        try:
            widget.configure(fg_color=color)
        except (tk.TclError, AttributeError) as e:
            logger.debug(f"Could not update drag highlight: {e}")

    def _clear_drag_target(self):
        target_row = self.drag_data.get("target_row")
        start_row = self.drag_data.get("widget_start")
        if target_row and target_row != start_row:
            self._restore_row_color(target_row)

        target_group = self.drag_data.get("target_group")
        if target_group:
            self._configure_drop_color(getattr(target_group, "header", None), "transparent")

        self.drag_data["target_row"] = None
        self.drag_data["target_group"] = None

    def _highlight_drag_target(self, target_group, target_row):
        self._clear_drag_target()
        if target_row and target_row != self.drag_data.get("widget_start"):
            color = "#D6EAF8" if ctk.get_appearance_mode() == "Light" else "#26384A"
            self._configure_drop_color(target_row, color)
            self.drag_data["target_row"] = target_row
        elif target_group:
            color = "#DDEEFF" if ctk.get_appearance_mode() == "Light" else "#253243"
            self._configure_drop_color(getattr(target_group, "header", None), color)
            self.drag_data["target_group"] = target_group

    def _filepath_for_row(self, row_widget):
        if not row_widget:
            return None
        with self.lock:
            for filepath, data in self.file_widgets.items():
                if data.get("row") == row_widget:
                    return filepath
        return None

    def _repack_group_rows(self, group):
        with self.lock:
            ordered_rows = [
                self.file_widgets.get(filepath, {}).get("row") for filepath in group.files
            ]

        for row in ordered_rows:
            if not row:
                continue
            try:
                if row.winfo_exists():
                    row.pack_forget()
                    row.pack(fill="x", pady=1)
            except (tk.TclError, AttributeError) as e:
                logger.debug(f"Could not repack queue row: {e}")

    def _refresh_after_reorder(self):
        if hasattr(self, "_refresh_queue_state"):
            self._refresh_queue_state()

    def _announce_file_move(self, filepath):
        if hasattr(self, "add_activity"):
            self.add_activity(f"Moved image: {os.path.basename(filepath)}.")

    def _announce_files_move(self, filepaths):
        if not filepaths or not hasattr(self, "add_activity"):
            return
        if len(filepaths) == 1:
            self._announce_file_move(filepaths[0])
        else:
            self.add_activity(f"Moved {len(filepaths)} images.")

    def _move_files_within_group(
        self, filepaths, group, insert_index=None, target_filepath=None, announce=True
    ):
        if not self._queue_reorder_allowed():
            return False

        requested = set(filepaths)
        with self.lock:
            moving_files = [filepath for filepath in group.files if filepath in requested]
            if not moving_files:
                return False
            if target_filepath and target_filepath in moving_files:
                return False

            original_files = list(group.files)
            remaining_files = [filepath for filepath in group.files if filepath not in requested]
            if target_filepath:
                if target_filepath not in remaining_files:
                    return False
                insert_index = remaining_files.index(target_filepath)
            elif insert_index is None:
                insert_index = len(remaining_files)

            insert_index = max(0, min(insert_index, len(remaining_files)))
            group.files[:] = (
                remaining_files[:insert_index]
                + moving_files
                + remaining_files[insert_index:]
            )

            if group.files == original_files:
                return False

        self._repack_group_rows(group)
        self._refresh_after_reorder()
        self._apply_file_selection_styles()
        if announce:
            self._announce_files_move(moving_files)
        return True

    def _move_files_before(self, filepaths, group, target_filepath, announce=True):
        return self._move_files_within_group(
            filepaths,
            group,
            target_filepath=target_filepath,
            announce=announce,
        )

    def _move_selected_files_relative(self, filepath, direction):
        if not self._queue_reorder_allowed():
            return False

        moving_files = self._selected_files_for_action(filepath)
        with self.lock:
            data = self.file_widgets.get(filepath)
            group = data.get("group") if data else None
            if not group:
                return False
            moving_in_group = [fp for fp in group.files if fp in set(moving_files)]
            if not moving_in_group:
                return False

            first_index = min(group.files.index(fp) for fp in moving_in_group)
            remaining_count = len(group.files) - len(moving_in_group)

        if direction == "top":
            new_index = 0
        elif direction == "up":
            new_index = first_index - 1
        elif direction == "down":
            new_index = first_index + 1
        elif direction == "bottom":
            new_index = remaining_count
        else:
            return False

        return self._move_files_within_group(moving_in_group, group, new_index)

    def _move_file_to_index(self, filepath, group, new_index, announce=True):
        if not self._queue_reorder_allowed():
            return False

        with self.lock:
            if filepath not in self.file_widgets or filepath not in group.files:
                return False
            if len(group.files) < 2:
                return False

            old_index = group.files.index(filepath)
            new_index = max(0, min(new_index, len(group.files) - 1))
            if old_index == new_index:
                return False

            group.files.insert(new_index, group.files.pop(old_index))

        self._repack_group_rows(group)
        self._refresh_after_reorder()
        self._apply_file_selection_styles()
        if announce:
            self._announce_file_move(filepath)
        return True

    def _move_file_before(self, filepath, group, target_filepath, announce=True):
        return self._move_files_before([filepath], group, target_filepath, announce=announce)

    def _move_file_relative(self, filepath, direction):
        return self._move_selected_files_relative(filepath, direction)

    def _safe_file_mtime(self, filepath):
        try:
            return os.path.getmtime(filepath)
        except OSError:
            return 0

    def _sort_group_files(self, group, mode):
        if not self._queue_reorder_allowed():
            return False

        with self.lock:
            current_files = list(getattr(group, "files", []))
            if len(current_files) < 2:
                return False

            if mode == "name":
                sorted_files = sorted(
                    current_files,
                    key=lambda fp: config.natural_sort_key(os.path.basename(fp)),
                )
                activity = f"Sorted batch by name: {group.title}."
            elif mode == "modified":
                sorted_files = sorted(
                    current_files,
                    key=lambda fp: (
                        self._safe_file_mtime(fp),
                        config.natural_sort_key(os.path.basename(fp)),
                    ),
                )
                activity = f"Sorted batch by modified date: {group.title}."
            elif mode == "reverse":
                sorted_files = list(reversed(current_files))
                activity = f"Reversed batch order: {group.title}."
            else:
                return False

            if sorted_files == current_files:
                return False
            group.files[:] = sorted_files

        self._repack_group_rows(group)
        self._refresh_after_reorder()
        self._apply_file_selection_styles()
        if hasattr(self, "add_activity"):
            self.add_activity(activity)
        return True

    def _on_group_drag_start(self, event, group):
        if not self._queue_reorder_allowed():
            return
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
        self._reset_drag_data()
        self.configure(cursor="")
        self._refresh_after_reorder()

    def _on_row_drag_start(self, event, row_widget, filepath):
        if not self._queue_reorder_allowed():
            return
        self._update_selection_from_click(event, filepath)
        self.drag_data["item"] = filepath
        self.drag_data["items"] = self._selected_files_for_action(filepath)
        self.drag_data["type"] = "file"
        self.drag_data["widget_start"] = row_widget
        row_widget.configure(
            fg_color="#3A7EBF" if ctk.get_appearance_mode() == "Light" else "#1F538D"
        )
        self.configure(cursor="hand2")

    def _on_row_drag_motion(self, event):
        if self.drag_data.get("type") != "file":
            return

        try:
            target_widget = self.winfo_containing(event.x_root, event.y_root)
            target_group, target_row_widget = self._find_target_row_and_group(target_widget)
        except (tk.TclError, AttributeError) as e:
            logger.debug(f"Could not resolve drag target: {e}")
            return

        self._highlight_drag_target(target_group, target_row_widget)

    def _on_row_drag_end(self, event):
        self.configure(cursor="")
        start_row = self.drag_data.get("widget_start")
        if start_row:
            self._restore_row_color(start_row)
        self._clear_drag_target()

        fp = self.drag_data.get("item")
        moving_files = self.drag_data.get("items") or [fp]
        if not fp:
            self._reset_drag_data()
            return

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        target_group, target_row_widget = self._find_target_row_and_group(target_widget)

        if target_group:
            with self.lock:
                row_data = self.file_widgets.get(fp)
                current_group = row_data.get("group") if row_data else None

            if not current_group:
                self._reset_drag_data()
                return

            if target_group == current_group:
                if target_row_widget and target_row_widget != start_row:
                    target_fp = self._filepath_for_row(target_row_widget)
                    if target_fp:
                        self._move_files_before(moving_files, current_group, target_fp)
                elif not target_row_widget:
                    self._move_files_within_group(
                        moving_files,
                        current_group,
                        len(current_group.files) - len(set(moving_files)),
                    )
            else:
                self._move_files_to_group(moving_files, target_group, target_row_widget)

        self._reset_drag_data()

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
        if not self._queue_reorder_allowed():
            return False
        old_group.remove_file(fp)
        self._remove_empty_group_if_needed(old_group)
        if before_widget:
            target_fp = self._filepath_for_row(before_widget)
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

        self._create_row(fp, None, new_group, preview_requested=self.var_show_previews.get())
        with self.lock:
            new_row = self.file_widgets[fp]["row"]

        if before_widget:
            try:
                new_row.pack(before=before_widget)
            except (tk.TclError, AttributeError) as e:
                logger.debug(f"Could not pack row before widget: {e}")

        if self.var_show_previews.get():
            self.thumb_executor.submit(self._thumb_worker, [fp], new_group, True)

        self._refresh_after_reorder()
        return True

    def _move_files_to_group(self, filepaths, new_group, before_widget=None):
        if not self._queue_reorder_allowed():
            return False

        moved_files = []
        for filepath in filepaths:
            with self.lock:
                row_data = self.file_widgets.get(filepath)
                old_group = row_data.get("group") if row_data else None
            if not old_group or old_group == new_group:
                continue
            if self._move_file_to_group(filepath, old_group, new_group, before_widget):
                moved_files.append(filepath)

        if moved_files:
            self._apply_file_selection_styles()
            self._announce_files_move(moved_files)
        return bool(moved_files)

    def _show_group_context(self, event, group):
        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="Sort Batch by Name",
            command=lambda g=group: self._sort_group_files(g, "name"),
        )
        self.context_menu.add_command(
            label="Sort Batch by Modified Date",
            command=lambda g=group: self._sort_group_files(g, "modified"),
        )
        self.context_menu.add_command(
            label="Reverse Batch Order",
            command=lambda g=group: self._sort_group_files(g, "reverse"),
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Delete Batch", command=lambda: self._delete_group(group)
        )
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _show_row_context(self, event, filepath):
        self._clear_highlights()
        self._ensure_context_selection(filepath)
        with self.lock:
            row = self.file_widgets[filepath]["row"]
        self.highlighted_row = row
        row.configure(fg_color=self._row_color_for_file(filepath))

        self.context_menu.delete(0, "end")
        self.context_menu.add_command(
            label="Move to Top", command=lambda f=filepath: self._move_file_relative(f, "top")
        )
        self.context_menu.add_command(
            label="Move Up", command=lambda f=filepath: self._move_file_relative(f, "up")
        )
        self.context_menu.add_command(
            label="Move Down", command=lambda f=filepath: self._move_file_relative(f, "down")
        )
        self.context_menu.add_command(
            label="Move to Bottom",
            command=lambda f=filepath: self._move_file_relative(f, "bottom"),
        )
        self.context_menu.add_separator()
        with self.lock:
            state = self.file_widgets.get(filepath, {}).get("state")
        if state == "failed":
            self.context_menu.add_command(
                label="Retry Image", command=lambda: self._retry_file(filepath)
            )
            self.context_menu.add_command(
                label="Copy Error", command=lambda: self._copy_file_error(filepath)
            )
            self.context_menu.add_separator()
        self.context_menu.add_command(
            label="Delete Image", command=lambda: self._delete_file(filepath)
        )
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _delete_group(self, group):
        if messagebox.askyesno("Confirm", f"Delete batch '{group.title}'?"):
            deleted_files = list(group.files)
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
            self._prune_selection(deleted_files)
            if hasattr(self, "add_activity"):
                self.add_activity(f"Deleted batch: {group.title}.", "warning")
            if hasattr(self, "_refresh_queue_state"):
                self._refresh_queue_state()

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
        self._prune_selection([filepath])
        self._clear_highlights()
        if hasattr(self, "add_activity"):
            self.add_activity(f"Removed image: {os.path.basename(filepath)}.", "warning")
        self._remove_empty_group_if_needed(group)
        if hasattr(self, "_refresh_queue_state"):
            self._refresh_queue_state()

    def _remove_empty_group_if_needed(self, group):
        if not group or getattr(group, "files", None):
            return False

        if group in self.groups:
            self.groups.remove(group)

        try:
            if group.winfo_exists():
                group.destroy()
        except (tk.TclError, AttributeError):
            pass

        if hasattr(self, "add_activity"):
            self.add_activity(f"Removed empty batch: {group.title}.", "warning")
        return True
