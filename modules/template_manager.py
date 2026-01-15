# modules/template_manager.py
import re
import json
import os
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, colorchooser
import urllib.parse
import webbrowser
import tempfile
from loguru import logger

# Local imports
from . import config
from .widgets import MouseWheelComboBox


class TemplateManager:
    def __init__(self):
        # 1. Standard Defaults
        self.defaults = {
            "BBCode": "[center]\n[if gallery_link][url=#gallery_link#]Click here for Gallery[/url]\n\n[/if]#all_images#\n[/center]",
            "Markdown": "[if gallery_link][Click here for Gallery](#gallery_link#)\n\n[/if]#all_images#",
            "HTML": '[if gallery_link]<center><a href="#gallery_link#">Click here for Gallery</a></center><br><br>[/if]#all_images#',
        }

        self.presets = {
            "Basic List": "#all_images#",
            "Vipr Forum (Center)": "[center][url=#gallery_link#][b]📂 Open Full Gallery[/b][/url][/center]\n\n#all_images#",
            "Vipr Forum (Simple)": "[b]Gallery:[/b] [url=#gallery_link#]#gallery_name#[/url]\n\n#all_images#",
            "Reddit Markdown": "[📂 View Gallery](#gallery_link#)\n\n#all_images#",
            "HTML Page Wrapper": "<html>\n<body>\n<h3><a href='#gallery_link#'>View Gallery</a></h3>\n<hr>\n#all_images#\n</body>\n</html>",
            "Cover + Gallery ID": "[center][img]#cover_url#[/img]\n\n[b]Gallery ID:[/b] #gallery_id#\n[url=#gallery_link#]Click to View Gallery[/url][/center]\n\n#all_images#",
        }
        self.defaults.update(self.presets)

        # Standard format: Clickable Images (Links to Viewer Page)
        # UPDATED: Now correctly uses #thumb_url# for the image source
        self.image_formats = {
            "BBCode": "[url=#image_url#][img]#thumb_url#[/img][/url]",
            "Markdown": "[![Image](#thumb_url#)](#image_url#)",
            "HTML": '<a href="#image_url#"><img src="#thumb_url#"></a>',
        }

        # NEW: Full Size Image Formats (Links/Displays Direct Image)
        self.full_image_formats = {
            "BBCode": "[img]#image_url#[/img]",
            "Markdown": "![]( #image_url# )",
            "HTML": '<img src="#image_url#">',
        }

        self.templates = self.defaults.copy()
        self.filepath = "user_templates.json"
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    saved = json.load(f)
                    self.templates.update(saved)
            except Exception as e:
                logger.error(f"Error loading templates: {e}")

    def save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.templates, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving templates: {e}")

    def get_template(self, fmt):
        return self.templates.get(fmt, self.defaults.get(fmt, ""))

    def set_template(self, fmt, content):
        self.templates[fmt] = content
        self.save()

    def get_all_keys(self):
        keys = list(self.templates.keys())
        standards = ["BBCode", "Markdown", "HTML"]
        others = sorted([k for k in keys if k not in standards])
        return [s for s in standards if s in keys] + [o for o in others if o not in standards]

    def process_conditionals(self, template_content, data):
        max_iterations = 50
        iteration = 0
        while iteration < max_iterations:
            if_pattern = r"\[if\s+(\w+)(=([^\]]+))?\]((?:(?!\[if).)*?)\[/if\]"
            match = re.search(if_pattern, template_content, re.DOTALL)
            if not match:
                break

            placeholder_name = match.group(1)
            expected_value = match.group(3)
            conditional_block = match.group(4)

            actual_value = data.get(placeholder_name, "")
            else_pattern = r"^(.*?)\[else\](.*?)$"
            else_match = re.match(else_pattern, conditional_block, re.DOTALL)

            if else_match:
                true_content = else_match.group(1)
                false_content = else_match.group(2)
            else:
                true_content = conditional_block
                false_content = ""

            if expected_value is not None:
                condition_met = str(actual_value).strip() == expected_value.strip()
            else:
                condition_met = bool(str(actual_value).strip())

            replacement = true_content if condition_met else false_content
            template_content = template_content[: match.start()] + replacement + template_content[match.end() :]
            iteration += 1
        return template_content

    def apply(self, format_mode, data, images):
        template = self.get_template(format_mode)

        # 1. Prepare Image Data
        # Expecting img tuple: (viewer_url, thumb_url, direct_url[optional])
        filtered_images = []
        cover_thumb = data.get("cover_url", "")
        use_cover_exclusion = "#cover_url#" in template

        for img in images:
            viewer_url = img[0] if len(img) > 0 else ""
            thumb_url = img[1] if len(img) > 1 else viewer_url
            # If a direct URL is provided (3rd element), use it; otherwise fallback to viewer
            direct_url = img[2] if len(img) > 2 else viewer_url

            # Exclude if it matches cover
            if use_cover_exclusion and cover_thumb and thumb_url == cover_thumb:
                continue

            filtered_images.append((viewer_url, thumb_url, direct_url))

        # 2. Generate #all_images# (Direct Images -> Links to Viewer)
        img_fmt = self.image_formats.get(format_mode, self.image_formats["BBCode"])
        processed_images = []
        for v_url, t_url, d_url in filtered_images:
            item_str = img_fmt
            # Available placeholders:
            # #image_url# - Link target (Viewer Page URL)
            # #thumb_url# - Thumbnail image URL
            # #direct_url# - Direct image URL (full-size image)
            item_str = item_str.replace("#image_url#", str(v_url))
            item_str = item_str.replace("#thumb_url#", str(t_url))
            item_str = item_str.replace("#direct_url#", str(d_url))
            # Replace context placeholders (like #thumb_size#) in each image's BBCode
            for k, v in data.items():
                item_str = item_str.replace(f"#{k}#", str(v))
            processed_images.append(item_str)
        data["all_images"] = " ".join(processed_images)

        # 3. Generate #all_full_images# (Direct Images)
        full_fmt = self.full_image_formats.get(format_mode, self.full_image_formats["BBCode"])
        processed_full = []
        for v_url, t_url, d_url in filtered_images:
            item_str = full_fmt
            # In full image list, #image_url# implies the source image (Direct JPG)
            item_str = item_str.replace("#image_url#", str(d_url))
            item_str = item_str.replace("#thumb_url#", str(t_url))
            # Replace context placeholders in full images too
            for k, v in data.items():
                item_str = item_str.replace(f"#{k}#", str(v))
            processed_full.append(item_str)
        data["all_full_images"] = " ".join(processed_full)

        # 4. Process
        content = self.process_conditionals(template, data)
        for k, v in data.items():
            content = content.replace(f"#{k}#", str(v))

        return content


class TemplateEditor(ctk.CTkToplevel):
    def __init__(self, parent, template_mgr, current_mode="BBCode", data_callback=None, update_callback=None):
        super().__init__(parent)
        self.mgr = template_mgr
        self.data_callback = data_callback
        self.update_callback = update_callback
        self.initial_mode = current_mode
        self.title("Template Editor")
        self.geometry("800x700")
        self.transient(parent)
        self._init_ui()

    def _init_ui(self):
        main = ctk.CTkFrame(self)
        main.pack(fill="both", expand=True, padx=15, pady=15)
        top = ctk.CTkFrame(main, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(top, text="Edit Format:", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.fmt = ctk.StringVar(value=self.initial_mode)
        all_keys = self.mgr.get_all_keys()
        self.cb_fmt = MouseWheelComboBox(
            top, variable=self.fmt, values=all_keys, state="readonly", command=self.load_curr
        )
        self.cb_fmt.pack(side="left", padx=10)
        preset_frame = ctk.CTkFrame(main)
        preset_frame.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(preset_frame, text="Saved Templates:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=5)
        self.saved_tmpl_var = ctk.StringVar()
        self.cb_saved = MouseWheelComboBox(
            preset_frame, variable=self.saved_tmpl_var, values=all_keys, state="readonly"
        )
        self.cb_saved.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        ctk.CTkButton(preset_frame, text="Load", width=60, command=self.load_saved_template).pack(side="left", padx=5)
        toolbar = ctk.CTkFrame(main, height=35)
        toolbar.pack(fill="x", pady=(5, 0))
        styles = [("B", "Bold"), ("I", "Italic"), ("U", "Underline")]
        for text, mode in styles:
            ctk.CTkButton(toolbar, text=text, width=30, command=lambda m=mode: self.format_text(m)).pack(
                side="left", padx=2, pady=2
            )
        ctk.CTkButton(toolbar, text="Color", width=50, command=lambda: self.format_complex("Color")).pack(
            side="left", padx=2, pady=2
        )
        ctk.CTkFrame(toolbar, width=2, height=20, fg_color="gray").pack(side="left", padx=5)
        ctk.CTkLabel(toolbar, text="Size:", width=30).pack(side="left", padx=(5, 2))
        self.cb_size = MouseWheelComboBox(
            toolbar,
            width=60,
            values=["1", "2", "3", "4", "5", "6", "7"],
            command=lambda v: self.apply_from_combo("Size", v),
        )
        self.cb_size.pack(side="left", padx=2)
        self.cb_size.set("")
        ctk.CTkLabel(toolbar, text="Font:", width=30).pack(side="left", padx=(5, 2))
        self.cb_font = MouseWheelComboBox(
            toolbar,
            width=120,
            values=["Arial", "Courier New", "Times New Roman", "Verdana", "Segoe UI", "Helvetica"],
            command=lambda v: self.apply_from_combo("Font", v),
        )
        self.cb_font.pack(side="left", padx=2)
        self.cb_font.set("")
        var_bar = ctk.CTkFrame(main, fg_color="transparent")
        var_bar.pack(fill="x", pady=(5, 5))
        vars_to_add = [
            ("Images", "#all_images#"),
            ("Full Imgs", "#all_full_images#"),
            ("Gal Link", "#gallery_link#"),
            ("Gal Name", "#gallery_name#"),
            ("Gal ID", "#gallery_id#"),
            ("Cover", "[img]#cover_url#[/img]"),
        ]
        for t, v in vars_to_add:
            ctk.CTkButton(var_bar, text=t, width=70, height=24, command=lambda v=v: self.ins(v)).pack(
                side="left", padx=2
            )
        self.txt = ctk.CTkTextbox(main, wrap="word", font=("Consolas", 12))
        self.txt.pack(fill="both", expand=True, pady=(0, 15))
        btn = ctk.CTkFrame(main, fg_color="transparent")
        btn.pack(fill="x")
        ctk.CTkButton(btn, text="Preview in Browser", command=self.generate_preview).pack(side="left")
        ctk.CTkButton(btn, text="Save As New...", command=self.save_as_new, fg_color="green").pack(
            side="right", padx=(5, 0)
        )
        ctk.CTkButton(btn, text="Save Current", command=self.save).pack(side="right")
        self.load_curr()

    def get_tags(self, mode, value=None):
        fmt = self.fmt.get()
        if mode == "Bold":
            return ("[b]", "[/b]") if fmt == "BBCode" else ("**", "**") if fmt == "Markdown" else ("<b>", "</b>")
        elif mode == "Italic":
            return ("[i]", "[/i]") if fmt == "BBCode" else ("*", "*") if fmt == "Markdown" else ("<i>", "</i>")
        elif mode == "Underline":
            return ("[u]", "[/u]") if fmt == "BBCode" else ("<u>", "</u>")
        elif mode == "Color":
            return (f"[color={value}]", "[/color]") if fmt == "BBCode" else (f'<span style="color:{value}">', "</span>")
        elif mode == "Size":
            return (
                (f"[size={value}]", "[/size]")
                if fmt == "BBCode"
                else (f'<span style="font-size:{value}px">', "</span>")
            )
        elif mode == "Font":
            return (
                (f"[font={value}]", "[/font]")
                if fmt == "BBCode"
                else (f'<span style="font-family:{value}">', "</span>")
            )
        return ("", "")

    def format_text(self, mode):
        try:
            start = self.txt.index("sel.first")
            end = self.txt.index("sel.last")
            s_tag, e_tag = self.get_tags(mode)
            selected = self.txt.get(start, end)
            self.txt.delete(start, end)
            self.txt.insert(start, f"{s_tag}{selected}{e_tag}")
        except tk.TclError:
            self.txt.insert("insert", "".join(self.get_tags(mode)))

    def format_complex(self, mode):
        val = None
        if mode == "Color":
            c = colorchooser.askcolor(title="Select Color")
            if c and c[1]:
                val = c[1]
        if val:
            self.apply_from_combo(mode, val)

    def apply_from_combo(self, mode, value):
        if not value:
            return
        try:
            start = self.txt.index("sel.first")
            end = self.txt.index("sel.last")
            s_tag, e_tag = self.get_tags(mode, value)
            selected = self.txt.get(start, end)
            self.txt.delete(start, end)
            self.txt.insert(start, f"{s_tag}{selected}{e_tag}")
        except tk.TclError:
            self.txt.insert("insert", "".join(self.get_tags(mode, value)))

    def ins(self, v):
        self.txt.insert("insert", v)
        self.txt.focus()

    def load_curr(self, _=None):
        self.txt.delete("0.0", "end")
        self.txt.insert("0.0", self.mgr.get_template(self.fmt.get()))

    def load_saved_template(self):
        sel = self.saved_tmpl_var.get()
        if not sel:
            return
        self.txt.delete("0.0", "end")
        self.txt.insert("0.0", self.mgr.get_template(sel))
        if sel not in self.cb_fmt._values:
            self.cb_fmt.configure(values=self.cb_fmt._values + [sel])
        self.cb_fmt.set(sel)
        self.fmt.set(sel)

    def save(self):
        name = self.fmt.get()
        self.mgr.set_template(name, self.txt.get("0.0", "end").strip())
        messagebox.showinfo("Saved", f"Template '{name}' updated.")
        if self.update_callback:
            self.update_callback(name)

    def save_as_new(self):
        dialog = ctk.CTkInputDialog(text="Enter name:", title="Save As New")
        new_name = dialog.get_input()
        if new_name:
            self.mgr.set_template(new_name.strip(), self.txt.get("0.0", "end").strip())
            keys = self.mgr.get_all_keys()
            self.cb_saved.configure(values=keys)
            self.cb_fmt.configure(values=keys)
            self.cb_fmt.set(new_name)
            self.cb_saved.set(new_name)
            self.fmt.set(new_name)
            messagebox.showinfo("Success", f"Created: {new_name}")
            if self.update_callback:
                self.update_callback(new_name)

    def generate_preview(self):
        if not self.data_callback:
            return
        files, title, size = self.data_callback()
        if not files:
            return messagebox.showwarning("Preview", "Add files first.")
        if not size or not str(size).isdigit():
            size = "200"
        # Mocking 3-tuple (Viewer, Thumb, Direct) for preview
        mock = []
        for f in files:
            path_url = f"file:///{urllib.parse.quote(f.replace(os.sep, '/'))}"
            mock.append((path_url, path_url, path_url))  # Viewer=Path, Thumb=Path, Direct=Path

        curr_fmt = self.fmt.get()
        orig = self.mgr.get_template(curr_fmt)
        self.mgr.set_template(curr_fmt, self.txt.get("0.0", "end").strip())
        ctx = {
            "gallery_link": "http://localhost/preview",
            "gallery_name": title,
            "gallery_id": "PREV_123",
            "cover_url": mock[0][1] if mock else "",
        }
        try:
            raw = self.mgr.apply(curr_fmt, ctx, mock)
        finally:
            self.mgr.set_template(curr_fmt, orig)

        html = raw if curr_fmt == "HTML" else raw.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        if curr_fmt != "HTML":
            html = re.sub(r"\[url=(.*?)\]", r'<a href="\1">', html)
            html = html.replace("[/url]", "</a>")
            html = re.sub(r"\[img\](.*?)\[/img\]", f'<img src="\\1" style="max-width:{size}px">', html)

        final_html = f"<html><body style='padding:20px; font-family:sans-serif'>{html}</body></html>"
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
                f.write(final_html)
                path = f.name
            webbrowser.open("file://" + path)
        except Exception as e:
            messagebox.showerror("Error", str(e))