# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import customtkinter as ctk
from tkinter import messagebox, simpledialog
import threading
import requests
import re
import urllib.parse
from modules.sidecar import SidecarBridge
from .widgets import MouseWheelComboBox
from . import api
from . import config


class GalleryManager(ctk.CTkToplevel):
    def __init__(self, parent, creds, callback=None):
        super().__init__(parent)
        self.creds = creds
        self.callback = callback
        self.bridge = SidecarBridge.get()

        self.title("Gallery Manager")
        self.geometry("600x700")  # Slightly taller for the new controls
        self.transient(parent)

        self.service_var = ctk.StringVar(value="imx.to")
        self.manual_cookies = {}
        self.current_page = 1  # Track current page

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
        self.manual_cookies = {"PHPSESSID": sess.strip(), "continue": "1"}
        messagebox.showinfo("Saved", "Cookie set! Refreshing list...")
        self._refresh_list()

    def _refresh_list(self):
        """Resets to Page 1 and clears the list"""
        self.current_page = 1

        # Clear UI
        for widget in self.scroll.winfo_children():
            widget.destroy()

        service = self.service_var.get()
        ctk.CTkLabel(self.scroll, text="Loading...").pack(pady=20)

        def _task():
            data = self._fetch_galleries(service, page=1)
            self.after(0, lambda: self._render_list(data, append=False))

        threading.Thread(target=_task, daemon=True).start()

    def _load_more_pages(self):
        """Fetches the next page and replaces current galleries"""
        self.current_page += 1

        # Clear UI
        for widget in self.scroll.winfo_children():
            widget.destroy()

        service = self.service_var.get()
        ctk.CTkLabel(self.scroll, text=f"Loading Page {self.current_page}...").pack(pady=20)

        def _task():
            data = self._fetch_galleries(service, page=self.current_page)
            self.after(0, lambda: self._render_list(data, append=False))

        threading.Thread(target=_task, daemon=True).start()

    def _render_list(self, data, append=False):
        # --- FIX: RACE CONDITION CHECK ---
        # If the window was closed while the thread was running, self.scroll might be gone.
        try:
            if not self.winfo_exists() or not self.scroll.winfo_exists():
                return
        except Exception:
            return
        # ---------------------------------

        if not append:
            for widget in self.scroll.winfo_children():
                widget.destroy()

        if not data:
            if not append:
                # Full refresh and no data
                if self.service_var.get() == "imx.to":
                    btn = ctk.CTkButton(
                        self.scroll,
                        text="Login Failed? Set Cookies Manually",
                        command=self._ask_cookies_dialog,
                        fg_color="orange",
                        text_color="black",
                    )
                    btn.pack(pady=20)
                    ctk.CTkLabel(
                        self.scroll, text="Login Failed.\nUse the button above if this persists."
                    ).pack(pady=5)
                else:
                    ctk.CTkLabel(self.scroll, text="No galleries found.").pack(pady=20)
            else:
                # Load more pressed but no more data
                ctk.CTkLabel(self.scroll, text="-- No more results --", text_color="gray").pack(
                    pady=10
                )
            return

        for item in data:
            f = ctk.CTkFrame(self.scroll, fg_color="transparent")
            f.pack(fill="x", pady=2)

            name = item.get("name") or item.get("gallery_name") or item.get("id")
            gid = item.get("id") or item.get("gallery_hash")

            ctk.CTkLabel(f, text=name, font=("", 12, "bold")).pack(side="left", padx=5)
            ctk.CTkLabel(f, text=f"({gid})", text_color="gray", font=("", 11)).pack(
                side="left", padx=5
            )

            if self.callback:
                ctk.CTkButton(
                    f,
                    text="Select",
                    width=60,
                    height=24,
                    command=lambda s=self.service_var.get(), g=gid: self._select(s, g),
                ).pack(side="right", padx=5)

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

    def _select(self, service, gid):
        if self.callback:
            self.callback(service, gid)
        self.destroy()

    def _create_gallery(self):
        name = self.ent_name.get().strip()
        if not name:
            messagebox.showwarning("Error", "Enter a gallery name")
            return

        service = self.service_var.get()

        def _task():
            new_id = self._perform_create(service, name)
            if new_id:
                self.after(0, lambda: messagebox.showinfo("Success", f"Gallery Created: {new_id}"))
                self.after(0, self._refresh_list)
                if self.callback:
                    self.after(0, lambda: self.callback(service, new_id))
            else:
                self.after(0, lambda: messagebox.showerror("Error", "Failed to create gallery."))

        threading.Thread(target=_task, daemon=True).start()

    # --- Logic ---

    def _get_creds_dict(self):
        return {
            "vipr_user": self.creds.get("vipr_user", ""),
            "vipr_pass": self.creds.get("vipr_pass", ""),
            "imagebam_user": self.creds.get("imagebam_user", ""),
            "imagebam_pass": self.creds.get("imagebam_pass", ""),
            "api_key": self.creds.get("imx_api", ""),
        }

    def _fetch_galleries(self, service, page=1):
        if service == "imx.to":
            return self._fetch_imx_galleries(page)

        # Other services don't support pagination in this bridge yet, return page 1 only
        if page > 1:
            return []

        payload = {"action": "list_galleries", "service": service, "creds": self._get_creds_dict()}
        resp = self.bridge.request_sync(payload, timeout=20)
        if resp.get("type") == "data" and resp.get("data"):
            return resp["data"]
        return []

    def _perform_create(self, service, name):
        if service == "imx.to":
            return self._create_imx_gallery(name)
        payload = {
            "action": "create_gallery",
            "service": service,
            "creds": self._get_creds_dict(),
            "config": {"gallery_name": name},
        }
        resp = self.bridge.request_sync(payload, timeout=20)
        if resp.get("status") == "success":
            return resp.get("data")
        if service == "pixhost.to":
            try:
                client = api.create_resilient_client()
                res = api.create_pixhost_gallery(name, client)
                client.close()
                if res:
                    return res.get("gallery_hash")
            except (requests.RequestException, AttributeError) as e:
                logger.error(f"Failed to create Pixhost gallery: {e}")
        return None

    # --- IMX IMPLEMENTATION ---

    def _create_imx_session(self):
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})

        if self.manual_cookies:
            for k, v in self.manual_cookies.items():
                session.cookies.set(k, v, domain="imx.to")
            return session

        user = self.creds.get("imx_user") or self.creds.get("vipr_user")
        pwd = self.creds.get("imx_pass") or self.creds.get("vipr_pass")
        if not user or not pwd:
            return None

        try:
            # Login
            login_url = "https://imx.to/login.php"
            session.get(login_url, timeout=10)  # Init cookies

            payload = {"usr_email": user, "pwd": pwd, "doLogin": "Login", "remember": "1"}
            session.post(login_url, data=payload, timeout=10)
            return session
        except requests.RequestException as e:
            logger.error(f"IMX login failed: {e}")
            return None

    def _fetch_imx_galleries(self, page=1):
        session = self._create_imx_session()
        if not session:
            return []

        try:
            # Append page parameter with 200 galleries per page
            url = f"https://imx.to/user/galleries?page={page}&limit=200"
            r = session.get(url, timeout=15)

            galleries = []
            seen = set()
            # FIX: Updated pattern to make <i> tags optional
            # Old pattern: r"href=['\"](?:https?://[^/'\"]+)?/g/(\w+)['\"][^>]*>\s*<i>([^<]+)</i>"
            pattern = (
                r"href=['\"](?:https?://[^/'\"]+)?/g/(\w+)['\"][^>]*>\s*(?:<i>)?([^<]+)(?:</i>)?"
            )
            for gid, gname in re.findall(pattern, r.text, re.IGNORECASE):
                if gid not in seen:
                    galleries.append({"id": gid, "name": gname.strip()})
                    seen.add(gid)
            return galleries
        except (requests.RequestException, AttributeError) as e:
            logger.error(f"Failed to fetch IMX galleries: {e}")
            return []

    def _create_imx_gallery(self, name):
        session = self._create_imx_session()
        if not session:
            return None
        try:
            url = "https://imx.to/user/gallery/add"
            # Correct fields from add.php source code
            data = {"gallery_name": name, "submit_new_gallery": "Add"}

            r = session.post(url, data=data, timeout=15)

            if "id=" in r.url:
                from urllib.parse import urlparse, parse_qs

                q = parse_qs(urlparse(r.url).query)
                if "id" in q:
                    return q["id"][0]

            return self._find_gid_in_list(session, name)
        except (requests.RequestException, KeyError, IndexError) as e:
            logger.error(f"Failed to create IMX gallery: {e}")
            return None

    def _find_gid_in_list(self, session, name):
        try:
            r = session.get("https://imx.to/user/galleries", timeout=10)
            # FIX: Updated pattern to make <i> tags optional
            pattern = r"href=['\"].*?/g/(\w+)['\"].*?>\s*(?:<i>)?(.*?)(?:</i>)?"
            for gid, gname in re.findall(pattern, r.text, re.IGNORECASE):
                if gname.strip() == name:
                    return gid
        except (requests.RequestException, AttributeError) as e:
            logger.debug(f"Could not find gallery '{name}' in list: {e}")
        return None
