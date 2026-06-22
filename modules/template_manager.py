# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Template management and rendering utilities."""

import json
import os
import re
import shutil
import tempfile
import urllib.parse
import webbrowser
import html

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
import tkinter as tk
import pyperclip
from loguru import logger
from tkinter import colorchooser, filedialog, messagebox

from .widgets import MouseWheelComboBox


_USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".conniesuploader")
DEFAULT_TEMPLATE_FILE = os.path.join(_USER_DATA_DIR, "templates.json")
LEGACY_TEMPLATE_FILE = os.path.abspath("user_templates.json")
TEMPLATE_EXPORT_VERSION = 1


class TemplateValidationError(ValueError):
    """Raised when a template is unsafe or incomplete."""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


class TemplateManager:
    TEMPLATE_TAG_PATTERN = re.compile(
        r"\[(?P<tag>else|/if|/for|if(?:\s+[^\]]*)?|for\s+(?:image|cover)(?:\s+[^\]]*)?)\]",
        re.IGNORECASE,
    )
    CONDITIONAL_START_PATTERN = re.compile(
        r"^if(?:\s+(.+))?$",
        re.IGNORECASE,
    )
    CONDITIONAL_EXPRESSION_PATTERN = re.compile(
        r"^#?([A-Za-z_][A-Za-z0-9_]*)#?(?:\s*=\s*(.+))?$"
    )
    LOOP_START_PATTERN = re.compile(r"^for\s+(image|cover)(?:\s+(.+))?$", re.IGNORECASE)
    LOOP_SEPARATOR_PATTERN = re.compile(
        r"(?:separator|sep)\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)",
        re.IGNORECASE,
    )
    HASH_PLACEHOLDER_PATTERN = re.compile(r"#([A-Za-z_][A-Za-z0-9_]*)#")
    HTML_TAG_PATTERN = re.compile(
        r"<\s*/?\s*(?:a|b|body|br|center|div|em|font|h[1-6]|html|i|img|p|span|strong|table|td|tr|u)\b[^>]*>",
        re.IGNORECASE,
    )
    ALLOWED_PLACEHOLDERS = {
        "all_images",
        "all_full_images",
        "batch_name",
        "cover_count",
        "cover_image",
        "cover_images",
        "cover_url",
        "direct_url",
        "gallery_id",
        "gallery_link",
        "gallery_name",
        "image_count",
        "image_url",
        "service",
        "thread_id",
        "thread_name",
        "thumb_size",
        "thumb_url",
        "upload_date",
    }
    IMAGE_OUTPUT_MARKERS = (
        "#all_images#",
        "#all_full_images#",
        "#cover_image#",
        "#cover_images#",
        "#cover_url#",
        "#image_url#",
        "#thumb_url#",
        "#direct_url#",
        "{viewer}",
        "{thumb}",
        "{direct}",
    )
    CATEGORY_ALL = "All"
    CUSTOM_CATEGORY = "Custom"
    BUILTIN_TEMPLATE_CATEGORY_ORDER = [
        "BBCode",
        "Markdown",
        "HTML",
        "Forum",
        "ViperGirls",
        CUSTOM_CATEGORY,
    ]
    BUILTIN_TEMPLATE_CATEGORIES = {
        "BBCode": "BBCode",
        "Basic List": "BBCode",
        "Cover + Gallery ID": "BBCode",
        "Markdown": "Markdown",
        "Reddit Markdown": "Markdown",
        "HTML": "HTML",
        "HTML Page Wrapper": "HTML",
        "Vipr Forum (Center)": "Forum",
        "Vipr Forum (Simple)": "Forum",
        "ViperGirls Gallery Post": "ViperGirls",
        "ViperGirls Compact Grid": "ViperGirls",
        "ViperGirls Full Image Post": "ViperGirls",
    }
    OUTPUT_FORMAT_BY_CATEGORY = {
        "BBCode": "BBCode",
        "Forum": "BBCode",
        "ViperGirls": "BBCode",
        "Markdown": "Markdown",
        "HTML": "HTML",
        CUSTOM_CATEGORY: "BBCode",
    }

    def __init__(self, filepath: Optional[str] = None) -> None:
        self.defaults = {
            "BBCode": "[center]\n[if gallery_link][url=#gallery_link#]Click here for Gallery[/url]\n\n[/if]#all_images#\n[/center]",
            "Markdown": "[if gallery_link][Click here for Gallery](#gallery_link#)\n\n[/if]#all_images#",
            "HTML": '[if gallery_link]<center><a href="#gallery_link#">Click here for Gallery</a></center><br><br>[/if]#all_images#',
            "Basic List": "#all_images#",
            "Vipr Forum (Center)": "[center][url=#gallery_link#][b]📂 Open Full Gallery[/b][/url][/center]\n\n#all_images#",
            "Vipr Forum (Simple)": "[b]Gallery:[/b] [url=#gallery_link#]#gallery_name#[/url]\n\n#all_images#",
            "Reddit Markdown": "[📂 View Gallery](#gallery_link#)\n\n#all_images#",
            "HTML Page Wrapper": "<html>\n<body>\n<h3><a href='#gallery_link#'>View Gallery</a></h3>\n<hr>\n#all_images#\n</body>\n</html>",
            "Cover + Gallery ID": "[center]#cover_image#\n\n[b]Gallery ID:[/b] #gallery_id#\n[url=#gallery_link#]Click to View Gallery[/url][/center]\n\n#all_images#",
            "ViperGirls Gallery Post": "[center][b]#batch_name#[/b]\n[if gallery_link][url=#gallery_link#]Open Gallery[/url]\n[/if][if thread_name][size=1]Target: #thread_name# (thread #thread_id#)[/size]\n[/if]\n#cover_images#\n\n#all_images#[/center]",
            "ViperGirls Compact Grid": "[center][for image separator=space][url=#image_url#][img]#thumb_url#[/img][/url][/for][/center]",
            "ViperGirls Full Image Post": "[center][b]#batch_name#[/b]\n\n[for image separator=blankline][img]#direct_url#[/img][/for]\n\n[if gallery_link][url=#gallery_link#]Gallery[/url][/if][/center]",
        }

        self.image_formats = {
            "BBCode": "[url=#image_url#][img]#thumb_url#[/img][/url]",
            "Markdown": "[![Image](#thumb_url#)](#image_url#)",
            "HTML": '<a href="#image_url#"><img src="#thumb_url#"></a>',
        }
        self.full_image_formats = {
            "BBCode": "[img]#image_url#[/img]",
            "Markdown": "![]( #image_url# )",
            "HTML": '<img src="#image_url#">',
        }

        self.templates = self.defaults.copy()
        self.uses_default_path = filepath is None
        self.filepath = filepath or DEFAULT_TEMPLATE_FILE
        if self.uses_default_path:
            self._migrate_legacy_templates()
        self.recovery_issue: Optional[Dict[str, Any]] = None
        self.load()
        self.save(validate=False)

    def _migrate_legacy_templates(self) -> None:
        if os.path.exists(self.filepath) or not os.path.exists(LEGACY_TEMPLATE_FILE):
            return

        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
            shutil.copy2(LEGACY_TEMPLATE_FILE, self.filepath)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{LEGACY_TEMPLATE_FILE}.migrated-{stamp}.bak"
            os.replace(LEGACY_TEMPLATE_FILE, backup_path)
            logger.info(f"Migrated templates to {self.filepath}; legacy file preserved at {backup_path}")
        except OSError as exc:
            logger.error(f"Could not migrate legacy templates: {exc}")

    def load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if not isinstance(saved, dict):
                    raise ValueError("Template file must contain a JSON object.")
                self.templates.update(saved)
                self.recovery_issue = None
            except Exception as e:
                backup_path = self._backup_unreadable_file()
                self.recovery_issue = {
                    "filepath": os.path.abspath(self.filepath),
                    "backup_path": backup_path,
                    "error": str(e),
                    "message": (
                        "Saved templates could not be loaded. Defaults were restored "
                        "and the broken file was preserved."
                    ),
                }
                logger.error(f"Error loading templates: {e}")

    def save(self, validate: bool = True) -> None:
        if validate:
            self.validate_all_templates(raise_on_error=True)

        try:
            folder = os.path.dirname(os.path.abspath(self.filepath))
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp_path = f"{self.filepath}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.templates, f, indent=4)
                f.write("\n")
            os.replace(tmp_path, self.filepath)
        except OSError as e:
            logger.error(f"Error saving templates: {e}")
            raise

    def _backup_unreadable_file(self) -> Optional[str]:
        try:
            folder = os.path.dirname(os.path.abspath(self.filepath))
            base_name = os.path.basename(self.filepath)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(folder, f"{base_name}.broken-{stamp}.bak")
            shutil.copy2(self.filepath, backup_path)
            return backup_path
        except Exception as e:
            logger.error(f"Could not preserve broken template file: {e}")
            return None

    def get_recovery_issue(self) -> Optional[Dict[str, Any]]:
        if not self.recovery_issue:
            return None
        return dict(self.recovery_issue)

    def restore_defaults(self) -> None:
        self.templates = self.defaults.copy()
        self.recovery_issue = None
        self.save()

    def get_template(self, fmt: str) -> str:
        return self.templates.get(fmt, self.defaults.get(fmt, ""))

    def set_template(self, fmt: str, content: str, validate: bool = True) -> None:
        clean_name = str(fmt or "").strip()
        if not clean_name:
            raise TemplateValidationError(["Template name is required."])
        if validate:
            self.validate_template(content, raise_on_error=True, template_name=clean_name)
        self.templates[clean_name] = content
        self.save(validate=False)

    def add_template(self, name: str, content: str) -> None:
        self.set_template(name, content)

    def delete_template(self, name: str) -> None:
        if name in self.templates:
            del self.templates[name]
            self.save(validate=False)

    def duplicate_template(self, source_name: str, new_name: str) -> None:
        if source_name not in self.templates:
            raise KeyError(source_name)
        self.set_template(new_name, self.templates[source_name])

    def rename_template(self, old_name: str, new_name: str, content: Optional[str] = None) -> None:
        if old_name not in self.templates:
            raise KeyError(old_name)
        clean_name = str(new_name or "").strip()
        if not clean_name:
            raise TemplateValidationError(["Template name is required."])
        template_content = self.templates[old_name] if content is None else content
        self.validate_template(template_content, raise_on_error=True, template_name=clean_name)
        updated = dict(self.templates)
        if clean_name != old_name:
            updated.pop(old_name, None)
        updated[clean_name] = template_content
        self.templates = updated
        self.save(validate=False)

    def get_all_templates(self) -> Dict[str, str]:
        return dict(self.templates)

    def get_template_category(self, name: str) -> str:
        return self.BUILTIN_TEMPLATE_CATEGORIES.get(name, self.CUSTOM_CATEGORY)

    def resolve_output_format(self, name: str) -> str:
        category = self.get_template_category(name)
        return self.OUTPUT_FORMAT_BY_CATEGORY.get(category, "BBCode")

    def template_warnings(self, name: str, content: str) -> List[str]:
        warnings: List[str] = []
        category = self.get_template_category(name)
        if self.resolve_output_format(name) == "BBCode" and category in {"BBCode", "Forum", "ViperGirls"}:
            if self.HTML_TAG_PATTERN.search(str(content or "")):
                warnings.append(
                    "This template is treated as BBCode, but it contains HTML tags. "
                    "ViperGirls/forum posts should use BBCode tags such as [b], [url], and [img]."
                )
        return warnings

    def get_category_names(self, include_all: bool = True) -> List[str]:
        present = {
            self.get_template_category(name)
            for name in self.templates
        }
        ordered = [
            category
            for category in self.BUILTIN_TEMPLATE_CATEGORY_ORDER
            if category in present
        ]
        remaining = sorted(present.difference(ordered))
        categories = ordered + remaining
        return ([self.CATEGORY_ALL] + categories) if include_all else categories

    def get_all_keys(self, category: Optional[str] = None) -> List[str]:
        keys = list(self.templates.keys())
        standards = ["BBCode", "Markdown", "HTML"]
        builtins = [name for name in self.defaults if name in keys and name not in standards]
        custom = sorted(
            [
                name
                for name in keys
                if name not in standards and name not in self.defaults
            ]
        )
        ordered = [s for s in standards if s in keys] + builtins + custom
        if category and category != self.CATEGORY_ALL:
            ordered = [
                name
                for name in ordered
                if self.get_template_category(name) == category
            ]
        return ordered

    def filter_template_names(
        self,
        query: str,
        category: Optional[str] = None,
    ) -> List[str]:
        needle = str(query or "").strip().lower()
        keys = self.get_all_keys(category)
        if not needle:
            return keys
        return [
            name
            for name in keys
            if needle in name.lower()
            or needle in str(self.templates.get(name, "")).lower()
            or needle in self.get_template_category(name).lower()
        ]

    def export_templates_file(self, filepath: str, names: Optional[List[str]] = None) -> int:
        selected_names = names if names is not None else self.get_all_keys()
        templates = {
            name: self.templates[name]
            for name in selected_names
            if name in self.templates
        }
        export_data = {
            "version": TEMPLATE_EXPORT_VERSION,
            "exported_at": datetime.now().replace(microsecond=0).isoformat(),
            "templates": templates,
        }
        folder = os.path.dirname(os.path.abspath(filepath))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=4)
            f.write("\n")
        return len(templates)

    def import_templates_file(
        self,
        filepath: str,
        overwrite: bool = True,
    ) -> Tuple[int, int, List[str]]:
        with open(filepath, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        if isinstance(raw_data, dict) and isinstance(raw_data.get("templates"), dict):
            raw_templates = raw_data["templates"]
        elif isinstance(raw_data, dict):
            raw_templates = raw_data
        else:
            raise TemplateValidationError(["Import file must contain a template object."])

        imported = 0
        skipped = 0
        errors = []
        updated = dict(self.templates)
        for raw_name, raw_content in raw_templates.items():
            name = str(raw_name or "").strip()
            content = str(raw_content or "")
            if not name:
                skipped += 1
                errors.append("Skipped a template with no name.")
                continue
            if name in updated and not overwrite:
                skipped += 1
                continue

            template_errors = self.validate_template(content, template_name=name)
            if template_errors:
                skipped += 1
                errors.extend(f"{name}: {error}" for error in template_errors)
                continue

            updated[name] = content
            imported += 1

        self.templates = updated
        self.save(validate=False)
        return imported, skipped, errors

    def validate_all_templates(self, raise_on_error: bool = False) -> Dict[str, List[str]]:
        errors = {
            name: template_errors
            for name, content in self.templates.items()
            for template_errors in [self.validate_template(content, template_name=name)]
            if template_errors
        }
        if errors and raise_on_error:
            flat_errors = [
                f"{name}: {error}"
                for name, template_errors in errors.items()
                for error in template_errors
            ]
            raise TemplateValidationError(flat_errors)
        return errors

    def validate_template(
        self,
        content: str,
        raise_on_error: bool = False,
        template_name: Optional[str] = None,
    ) -> List[str]:
        template = str(content or "")
        errors = []

        if not template.strip():
            errors.append("Template cannot be empty.")

        unknown_names = {
            name
            for name in self.HASH_PLACEHOLDER_PATTERN.findall(template)
            if name not in self.ALLOWED_PLACEHOLDERS
        }
        structure_errors, conditional_names = self._validate_template_structure(template)
        unknown = sorted(
            unknown_names.union(
                name for name in conditional_names if name not in self.ALLOWED_PLACEHOLDERS
            )
        )
        if unknown:
            errors.append("Unknown placeholder(s): " + ", ".join(f"#{name}#" for name in unknown))
        errors.extend(structure_errors)

        if not any(marker in template for marker in self.IMAGE_OUTPUT_MARKERS):
            errors.append(
                "Template needs an image output placeholder such as #all_images#, "
                "#all_full_images#, #cover_images#, #cover_image#, or #cover_url#."
            )

        if errors and raise_on_error:
            raise TemplateValidationError(errors)
        return errors

    def _validate_template_structure(self, template: str) -> Tuple[List[str], List[str]]:
        errors: List[str] = []
        conditional_names: List[str] = []
        stack: List[Dict[str, Any]] = []

        for match in self.TEMPLATE_TAG_PATTERN.finditer(template):
            raw_tag = match.group("tag").strip()
            kind = self._template_tag_kind(raw_tag)

            if kind == "if_start":
                name, _expected, valid = self._parse_condition_tag(raw_tag)
                if valid and name:
                    conditional_names.append(name)
                else:
                    errors.append(f"Invalid conditional tag: {match.group(0)}")
                stack.append({"kind": "if", "tag": match.group(0), "has_else": False})
                continue

            if kind == "else":
                if not stack or stack[-1]["kind"] != "if":
                    errors.append("Template has an [else] without a matching [if].")
                elif stack[-1]["has_else"]:
                    errors.append("Template has more than one [else] in an [if] block.")
                else:
                    stack[-1]["has_else"] = True
                continue

            if kind == "if_end":
                if not stack or stack[-1]["kind"] != "if":
                    errors.append("Template has a closing [/if] without a matching [if].")
                else:
                    stack.pop()
                continue

            if kind in {"for_image_start", "for_cover_start"}:
                loop_name = "image" if kind == "for_image_start" else "cover"
                stack.append({"kind": "for", "tag": match.group(0), "loop_name": loop_name})
                continue

            if kind == "for_end":
                if not stack or stack[-1]["kind"] != "for":
                    errors.append("Template has a closing [/for] without a matching [for image] or [for cover].")
                else:
                    stack.pop()

        for entry in reversed(stack):
            if entry["kind"] == "if":
                errors.append("Template has an unclosed [if] block.")
            elif entry["kind"] == "for":
                loop_name = entry.get("loop_name", "image")
                errors.append(f"Template has an unclosed [for {loop_name}] block.")

        return errors, conditional_names

    @staticmethod
    def _clean_expected_value(value: str) -> str:
        expected = str(value or "").strip()
        if len(expected) >= 2 and expected[0] == expected[-1] and expected[0] in {"'", '"'}:
            return expected[1:-1].strip()
        return expected

    @staticmethod
    def _decode_separator(value: str) -> str:
        return (
            str(value)
            .replace("\\r", "\r")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
        )

    @staticmethod
    def _clean_separator_value(value: str) -> str:
        raw_value = str(value or "").strip()
        if (
            len(raw_value) >= 2
            and raw_value[0] == raw_value[-1]
            and raw_value[0] in {"'", '"'}
        ):
            return raw_value[1:-1]
        return raw_value

    def _template_tag_kind(self, raw_tag: str) -> str:
        tag = raw_tag.strip()
        lower = tag.lower()
        if lower == "else":
            return "else"
        if lower == "/if":
            return "if_end"
        if lower == "/for":
            return "for_end"
        if self.CONDITIONAL_START_PATTERN.fullmatch(tag):
            return "if_start"
        loop_match = self.LOOP_START_PATTERN.fullmatch(tag)
        if loop_match:
            loop_name = str(loop_match.group(1) or "").lower()
            return "for_cover_start" if loop_name == "cover" else "for_image_start"
        return "text"

    def _parse_condition_tag(self, raw_tag: str) -> Tuple[str, Optional[str], bool]:
        match = self.CONDITIONAL_START_PATTERN.fullmatch(raw_tag.strip())
        if not match:
            return "", None, False

        expression = str(match.group(1) or "").strip()
        if not expression:
            return "", None, False

        expr_match = self.CONDITIONAL_EXPRESSION_PATTERN.fullmatch(expression)
        if not expr_match:
            return "", None, False

        expected = expr_match.group(2)
        return (
            expr_match.group(1),
            self._clean_expected_value(expected) if expected is not None else None,
            True,
        )

    def _condition_matches(self, name: str, expected: Optional[str], data: Dict[str, Any]) -> bool:
        actual_value = data.get(name, "")
        if expected is not None:
            return str(actual_value).strip() == expected
        return bool(str(actual_value).strip())

    def _loop_separator_from_tag(self, raw_tag: str) -> str:
        match = self.LOOP_START_PATTERN.fullmatch(raw_tag.strip())
        attrs = str(match.group(2) or "") if match else ""
        sep_match = self.LOOP_SEPARATOR_PATTERN.search(attrs)
        value = self._clean_separator_value(sep_match.group(1)) if sep_match else "newline"
        normalized = value.strip().lower().replace("_", "").replace("-", "").replace(" ", "")
        separators = {
            "space": " ",
            "newline": "\n",
            "line": "\n",
            "blankline": "\n\n",
            "blank": "\n\n",
            "none": "",
            "empty": "",
            "comma": ", ",
        }
        return separators.get(normalized, self._decode_separator(value))

    @staticmethod
    def _image_values(image: Tuple[str, str, str]) -> Tuple[str, str, str]:
        viewer_url = image[0] if len(image) > 0 else ""
        thumb_url = image[1] if len(image) > 1 else viewer_url
        direct_url = image[2] if len(image) > 2 else viewer_url
        return str(viewer_url), str(thumb_url), str(direct_url)

    def _image_context(
        self,
        data: Dict[str, Any],
        image: Tuple[str, str, str],
    ) -> Dict[str, Any]:
        viewer_url, thumb_url, direct_url = self._image_values(image)
        image_data = dict(data)
        image_data["image_url"] = viewer_url
        image_data["thumb_url"] = thumb_url
        image_data["direct_url"] = direct_url
        return image_data

    def _parse_template_nodes(
        self,
        template_content: str,
    ) -> List[Tuple[Any, ...]]:
        nodes, _position, _stop = self._parse_nodes(template_content, 0, set())
        return nodes

    def _parse_nodes(
        self,
        template_content: str,
        start_position: int,
        stop_tags: set,
    ) -> Tuple[List[Tuple[Any, ...]], int, str]:
        nodes: List[Tuple[Any, ...]] = []
        position = start_position

        for match in self.TEMPLATE_TAG_PATTERN.finditer(template_content, start_position):
            if match.start() < position:
                continue

            raw_tag = match.group("tag").strip()
            kind = self._template_tag_kind(raw_tag)
            if kind in stop_tags:
                if match.start() > position:
                    nodes.append(("text", template_content[position:match.start()]))
                return nodes, match.end(), kind

            if match.start() > position:
                nodes.append(("text", template_content[position:match.start()]))

            if kind == "if_start":
                name, expected, valid = self._parse_condition_tag(raw_tag)
                true_nodes, next_position, stop_kind = self._parse_nodes(
                    template_content,
                    match.end(),
                    {"else", "if_end"},
                )
                false_nodes: List[Tuple[Any, ...]] = []
                if stop_kind == "else":
                    false_nodes, next_position, _stop_kind = self._parse_nodes(
                        template_content,
                        next_position,
                        {"if_end"},
                    )
                nodes.append(
                    (
                        "if",
                        name if valid else "",
                        expected,
                        true_nodes,
                        false_nodes,
                    )
                )
                position = next_position
                continue

            if kind in {"for_image_start", "for_cover_start"}:
                separator = self._loop_separator_from_tag(raw_tag)
                body_nodes, next_position, _stop_kind = self._parse_nodes(
                    template_content,
                    match.end(),
                    {"for_end"},
                )
                node_kind = "for_cover" if kind == "for_cover_start" else "for_image"
                nodes.append((node_kind, separator, body_nodes))
                position = next_position
                continue

            position = match.end()

        if position < len(template_content):
            nodes.append(("text", template_content[position:]))

        return nodes, len(template_content), ""

    def _replace_placeholders(
        self,
        content: str,
        data: Dict[str, Any],
        skip_keys: Optional[set] = None,
    ) -> str:
        skip_keys = skip_keys or set()
        for key, value in data.items():
            if key in skip_keys:
                continue
            content = content.replace(f"#{key}#", str(value))
        return content

    @staticmethod
    def _safe_nonnegative_int(value: Any, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    def _cover_requirements_from_nodes(
        self,
        nodes: List[Tuple[Any, ...]],
        data: Dict[str, Any],
    ) -> Tuple[int, bool]:
        cover_slots = 0
        uses_auto_covers = False
        for node in nodes:
            kind = node[0]
            if kind == "text":
                text = str(node[1])
                cover_slots += text.count("#cover_image#") + text.count("#cover_url#")
                if "#cover_images#" in text:
                    uses_auto_covers = True
            elif kind == "if":
                _kind, name, expected, true_nodes, false_nodes = node
                selected_nodes = (
                    true_nodes
                    if self._condition_matches(name, expected, data)
                    else false_nodes
                )
                child_slots, child_auto = self._cover_requirements_from_nodes(selected_nodes, data)
                cover_slots += child_slots
                uses_auto_covers = uses_auto_covers or child_auto
            elif kind == "for_cover":
                uses_auto_covers = True
        return cover_slots, uses_auto_covers

    def _render_nodes(
        self,
        nodes: List[Tuple[Any, ...]],
        data: Dict[str, Any],
        images: List[Tuple[str, str, str]],
        cover_images: Optional[List[Tuple[str, str, str]]] = None,
    ) -> str:
        cover_images = cover_images or []
        rendered: List[str] = []
        for node in nodes:
            kind = node[0]
            if kind == "text":
                rendered.append(node[1])
            elif kind == "if":
                _kind, name, expected, true_nodes, false_nodes = node
                selected_nodes = (
                    true_nodes
                    if self._condition_matches(name, expected, data)
                    else false_nodes
                )
                rendered.append(self._render_nodes(selected_nodes, data, images, cover_images))
            elif kind == "for_image":
                _kind, separator, body_nodes = node
                blocks = []
                for image in images:
                    image_data = self._image_context(data, image)
                    block = self._render_nodes(body_nodes, image_data, images, cover_images)
                    blocks.append(self._replace_placeholders(block, image_data))
                rendered.append(separator.join(blocks))
            elif kind == "for_cover":
                _kind, separator, body_nodes = node
                blocks = []
                for image in cover_images:
                    image_data = self._image_context(data, image)
                    block = self._render_nodes(body_nodes, image_data, images, cover_images)
                    blocks.append(self._replace_placeholders(block, image_data))
                rendered.append(separator.join(blocks))
        return "".join(rendered)

    def _render_template(
        self,
        template_content: str,
        data: Dict[str, Any],
        images: List[Tuple[str, str, str]],
        cover_images: Optional[List[Tuple[str, str, str]]] = None,
    ) -> str:
        return self._render_nodes(
            self._parse_template_nodes(template_content),
            data,
            images,
            cover_images,
        )

    def process_conditionals(self, template_content: str, data: Dict[str, Any]) -> str:
        return self._render_template(template_content, data, [])

    def remove_unresolved_conditionals(self, template_content: str) -> str:
        """Remove app-only conditional syntax before output reaches forums."""
        return self.TEMPLATE_TAG_PATTERN.sub("", template_content)

    def apply(self, format_mode: str, data: Dict[str, Any], images: List[Tuple[str, str, str]]) -> str:
        template = self.get_template(format_mode)
        output_format = self.resolve_output_format(format_mode)
        nodes = self._parse_template_nodes(template)
        data = dict(data)
        if images:
            first_image = images[0]
            first_viewer = first_image[0] if len(first_image) > 0 else ""
            first_thumb = first_image[1] if len(first_image) > 1 else first_viewer
            first_direct = first_image[2] if len(first_image) > 2 else first_viewer
        else:
            first_viewer = ""
            first_thumb = ""
            first_direct = ""
        data.setdefault("image_url", first_viewer)
        data.setdefault("thumb_url", first_thumb)
        data.setdefault("direct_url", first_direct)
        data.setdefault("image_count", len(images))

        temp_data = data.copy()
        temp_data.setdefault("all_images", "dummy")
        temp_data.setdefault("all_full_images", "dummy")
        temp_data.setdefault("cover_image", "dummy")
        temp_data.setdefault("cover_images", "dummy")
        temp_data.setdefault("cover_url", "dummy")
        cover_slots, uses_auto_covers = self._cover_requirements_from_nodes(nodes, temp_data)
        selected_cover_count = self._safe_nonnegative_int(data.get("cover_count"), 0)
        cover_count = max(cover_slots, selected_cover_count if uses_auto_covers else 0)
        cover_count = min(cover_count, len(images))

        covers_extracted = [self._image_values(img) for img in images[:cover_count]]
        remaining_images = images[cover_count:] if cover_count > 0 else images

        filtered_images = []
        for img in remaining_images:
            filtered_images.append(self._image_values(img))

        img_fmt = self.image_formats.get(output_format, self.image_formats["BBCode"])
        processed_images = []
        for v_url, t_url, d_url in filtered_images:
            item_str = img_fmt
            image_data = dict(data)
            image_data["image_url"] = v_url
            image_data["thumb_url"] = t_url
            image_data["direct_url"] = d_url
            processed_images.append(self._replace_placeholders(item_str, image_data))
        data["all_images"] = " ".join(processed_images)

        full_fmt = self.full_image_formats.get(output_format, self.full_image_formats["BBCode"])
        processed_full = []
        for _, t_url, d_url in filtered_images:
            item_str = full_fmt
            image_data = dict(data)
            image_data["image_url"] = d_url
            image_data["thumb_url"] = t_url
            image_data["direct_url"] = d_url
            processed_full.append(self._replace_placeholders(item_str, image_data))
        data["all_full_images"] = " ".join(processed_full)
        data["cover_count"] = len(covers_extracted)
        data["cover_images"] = "\n".join(
            self._replace_placeholders(
                img_fmt,
                {
                    **data,
                    "image_url": viewer_url,
                    "thumb_url": thumb_url,
                    "direct_url": direct_url,
                },
            )
            for viewer_url, thumb_url, direct_url in covers_extracted
        )

        content = self._render_nodes(nodes, data, filtered_images, covers_extracted)

        covers_to_use = covers_extracted.copy()

        def cover_repl(match):
            placeholder = match.group(0)
            if covers_to_use:
                viewer_url, thumb_url, direct_url = covers_to_use.pop(0)
            else:
                viewer_url = str(data.get("image_url", ""))
                thumb_url = str(data.get("cover_url") or data.get("thumb_url", ""))
                direct_url = str(data.get("direct_url", viewer_url))

            if placeholder == "#cover_image#":
                image_data = dict(data)
                image_data["image_url"] = viewer_url
                image_data["thumb_url"] = thumb_url
                image_data["direct_url"] = direct_url
                return self._replace_placeholders(img_fmt, image_data)
            return thumb_url

        content = re.sub(r"#cover_image#|#cover_url#", cover_repl, content)

        return self._replace_placeholders(content, data, skip_keys={"cover_image", "cover_url"})


class TemplateEditor(ctk.CTkToplevel):
    PLACEHOLDER_CATEGORIES = {
        "Images": [
            ("All Images", "#all_images#"),
            ("Full Images", "#all_full_images#"),
            ("All Covers", "#cover_images#"),
            ("Cover{s}", "#cover_image#"),
            ("Cover Count", "#cover_count#"),
            ("Image URL", "#image_url#"),
            ("Thumb URL", "#thumb_url#"),
            ("Direct URL", "#direct_url#"),
            ("Thumb Size", "#thumb_size#"),
            ("Image Count", "#image_count#"),
            ("Cover Loop", "[for cover separator=newline]\n[url=#image_url#][img]#thumb_url#[/img][/url]\n[/for]"),
            ("Loop: Newline", "[for image separator=newline]\n[url=#image_url#][img]#thumb_url#[/img][/url]\n[/for]"),
            ("Loop: Blank Line", "[for image separator=blankline]\n[url=#image_url#][img]#thumb_url#[/img][/url]\n[/for]"),
            ("Loop: Space", "[for image separator=space][url=#image_url#][img]#thumb_url#[/img][/url][/for]"),
        ],
        "Gallery": [
            ("Gallery Link", "#gallery_link#"),
            ("Gallery Name", "#gallery_name#"),
            ("Gallery ID", "#gallery_id#"),
        ],
        "Batch": [
            ("Batch Name", "#batch_name#"),
            ("Upload Date", "#upload_date#"),
        ],
        "Service": [
            ("Service", "#service#"),
        ],
        "ViperGirls": [
            ("Thread Name", "#thread_name#"),
            ("Thread ID", "#thread_id#"),
        ],
    }

    def __init__(self, parent, template_mgr, current_mode="BBCode", data_callback=None, update_callback=None):
        super().__init__(parent)
        self.mgr = template_mgr
        self.data_callback = data_callback
        self.update_callback = update_callback
        self.initial_mode = current_mode
        self.current_template_name = current_mode
        self.loaded_content = ""
        self.last_preview_output = ""
        self.title("Template Editor")
        self.geometry("980x760")
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._init_ui()

    def _init_ui(self):
        main = ctk.CTkFrame(self)
        main.pack(fill="both", expand=True, padx=15, pady=15)
        top = ctk.CTkFrame(main, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(top, text="Edit Format:", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.fmt = ctk.StringVar(value=self.initial_mode)
        self.template_search_var = ctk.StringVar(value="")
        self.template_category_var = ctk.StringVar(value=self.mgr.CATEGORY_ALL)
        all_keys = self.mgr.get_all_keys()
        self.cb_fmt = MouseWheelComboBox(
            top,
            variable=self.fmt,
            values=all_keys,
            state="readonly",
            command=self._handle_template_change,
        )
        self.cb_fmt.pack(side="left", padx=10)
        ctk.CTkLabel(top, text="Category").pack(side="left", padx=(4, 4))
        self.cb_category = MouseWheelComboBox(
            top,
            variable=self.template_category_var,
            values=self.mgr.get_category_names(),
            state="readonly",
            command=lambda _choice: self._refresh_template_lists(self.current_template_name),
            width=120,
        )
        self.cb_category.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(top, text="Search").pack(side="left", padx=(12, 4))
        search_entry = ctk.CTkEntry(top, textvariable=self.template_search_var, width=190)
        search_entry.pack(side="left", padx=(0, 6))
        self.template_search_var.trace_add("write", lambda *_: self._refresh_template_lists(self.current_template_name))
        self.template_empty_label = ctk.CTkLabel(top, text="", text_color="gray")
        self.template_empty_label.pack(side="left", padx=(4, 0))

        preset_frame = ctk.CTkFrame(main)
        preset_frame.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(preset_frame, text="Saved Templates:", font=("Segoe UI", 11, "bold")).pack(side="left", padx=5)
        self.saved_tmpl_var = ctk.StringVar(value=self.initial_mode)
        self.cb_saved = MouseWheelComboBox(preset_frame, variable=self.saved_tmpl_var, values=all_keys, state="readonly")
        self.cb_saved.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        ctk.CTkButton(preset_frame, text="Load", width=60, command=self.load_saved_template).pack(side="left", padx=5)
        ctk.CTkButton(preset_frame, text="Duplicate", width=82, command=self.duplicate_current).pack(side="left", padx=3)
        ctk.CTkButton(preset_frame, text="Rename", width=74, command=self.rename_current).pack(side="left", padx=3)
        ctk.CTkButton(
            preset_frame,
            text="Delete",
            width=64,
            fg_color="#B23B3B",
            hover_color="#8F2D2D",
            command=self.delete_current,
        ).pack(side="left", padx=(3, 5))
        ctk.CTkButton(preset_frame, text="Import", width=68, command=self.import_templates).pack(side="left", padx=3)
        ctk.CTkButton(preset_frame, text="Export", width=68, command=self.export_templates).pack(side="left", padx=3)
        toolbar = ctk.CTkFrame(main, height=35)
        toolbar.pack(fill="x", pady=(5, 0))
        for text, mode in [("B", "Bold"), ("I", "Italic"), ("U", "Underline")]:
            ctk.CTkButton(toolbar, text=text, width=30, command=lambda m=mode: self.format_text(m)).pack(side="left", padx=2, pady=2)
        ctk.CTkButton(toolbar, text="Color", width=50, command=lambda: self.format_complex("Color")).pack(side="left", padx=2, pady=2)
        ctk.CTkFrame(toolbar, width=2, height=20, fg_color="gray").pack(side="left", padx=5)
        ctk.CTkLabel(toolbar, text="Size:", width=30).pack(side="left", padx=(5, 2))
        self.cb_size = MouseWheelComboBox(toolbar, width=60, values=["1", "2", "3", "4", "5", "6", "7"], command=lambda v: self.apply_from_combo("Size", v))
        self.cb_size.pack(side="left", padx=2)
        self.cb_size.set("")
        ctk.CTkLabel(toolbar, text="Font:", width=30).pack(side="left", padx=(5, 2))
        self.cb_font = MouseWheelComboBox(toolbar, width=120, values=["Arial", "Courier New", "Times New Roman", "Verdana", "Segoe UI", "Helvetica"], command=lambda v: self.apply_from_combo("Font", v))
        self.cb_font.pack(side="left", padx=2)
        self.cb_font.set("")
        placeholder_panel = ctk.CTkFrame(main)
        placeholder_panel.pack(fill="x", pady=(5, 5))
        placeholder_panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(placeholder_panel, text="Placeholders", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=(8, 6), pady=6
        )
        self.placeholder_category_var = ctk.StringVar(value="Images")
        self.placeholder_category_menu = ctk.CTkOptionMenu(
            placeholder_panel,
            variable=self.placeholder_category_var,
            values=list(self.PLACEHOLDER_CATEGORIES),
            command=lambda _choice: self._render_placeholder_buttons(),
            width=120,
        )
        self.placeholder_category_menu.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=6)
        self.placeholder_buttons_frame = ctk.CTkFrame(placeholder_panel, fg_color="transparent")
        self.placeholder_buttons_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self._render_placeholder_buttons()

        self.txt = ctk.CTkTextbox(main, wrap="word", font=("Consolas", 12))
        self.txt.pack(fill="both", expand=True, pady=(0, 15))
        btn = ctk.CTkFrame(main, fg_color="transparent")
        btn.pack(fill="x")
        ctk.CTkButton(btn, text="Preview in Browser", command=self.generate_preview).pack(side="left")
        ctk.CTkButton(btn, text="Copy Preview Output", command=self.copy_preview_output).pack(
            side="left", padx=(8, 0)
        )
        ctk.CTkButton(
            btn,
            text="Restore Defaults",
            command=self.restore_defaults,
            fg_color="gray",
            hover_color="#666666",
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(btn, text="Save As New...", command=self.save_as_new, fg_color="green").pack(side="right", padx=(5, 0))
        ctk.CTkButton(btn, text="Save Current", command=self.save).pack(side="right")
        self.load_curr()

    def get_tags(self, mode, value=None):
        fmt = self.mgr.resolve_output_format(self.fmt.get())
        if mode == "Bold":
            return ("[b]", "[/b]") if fmt == "BBCode" else (("**", "**") if fmt == "Markdown" else ("<b>", "</b>"))
        if mode == "Italic":
            return ("[i]", "[/i]") if fmt == "BBCode" else (("*", "*") if fmt == "Markdown" else ("<i>", "</i>"))
        if mode == "Underline":
            return ("[u]", "[/u]") if fmt == "BBCode" else ("<u>", "</u>")
        if mode == "Color":
            return (f"[color={value}]", "[/color]") if fmt == "BBCode" else (f'<span style="color:{value}">', "</span>")
        if mode == "Size":
            return (f"[size={value}]", "[/size]") if fmt == "BBCode" else (f'<span style="font-size:{value}px">', "</span>")
        if mode == "Font":
            return (f"[font={value}]", "[/font]") if fmt == "BBCode" else (f'<span style="font-family:{value}">', "</span>")
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
            color = colorchooser.askcolor(title="Select Color")
            if color and color[1]:
                val = color[1]
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

    @classmethod
    def supported_placeholder_values(cls) -> List[str]:
        return [
            value
            for placeholders in cls.PLACEHOLDER_CATEGORIES.values()
            for _label, value in placeholders
        ]

    def _render_placeholder_buttons(self):
        for widget in self.placeholder_buttons_frame.winfo_children():
            widget.destroy()

        category = self.placeholder_category_var.get()
        placeholders = self.PLACEHOLDER_CATEGORIES.get(category, [])
        if not placeholders:
            ctk.CTkLabel(
                self.placeholder_buttons_frame,
                text="No placeholders in this category.",
                text_color="gray",
            ).grid(row=0, column=0, sticky="w", padx=6, pady=4)
            return

        for index, (label, value) in enumerate(placeholders):
            row = index // 4
            column = index % 4
            ctk.CTkButton(
                self.placeholder_buttons_frame,
                text=label,
                width=118,
                height=24,
                command=lambda v=value: self.ins(v),
            ).grid(row=row, column=column, sticky="w", padx=3, pady=3)

    def _editor_content(self) -> str:
        return self.txt.get("0.0", "end").strip()

    def is_dirty(self) -> bool:
        return self._editor_content() != self.loaded_content

    def _handle_template_change(self, choice=None):
        self.load_curr(choice or self.fmt.get())

    def _confirm_discard_changes(self) -> bool:
        if not self.is_dirty():
            return True

        result = messagebox.askyesnocancel(
            "Unsaved Template",
            "Save changes to the current template before continuing?",
        )
        if result is None:
            return False
        if result:
            return self.save(show_success=False)
        return True

    def _refresh_template_lists(self, selected: str) -> None:
        keys = self.mgr.filter_template_names(
            self.template_search_var.get(),
            self.template_category_var.get(),
        )
        self.cb_saved.configure(values=keys)
        self.cb_fmt.configure(values=keys)
        self.cb_category.configure(values=self.mgr.get_category_names())
        self.template_empty_label.configure(
            text="No matching templates." if not keys else ""
        )
        if selected in keys:
            self.cb_fmt.set(selected)
            self.cb_saved.set(selected)
            self.fmt.set(selected)
            self.saved_tmpl_var.set(selected)

    def _show_validation_errors(self, title: str, exc: Exception) -> None:
        if isinstance(exc, TemplateValidationError):
            messagebox.showerror(title, "Fix these template issues:\n\n" + "\n".join(exc.errors))
            return
        messagebox.showerror(title, str(exc))

    def _confirm_template_warnings(self, name: str, content: str) -> bool:
        warnings = self.mgr.template_warnings(name, content)
        if not warnings:
            return True
        return messagebox.askyesno(
            "Template Warning",
            "Review this template before saving:\n\n"
            + "\n".join(warnings)
            + "\n\nSave anyway?",
        )

    def _load_template_content(self, name: str) -> None:
        self.txt.delete("0.0", "end")
        content = self.mgr.get_template(name)
        self.txt.insert("0.0", content)
        self.current_template_name = name
        self.loaded_content = content.strip()
        self._refresh_template_lists(name)

    def load_curr(self, name=None):
        target_name = name or self.fmt.get()
        if target_name == self.current_template_name and self.loaded_content:
            return
        if not self._confirm_discard_changes():
            self._refresh_template_lists(self.current_template_name)
            return
        self._load_template_content(target_name)

    def load_saved_template(self):
        sel = self.saved_tmpl_var.get()
        if not sel:
            return
        self.load_curr(sel)

    def save(self, show_success: bool = True) -> bool:
        name = self.fmt.get().strip()
        content = self._editor_content()
        if not self._confirm_template_warnings(name, content):
            return False
        try:
            self.mgr.set_template(name, content)
        except (TemplateValidationError, OSError) as exc:
            self._show_validation_errors("Template Not Saved", exc)
            return False

        self.current_template_name = name
        self.loaded_content = content
        self._refresh_template_lists(name)
        if show_success:
            messagebox.showinfo("Saved", f"Template '{name}' updated.")
        if self.update_callback:
            self.update_callback(name)
        return True

    def save_as_new(self):
        dialog = ctk.CTkInputDialog(text="Enter name:", title="Save As New")
        new_name = dialog.get_input()
        if not new_name:
            return
        clean_name = new_name.strip()
        if clean_name in self.mgr.templates and not messagebox.askyesno(
            "Replace Template",
            f"Replace existing template '{clean_name}'?",
        ):
            return
        content = self._editor_content()
        if not self._confirm_template_warnings(clean_name, content):
            return
        try:
            self.mgr.set_template(clean_name, content)
        except (TemplateValidationError, OSError) as exc:
            self._show_validation_errors("Template Not Saved", exc)
            return
        self._load_template_content(clean_name)
        messagebox.showinfo("Success", f"Created: {clean_name}")
        if self.update_callback:
            self.update_callback(clean_name)

    def duplicate_current(self):
        source_name = self.current_template_name
        dialog = ctk.CTkInputDialog(text=f"Duplicate '{source_name}' as:", title="Duplicate Template")
        new_name = dialog.get_input()
        if not new_name:
            return
        clean_name = new_name.strip()
        if clean_name in self.mgr.templates and not messagebox.askyesno(
            "Replace Template",
            f"Replace existing template '{clean_name}'?",
        ):
            return
        content = self._editor_content()
        if not self._confirm_template_warnings(clean_name, content):
            return
        try:
            self.mgr.set_template(clean_name, content)
        except (TemplateValidationError, OSError) as exc:
            self._show_validation_errors("Duplicate Failed", exc)
            return
        self._load_template_content(clean_name)
        messagebox.showinfo("Template Duplicated", f"Created: {clean_name}")
        if self.update_callback:
            self.update_callback(clean_name)

    def rename_current(self):
        old_name = self.current_template_name
        dialog = ctk.CTkInputDialog(text=f"Rename '{old_name}' to:", title="Rename Template")
        new_name = dialog.get_input()
        if not new_name:
            return
        clean_name = new_name.strip()
        if clean_name != old_name and clean_name in self.mgr.templates and not messagebox.askyesno(
            "Replace Template",
            f"Replace existing template '{clean_name}'?",
        ):
            return
        content = self._editor_content()
        if not self._confirm_template_warnings(clean_name, content):
            return
        try:
            self.mgr.rename_template(old_name, clean_name, content)
        except (TemplateValidationError, OSError, KeyError) as exc:
            self._show_validation_errors("Rename Failed", exc)
            return
        self._load_template_content(clean_name)
        messagebox.showinfo("Template Renamed", f"Renamed to: {clean_name}")
        if self.update_callback:
            self.update_callback(clean_name)

    def delete_current(self):
        name = self.current_template_name
        if not messagebox.askyesno("Delete Template", f"Delete template '{name}'?"):
            return
        try:
            self.mgr.delete_template(name)
        except (TemplateValidationError, OSError) as exc:
            self._show_validation_errors("Delete Failed", exc)
            return
        keys = self.mgr.get_all_keys()
        next_name = keys[0] if keys else "BBCode"
        if not keys:
            self.mgr.restore_defaults()
            keys = self.mgr.get_all_keys()
            next_name = keys[0]
        self._load_template_content(next_name)
        messagebox.showinfo("Template Deleted", f"Deleted: {name}")
        if self.update_callback:
            self.update_callback(next_name)

    def import_templates(self):
        filepath = filedialog.askopenfilename(
            title="Import Templates",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return

        overwrite = True
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            raw_templates = raw_data.get("templates", raw_data) if isinstance(raw_data, dict) else {}
            duplicates = [
                str(name).strip()
                for name in raw_templates
                if str(name).strip() in self.mgr.templates
            ]
        except Exception:
            duplicates = []

        if duplicates:
            overwrite = messagebox.askyesno(
                "Import Templates",
                f"{len(duplicates)} template name(s) already exist. Replace matching templates?",
            )

        try:
            imported, skipped, errors = self.mgr.import_templates_file(filepath, overwrite=overwrite)
        except (OSError, json.JSONDecodeError, TemplateValidationError) as exc:
            self._show_validation_errors("Import Failed", exc)
            return

        self._refresh_template_lists(self.current_template_name)
        if imported and self.current_template_name not in self.mgr.templates:
            self._load_template_content(self.mgr.get_all_keys()[0])
        message = f"Imported {imported} template(s). Skipped {skipped} template(s)."
        if errors:
            message += "\n\n" + "\n".join(errors[:8])
            if len(errors) > 8:
                message += f"\n...and {len(errors) - 8} more issue(s)."
        messagebox.showinfo("Import Complete", message)
        if imported and self.update_callback:
            self.update_callback(self.current_template_name)

    def export_templates(self):
        filepath = filedialog.asksaveasfilename(
            title="Export Templates",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filepath:
            return
        try:
            exported = self.mgr.export_templates_file(filepath)
        except OSError as exc:
            messagebox.showerror("Export Failed", f"Could not export templates:\n{exc}")
            return
        messagebox.showinfo("Export Complete", f"Exported {exported} template(s).")

    def restore_defaults(self):
        if not messagebox.askyesno(
            "Restore Defaults",
            "Restore the built-in templates and remove saved custom templates?",
        ):
            return

        self.mgr.restore_defaults()
        self.current_template_name = "BBCode"
        self.loaded_content = ""
        self._load_template_content("BBCode")
        messagebox.showinfo("Templates Restored", "Default templates have been restored.")
        if self.update_callback:
            self.update_callback("BBCode")

    def close(self):
        if self._confirm_discard_changes():
            self.destroy()

    def generate_preview(self):
        preview = self._build_preview_output()
        if not preview:
            return
        raw, curr_fmt, size = preview
        self.last_preview_output = raw

        final_html = self.build_preview_html(raw, curr_fmt, str(size))
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
                f.write(final_html)
                path = f.name
            webbrowser.open("file://" + path)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def copy_preview_output(self):
        preview = self._build_preview_output()
        if not preview:
            return
        raw, _curr_fmt, _size = preview
        self.last_preview_output = raw
        try:
            pyperclip.copy(raw)
            messagebox.showinfo("Preview Copied", "Raw preview output copied to clipboard.")
        except (OSError, pyperclip.PyperclipException) as exc:
            messagebox.showerror("Copy Failed", f"Could not copy preview output:\n{exc}")

    def _build_preview_output(self) -> Optional[Tuple[str, str, str]]:
        if not self.data_callback:
            messagebox.showwarning(
                "Preview Unavailable",
                "Preview needs files from the upload queue. Add one or more images, then try again.",
            )
            return None

        content = self._editor_content()
        errors = self.mgr.validate_template(content)
        if errors:
            messagebox.showerror("Preview", "Fix these template issues before previewing:\n\n" + "\n".join(errors))
            return None

        try:
            preview_data = self.data_callback()
        except Exception as exc:
            messagebox.showerror("Preview Unavailable", f"Could not prepare preview data:\n{exc}")
            return None

        cover_count = 0
        if preview_data:
            if len(preview_data) >= 4:
                files, title, size, cover_count = preview_data[:4]
            else:
                files, title, size = preview_data[:3]
        else:
            files, title, size = None, None, None

        if not files:
            messagebox.showwarning(
                "Preview Unavailable",
                "Add one or more image files to the upload queue before previewing a template.",
            )
            return None
        if not size or not str(size).isdigit():
            size = "200"

        mock = []
        for file_path in files:
            path_url = f"file:///{urllib.parse.quote(file_path.replace(os.sep, '/'))}"
            mock.append((path_url, path_url, path_url))

        curr_fmt = self.fmt.get()
        output_fmt = self.mgr.resolve_output_format(curr_fmt)
        existed = curr_fmt in self.mgr.templates
        orig = self.mgr.templates.get(curr_fmt)
        self.mgr.templates[curr_fmt] = content
        ctx = {
            "batch_name": title,
            "gallery_link": "http://localhost/preview",
            "gallery_name": title,
            "gallery_id": "PREV_123",
            "cover_url": mock[0][1] if mock else "",
            "cover_count": self.mgr._safe_nonnegative_int(cover_count, 0),
            "image_count": len(mock),
            "service": "preview",
            "thread_name": "Preview Thread",
            "thread_id": "PREV_THREAD",
            "upload_date": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            raw = self.mgr.apply(curr_fmt, ctx, mock)
        finally:
            if existed:
                self.mgr.templates[curr_fmt] = orig
            else:
                self.mgr.templates.pop(curr_fmt, None)
        return raw, output_fmt, str(size)

    @staticmethod
    def build_preview_html(raw: str, curr_fmt: str, size: str) -> str:
        rendered = raw if curr_fmt == "HTML" else html.escape(raw).replace("\n", "<br>")
        if curr_fmt != "HTML":
            rendered = re.sub(r"\[url=(.*?)\]", r'<a href="\1">', rendered)
            rendered = rendered.replace("[/url]", "</a>")
            rendered = re.sub(r"\[img\](.*?)\[/img\]", f'<img src="\\1" style="max-width:{size}px">', rendered)

        raw_output = html.escape(raw)
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Template Preview</title>
<style>
body {{ padding: 20px; font-family: Segoe UI, Arial, sans-serif; color: #202124; }}
h1 {{ font-size: 20px; margin: 0 0 18px; }}
h2 {{ font-size: 15px; margin: 22px 0 8px; }}
.preview {{ border: 1px solid #d0d7de; border-radius: 6px; padding: 14px; }}
pre {{ white-space: pre-wrap; word-break: break-word; border: 1px solid #d0d7de; border-radius: 6px; padding: 14px; background: #f6f8fa; }}
</style>
</head>
<body>
<h1>Template Preview</h1>
<h2>Rendered Preview</h2>
<div class="preview">{rendered}</div>
<h2>Raw Generated Output</h2>
<pre>{raw_output}</pre>
</body>
</html>"""
