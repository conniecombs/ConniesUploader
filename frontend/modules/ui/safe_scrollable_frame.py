# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Safe scrollable frame widget with canvas master checking."""

import customtkinter as ctk


class SafeScrollableFrame(ctk.CTkScrollableFrame):
    """Enhanced scrollable frame with safe canvas master checking.

    Prevents errors when checking if a widget's master is a canvas,
    handling edge cases gracefully.
    """

    def check_if_master_is_canvas(self, widget):
        """Check if the given widget's master is a canvas.

        Args:
            widget: The widget to check, can be a widget object or string name

        Returns:
            bool: True if the widget's master is a canvas, False otherwise
        """
        if widget is None:
            return False
        if isinstance(widget, str):
            try:
                widget = self.winfo_toplevel().nametowidget(widget)
            except Exception:
                return False
        try:
            if widget == self._parent_canvas:
                return True
            elif hasattr(widget, "master") and widget.master is not None:
                return self.check_if_master_is_canvas(widget.master)
            else:
                return False
        except Exception:
            return False
