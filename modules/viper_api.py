# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import json
import os
import customtkinter as ctk
from tkinter import messagebox
from loguru import logger
from modules.sidecar import SidecarBridge

# Store threads file in user's home directory
_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".conniesuploader")
THREADS_FILE = os.path.join(_USER_DATA_DIR, "saved_threads.json")


def load_saved_threads():
    """Helper to load threads from JSON for external use."""
    if os.path.exists(THREADS_FILE):
        try:
            with open(THREADS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


class ViperGirlsAPI:
    def __init__(self):
        self.bridge = SidecarBridge.get()
        self.is_logged_in = False

    def login(self, username, password):
        logger.info(f"ViperAPI: Logging in as {username}...")
        payload = {
            "action": "viper_login",
            "service": "vipergirls",
            "creds": {"vg_user": username, "vg_pass": password},
        }

        resp = self.bridge.request_sync(payload, timeout=30)

        if resp.get("status") == "success":
            self.is_logged_in = True
            logger.info("ViperAPI: Login Successful")
            return True
        else:
            logger.error(f"ViperAPI: Login Failed: {resp.get('msg')}")
            return False

    def post_reply(self, thread_id, message):
        logger.info(f"ViperAPI: Posting to thread {thread_id}...")
        payload = {
            "action": "viper_post",
            "service": "vipergirls",
            "config": {"thread_id": str(thread_id), "message": message},
        }

        resp = self.bridge.request_sync(payload, timeout=60)

        if resp.get("status") == "success":
            logger.info("ViperAPI: Post Successful")
            return True
        else:
            logger.error(f"ViperAPI: Post Failed: {resp.get('msg')}")
            return False

    def close(self):
        pass


class ViperToolsWindow(ctk.CTkToplevel):
    def __init__(self, parent, creds=None, callback=None):
        super().__init__(parent)
        self.creds = creds
        self.callback = callback
        self.title("ViperGirls Tools")
        self.geometry("600x500")

        # --- FIX: Keep window on top ---
        self.transient(parent)  # Tells the OS this window belongs to 'parent'
        self.lift()  # Brings it to the front immediately
        self.focus_force()  # Grabs input focus
        # -------------------------------

        self.saved_threads = load_saved_threads()

        # --- UI Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left: List
        self.scroll = ctk.CTkScrollableFrame(self, label_text="Saved Threads")
        self.scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Right: Add New
        self.controls = ctk.CTkFrame(self)
        self.controls.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)

        ctk.CTkLabel(self.controls, text="Add New Thread").pack(pady=10)

        self.ent_name = ctk.CTkEntry(self.controls, placeholder_text="Name (e.g. 'My Thread')")
        self.ent_name.pack(pady=5, padx=10)

        self.ent_url = ctk.CTkEntry(self.controls, placeholder_text="URL or Thread ID")
        self.ent_url.pack(pady=5, padx=10)

        ctk.CTkButton(self.controls, text="Save Thread", command=self.add_thread).pack(
            pady=10, padx=10
        )
        ctk.CTkLabel(self.controls, text="-----------------").pack(pady=5)
        ctk.CTkButton(self.controls, text="Refresh List", command=self.refresh_list).pack(pady=5)

        self.refresh_list()

    def refresh_list(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        self.saved_threads = load_saved_threads()

        for name, data in self.saved_threads.items():
            row = ctk.CTkFrame(self.scroll)
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=name, font=("", 12, "bold")).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=data.get("url", "???"), text_color="gray").pack(
                side="left", padx=5
            )

            ctk.CTkButton(
                row,
                text="X",
                width=30,
                fg_color="red",
                command=lambda n=name: self.delete_thread(n),
            ).pack(side="right", padx=5)

    def add_thread(self):
        name = self.ent_name.get().strip()
        url = self.ent_url.get().strip()

        if not name or not url:
            messagebox.showerror("Error", "Name and URL required")
            return

        self.saved_threads[name] = {"url": url}
        self.save_to_file()
        self.refresh_list()
        self.ent_name.delete(0, "end")
        self.ent_url.delete(0, "end")

        if self.callback:
            self.callback()

    def delete_thread(self, name):
        if name in self.saved_threads:
            del self.saved_threads[name]
            self.save_to_file()
            self.refresh_list()
            if self.callback:
                self.callback()

    def save_to_file(self):
        try:
            # Ensure user data directory exists
            os.makedirs(_USER_DATA_DIR, exist_ok=True)
            with open(THREADS_FILE, "w") as f:
                json.dump(self.saved_threads, f, indent=4)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")
