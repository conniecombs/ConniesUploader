# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Headless template loading and rendering for non-Tk runtimes."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import config


DEFAULT_TEMPLATE_FILE = "templates.json"


class HeadlessTemplateManager:
    """Render Connie's Uploader templates without importing desktop UI modules."""

    TEMPLATE_TAG_PATTERN = re.compile(
        r"\[(?P<tag>else|/if|/for|if(?:\s+[^\]]*)?|for\s+(?:image|cover)(?:\s+[^\]]*)?)\]",
        re.IGNORECASE,
    )
    CONDITIONAL_START_PATTERN = re.compile(r"^if(?:\s+(.+))?$", re.IGNORECASE)
    CONDITIONAL_EXPRESSION_PATTERN = re.compile(
        r"^#?([A-Za-z_][A-Za-z0-9_]*)#?(?:\s*=\s*(.+))?$"
    )
    LOOP_START_PATTERN = re.compile(r"^for\s+(image|cover)(?:\s+(.+))?$", re.IGNORECASE)
    LOOP_SEPARATOR_PATTERN = re.compile(
        r"(?:separator|sep)\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)",
        re.IGNORECASE,
    )
    CUSTOM_CATEGORY = "Custom"
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
            "Vipr Forum (Center)": "[center][url=#gallery_link#][b]Open Full Gallery[/b][/url][/center]\n\n#all_images#",
            "Vipr Forum (Simple)": "[b]Gallery:[/b] [url=#gallery_link#]#gallery_name#[/url]\n\n#all_images#",
            "Reddit Markdown": "[View Gallery](#gallery_link#)\n\n#all_images#",
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
            "Markdown": "![](#image_url#)",
            "HTML": '<img src="#image_url#">',
        }
        self.templates = self.defaults.copy()
        self.filepath = filepath or os.path.join(config.USER_DATA_DIR, DEFAULT_TEMPLATE_FILE)
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            if isinstance(saved, dict):
                self.templates.update(
                    {str(key): str(value) for key, value in saved.items()}
                )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return

    def get_template(self, name: str) -> str:
        return self.templates.get(name, self.defaults.get(name, ""))

    def get_template_category(self, name: str) -> str:
        return self.BUILTIN_TEMPLATE_CATEGORIES.get(name, self.CUSTOM_CATEGORY)

    def resolve_output_format(self, name: str) -> str:
        category = self.get_template_category(name)
        return self.OUTPUT_FORMAT_BY_CATEGORY.get(category, "BBCode")

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
        viewer_url = image[0] if len(image) > 0 and image[0] is not None else ""
        thumb_url = image[1] if len(image) > 1 and image[1] is not None else viewer_url
        direct_url = image[2] if len(image) > 2 and image[2] is not None else viewer_url
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

    def _parse_template_nodes(self, template_content: str) -> List[Tuple[Any, ...]]:
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
                nodes.append(("if", name if valid else "", expected, true_nodes, false_nodes))
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

    def apply(
        self,
        format_mode: str,
        data: Dict[str, Any],
        images: List[Tuple[str, str, str]],
    ) -> str:
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
        filtered_images = [self._image_values(img) for img in remaining_images]

        img_fmt = self.image_formats.get(output_format, self.image_formats["BBCode"])
        data["all_images"] = " ".join(
            self._replace_placeholders(
                img_fmt,
                {
                    **data,
                    "image_url": viewer_url,
                    "thumb_url": thumb_url,
                    "direct_url": direct_url,
                },
            )
            for viewer_url, thumb_url, direct_url in filtered_images
        )

        full_fmt = self.full_image_formats.get(output_format, self.full_image_formats["BBCode"])
        data["all_full_images"] = " ".join(
            self._replace_placeholders(
                full_fmt,
                {
                    **data,
                    "image_url": direct_url,
                    "thumb_url": thumb_url,
                    "direct_url": direct_url,
                },
            )
            for _viewer_url, thumb_url, direct_url in filtered_images
        )
        data["cover_count"] = len(covers_extracted)
        data["cover_images"] = " ".join(
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
