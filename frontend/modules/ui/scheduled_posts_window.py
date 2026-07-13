import datetime
from tkinter import messagebox

import customtkinter as ctk

from modules.ui.safe_scrollable_frame import SafeScrollableFrame
from modules.viper_api import ViperGirlsAPI, extract_thread_id


class SchedulePostModal(ctk.CTkToplevel):
    def __init__(self, parent, text, saved_threads_data):
        super().__init__(parent)
        self.title("Schedule Post")
        self.geometry("500x600")
        self.resizable(False, False)

        self.text = text
        self.saved_threads_data = saved_threads_data
        self.result = None

        self._build_ui()

    def _build_ui(self):
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            main_frame,
            text="Select Target Thread:",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", pady=(0, 5))

        targets = ["Select a thread..."] + sorted(self.saved_threads_data.keys())
        self.var_thread = ctk.StringVar(value=targets[0])
        self.dropdown_thread = ctk.CTkOptionMenu(
            main_frame,
            variable=self.var_thread,
            values=targets,
            width=460,
        )
        self.dropdown_thread.pack(anchor="w", pady=(0, 20))

        ctk.CTkLabel(
            main_frame,
            text="Select Time:",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", pady=(0, 5))

        time_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        time_frame.pack(fill="x", pady=(0, 20))

        for name, hours in (
            ("In 1 Hour", 1),
            ("In 4 Hours", 4),
            ("In 12 Hours", 12),
            ("In 24 Hours", 24),
        ):
            ctk.CTkButton(
                time_frame,
                text=name,
                command=lambda h=hours: self._apply_preset(h),
                width=100,
            ).pack(side="left", padx=(0, 10))

        self.var_time = ctk.StringVar()
        self._apply_preset(1)
        self.entry_time = ctk.CTkEntry(main_frame, textvariable=self.var_time, width=460)
        self.entry_time.pack(anchor="w", pady=(0, 5))
        ctk.CTkLabel(
            main_frame,
            text="Format: YYYY-MM-DD HH:MM:SS (24-hour, local time)",
            text_color="gray",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 20))

        ctk.CTkLabel(
            main_frame,
            text="Post Preview:",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", pady=(0, 5))
        self.preview_box = ctk.CTkTextbox(main_frame, width=460, height=200)
        self.preview_box.pack(anchor="w", pady=(0, 20))
        self.preview_box.insert("1.0", self.text)
        self.preview_box.configure(state="disabled")

        action_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        action_frame.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            action_frame,
            text="Cancel",
            fg_color="transparent",
            border_width=1,
            command=self.destroy,
            width=100,
        ).pack(side="right")
        ctk.CTkButton(
            action_frame,
            text="Schedule",
            command=self._on_schedule,
            width=100,
        ).pack(side="right", padx=(0, 10))

    def _apply_preset(self, hours):
        scheduled_at = datetime.datetime.now() + datetime.timedelta(hours=hours)
        self.var_time.set(scheduled_at.strftime("%Y-%m-%d %H:%M:%S"))

    def _on_schedule(self):
        thread_name = self.var_thread.get()
        if thread_name == "Select a thread...":
            messagebox.showerror("Error", "Please select a target thread.")
            return

        time_str = self.var_time.get()
        try:
            scheduled_at = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("Error", "Invalid time format. Use YYYY-MM-DD HH:MM:SS")
            return

        if scheduled_at < datetime.datetime.now():
            messagebox.showerror("Error", "Scheduled time must be in the future.")
            return

        thread_id = self._selected_thread_id(thread_name)
        if not thread_id:
            messagebox.showerror("Error", "Selected thread is invalid or missing ID.")
            return

        self.result = {
            "thread_id": thread_id,
            "thread_name": thread_name,
            "message": self.text,
            "scheduled_time": scheduled_at.astimezone(datetime.timezone.utc).isoformat(),
        }
        self.destroy()

    def _selected_thread_id(self, thread_name):
        data = self.saved_threads_data.get(thread_name, {})
        if isinstance(data, dict):
            thread_id = extract_thread_id(str(data.get("thread_id") or ""))
            return thread_id or extract_thread_id(str(data.get("url") or ""))
        return extract_thread_id(str(data or ""))

    def get_result(self):
        return self.result


class ScheduledPostsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Scheduled Posts")
        self.geometry("800x600")

        from modules.sidecar import SidecarBridge

        self.api = None
        self.bridge = SidecarBridge.get()

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        toolbar = ctk.CTkFrame(main_frame, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(toolbar, text="Scheduled Posts", font=("Segoe UI", 20, "bold")).pack(
            side="left"
        )
        ctk.CTkButton(toolbar, text="Refresh", command=self.refresh, width=100).pack(
            side="right"
        )

        self.scroll_frame = SafeScrollableFrame(main_frame)
        self.scroll_frame.pack(fill="both", expand=True)

    def refresh(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        if not self.api:
            self.api = ViperGirlsAPI()
            self.api.bridge = self.bridge

        posts = self.api.list_scheduled_posts()
        if not posts:
            ctk.CTkLabel(
                self.scroll_frame,
                text="No scheduled posts.",
                text_color="gray",
            ).pack(pady=20)
            return

        for post in sorted(posts, key=lambda p: p.get("scheduled_time", ""), reverse=True):
            self._build_post_row(post)

    def _build_post_row(self, post):
        row = ctk.CTkFrame(self.scroll_frame)
        row.pack(fill="x", padx=5, pady=5)

        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        thread_name = post.get("thread_name", "Unknown Thread")
        status = post.get("status", "unknown")
        time_str = self._format_scheduled_time(post.get("scheduled_time"))

        ctk.CTkLabel(info_frame, text=thread_name, font=("Segoe UI", 14, "bold")).pack(
            anchor="w"
        )

        details = f"Scheduled: {time_str} | Status: {status.upper()}"
        if post.get("error"):
            details += f" | Error: {post.get('error')}"

        ctk.CTkLabel(info_frame, text=details, text_color=self._status_color(status)).pack(
            anchor="w"
        )

        if status == "pending":
            ctk.CTkButton(
                row,
                text="Cancel",
                fg_color="#FF3B30",
                hover_color="#D32F2F",
                width=80,
                command=lambda post_id=post.get("id"): self._cancel_post(post_id),
            ).pack(side="right", padx=10, pady=10)

    def _format_scheduled_time(self, value):
        raw_value = str(value or "")
        try:
            scheduled_at = datetime.datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            return scheduled_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw_value

    def _status_color(self, status):
        if status == "pending":
            return "#34C759"
        if status == "failed":
            return "#FF3B30"
        return "gray"

    def _cancel_post(self, post_id):
        if not post_id:
            messagebox.showerror("Error", "Scheduled post is missing an ID.")
            return
        if not messagebox.askyesno(
            "Confirm",
            "Are you sure you want to cancel this scheduled post?",
        ):
            return
        if self.api.cancel_scheduled_post(post_id):
            self.refresh()
        else:
            messagebox.showerror("Error", "Failed to cancel post.")
