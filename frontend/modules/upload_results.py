# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Building blocks for a host plugin's ``parse_upload_response``.

Plugins on the Python upload path get the host's raw answer to each upload
(a ``TransportResponse``) and return an ``UploadResult``. This module holds
what most parsers need, ported from the legacy Go parser so both paths give
the same results for the same responses (see tests/test_upload_parity.py):

- ``parse_json_upload``: the common "check a status field, read the link
  and thumbnail from JSON paths or templates" parser, with the failure rules
  below.
- ``upload_failure`` / ``request_failure``: failure messages that carry the
  HTTP status and the host's own message (a JSON ``error``/``message``/``msg``
  field, nested or not), else a short visible-text snippet of the page with
  scripts and styles stripped, with credentials and session values redacted.
- ``json_value``, ``apply_response_template``, ``split_url_extension``,
  ``html_field``: the legacy response_parser primitives.

Known flavour differences from Go: CSS selection uses BeautifulSoup's
``html.parser`` instead of an HTML5 parser, and regular expressions use
Python ``re`` instead of RE2 (avoid backtracking-only constructs).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

# Shown when a host's answer has no viewer link and the parser gave no reason.
NO_LINK_ERROR = "Host returned no link"

# How much of a host's response a failure message quotes.
MAX_SNIPPET_CHARS = 200

# Values shorter than this are not redacted: they would mangle the text.
MIN_SECRET_LENGTH = 4

# JSON fields hosts use to explain a failure, most specific first. Only string
# values count.
HOST_MESSAGE_KEYS = (
    "error.message",
    "error",
    "message",
    "msg",
    "error_message",
    "errors.0.message",
    "errors.0",
    "data.error.message",
    "data.error",
    "data.message",
    "detail",
    "reason",
    "status_txt",
)


@dataclass(frozen=True)
class UploadResult:
    """What a plugin's ``parse_upload_response`` found for one file.

    A result is a success only with a viewer ``url`` and no ``error``. A
    result with neither fails the file with "Host returned no link".
    ``gallery_url`` is the gallery the upload landed in, when the host says.
    """

    url: str = ""
    thumb: str = ""
    gallery_url: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.url.strip()) and not self.error

    @property
    def failure_reason(self) -> str:
        """Why the file failed, or "" for a success."""
        if self.ok:
            return ""
        return self.error or NO_LINK_ERROR

    @classmethod
    def failed(cls, error: str) -> "UploadResult":
        return cls(error=str(error or NO_LINK_ERROR))


# --- Failure messages ----------------------------------------------------------------


def collect_secrets(*mappings: Optional[Mapping[str, Any]], extra: Iterable[str] = ()) -> List[str]:
    """Every value of ``mappings`` (and ``extra``) worth redacting, longest first."""
    values: List[str] = list(extra)
    for mapping in mappings:
        for value in (mapping or {}).values():
            if isinstance(value, str):
                values.append(value)
    return normalize_secrets(values)


def normalize_secrets(secrets: Iterable[str]) -> List[str]:
    unique = {
        str(secret)
        for secret in secrets or ()
        if len(str(secret or "").strip()) >= MIN_SECRET_LENGTH
    }
    # Longest first, so a secret that contains another is redacted whole.
    return sorted(unique, key=len, reverse=True)


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    for secret in normalize_secrets(secrets):
        text = text.replace(secret, "[redacted]")
    return text


def collapse_text(text: str) -> str:
    """Control characters become spaces; runs of whitespace become one space."""
    text = "".join(" " if unicodedata.category(char) == "Cc" else char for char in str(text))
    return " ".join(text.split())


def truncate_text(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].strip() + "…"


def host_message(body: str) -> str:
    """The host's error text from a JSON body, else a short snippet of the page."""
    return truncate_text(host_message_text(body))


def host_message_text(body: str) -> str:
    """``host_message`` without the length limit, so secrets can be redacted first."""
    trimmed = str(body or "").strip()
    if not trimmed:
        return ""
    if trimmed.startswith("{"):
        data = _loads(trimmed)
        if isinstance(data, dict):
            for path in HOST_MESSAGE_KEYS:
                message = _json_string_at(data, path)
                if message:
                    return collapse_text(message)
            return collapse_text(trimmed)
    if "<" in trimmed:
        text = html_visible_text(trimmed)
        if text:
            return text
    return collapse_text(trimmed)


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return _INVALID


_INVALID = object()


def _json_string_at(data: Any, path: str) -> str:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            index = _atoi(part)
            if index is None or not 0 <= index < len(current):
                return ""
            current = current[index]
        else:
            return ""
    return current.strip() if isinstance(current, str) else ""


_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "head"})


def html_visible_text(body: str) -> str:
    """The visible text of an HTML page: its body without scripts or styles, else its title."""
    soup = BeautifulSoup(body, "html.parser")
    root: Any = soup.body
    skipped = _SKIPPED_TAGS
    if root is None:
        # Without a <body> the whole document counts, as an HTML5 parser
        # would put it in one, except what belongs in <head>.
        root = soup
        skipped = _SKIPPED_TAGS | {"title"}
    parts: List[str] = []

    def walk(node: Any) -> None:
        for child in node.children:
            if isinstance(child, Tag):
                if child.name not in skipped:
                    walk(child)
            elif type(child) is NavigableString:
                parts.append(str(child))

    walk(root)
    text = collapse_text(" ".join(parts))
    if text:
        return text
    return collapse_text(soup.title.get_text()) if soup.title else ""


def upload_failure(reason: str, status_code: int, body: str, secrets: Iterable[str] = ()) -> str:
    """Describe a host's refusal: the reason, the HTTP status and the host's message.

    The quoted text is redacted, then cut to MAX_SNIPPET_CHARS.
    """
    detail = truncate_text(redact_secrets(host_message_text(body), secrets))
    if not detail:
        return f"{reason} (HTTP {status_code})"
    return f"{reason} (HTTP {status_code}): {detail}"


# Go reports a non-2xx answer as "[context ]HTTP <code>[: <body>]", possibly
# wrapped ("max retries (3) exhausted, last error: HTTP 503: ...").
_HTTP_STATUS_MESSAGE = re.compile(r"HTTP (\d{3})(?:: (.*))?\Z", re.S)


def request_failure(reason: str, response: Any, secrets: Iterable[str] = ()) -> str:
    """Describe a failed request (a login, a follow-up, a result page) for the user.

    Uses the same extraction, redaction and length limit as ``upload_failure``:
    the host's whole page is never quoted.
    """
    status = int(getattr(response, "status_code", 0) or 0)
    body = str(getattr(response, "body", "") or "")
    message = str(getattr(response, "message", "") or "")
    if getattr(response, "status", "") == "cancelled":
        return f"{reason}: {message or 'Upload cancelled'}"
    if not status:
        match = _HTTP_STATUS_MESSAGE.search(message)
        if match:
            status, body = int(match.group(1)), match.group(2) or ""
    if status and (body or not 200 <= status < 300):
        return upload_failure(reason, status, body, secrets)
    detail = truncate_text(redact_secrets(collapse_text(message), secrets))
    return f"{reason}: {detail}" if detail else reason


# --- JSON paths and templates ------------------------------------------------------


def _atoi(text: str) -> Optional[int]:
    return int(text) if re.fullmatch(r"[+-]?[0-9]+", text) else None


def _scalar_to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(Decimal(repr(value)), "f")
    return ""


def json_value(data: Any, path: str) -> str:
    """A scalar at a dotted path (``data.link``, ``files.0.url``) as text, else "".

    Numbers are written without exponents and booleans as true/false, as the
    legacy Go parser does.
    """
    if not path:
        return ""
    current = data
    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            index = _atoi(part)
            if index is None or not 0 <= index < len(current):
                return ""
            current = current[index]
        else:
            return ""
    return _scalar_to_string(current)


def _find_json_scalar(value: Any, key: str) -> str:
    if isinstance(value, dict):
        if key in value:
            return _scalar_to_string(value[key])
        children: Iterable[Any] = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return ""
    for child in children:
        found = _find_json_scalar(child, key)
        if found:
            return found
    return ""


def _path_ext(path: str) -> str:
    """The extension of the last path element, from its last dot (Go's path.Ext)."""
    for index in range(len(path) - 1, -1, -1):
        char = path[index]
        if char in "/\\":
            break
        if char == ".":
            return path[index:]
    return ""


def split_url_extension(link: str) -> Tuple[str, str]:
    """Split a link into everything before its path's extension, and the extension.

    ``https://h/a/x.jpg?q#f`` -> (``https://h/a/x``, ``.jpg``). The query and
    fragment are dropped; the path keeps the link's own escaping (``%2F``
    stays ``%2F``, ``(`` stays ``(``).
    """
    link = str(link or "").strip()
    if not link:
        return "", ""
    try:
        parts = urlsplit(link)
    except ValueError:
        return link, ""
    bare = parts._replace(query="", fragment="")
    ext = _path_ext(parts.path)
    if not ext:
        return urlunsplit(bare), ""
    return urlunsplit(bare._replace(path=parts.path[: -len(ext)])), ext


_TEMPLATE_TOKEN = re.compile(r"\{([^{}]+)\}")


def apply_response_template(template: str, data: Any, file_path: str, result_url: str = "") -> str:
    """Fill a legacy url/thumb template.

    ``{filename}``, ``{basename}``, ``{ext}``, ``{dot_ext}`` come from the local
    file; ``{url_no_ext}`` and ``{url_dot_ext}`` from ``result_url`` (see
    ``split_url_extension``); any other ``{key}`` is a JSON value by dotted
    path, else the first value with that key anywhere in ``data``.
    """
    base = os.path.basename(str(file_path or ""))
    dot_ext = _path_ext(base)
    ext = dot_ext[1:] if dot_ext else ""
    stem = base[: -len(dot_ext)] if dot_ext else base
    url_no_ext, url_dot_ext = split_url_extension(result_url)
    fixed = {
        "filename": base,
        "basename": stem,
        "ext": ext,
        "extension": ext,
        "dot_ext": dot_ext if ext else "",
        "url_no_ext": url_no_ext,
        "url_dot_ext": url_dot_ext,
    }

    def fill(match: "re.Match[str]") -> str:
        key = match.group(0).strip("{}").strip()
        if key in fixed:
            return fixed[key]
        if data is None:
            return ""
        return json_value(data, key) or _find_json_scalar(data, key)

    return _TEMPLATE_TOKEN.sub(fill, str(template or ""))


_SELECTION_ATTRIBUTES = ("value", "content", "action", "href", "src", "data-url")


def html_field(body: str, selector: str) -> str:
    """One value from an HTML page, as the legacy ``extract_fields`` read it.

    ``regex:<pattern>`` returns the first match's first group (else the whole
    match). Otherwise ``selector`` is a CSS selector and the first match gives
    its value, content, action, href, src or data-url attribute (the first
    that is not blank), else its text.
    """
    if not selector:
        return ""
    if selector.startswith("regex:"):
        match = re.search(selector[len("regex:") :], str(body or ""))
        if not match:
            return ""
        value = match.group(1) if match.re.groups >= 1 else match.group(0)
        return (value or "").strip()
    element = BeautifulSoup(str(body or ""), "html.parser").select_one(selector)
    if element is None:
        return ""
    for attribute in _SELECTION_ATTRIBUTES:
        value = element.get(attribute)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return element.get_text().strip()


# --- The common JSON upload parser ---------------------------------------------------

_JSON_PARSER_KEYS = (
    "url_path",
    "thumb_path",
    "status_path",
    "success_value",
    "url_template",
    "thumb_template",
)


def json_parser_options(parser: Mapping[str, Any]) -> Dict[str, str]:
    """``parse_json_upload`` options from a legacy JSON ``response_parser`` dict.

    Lets a migrated plugin keep one parser definition for both paths.
    """
    if str(parser.get("type") or "json").lower() != "json":
        raise ValueError(f"not a JSON response_parser: {parser.get('type')!r}")
    return {key: str(parser.get(key) or "") for key in _JSON_PARSER_KEYS}


def parse_json_upload(
    response: Any,
    *,
    url_path: str,
    file_path: str = "",
    thumb_path: str = "",
    status_path: str = "",
    success_value: str = "",
    url_template: str = "",
    thumb_template: str = "",
    secrets: Iterable[str] = (),
) -> UploadResult:
    """Parse a JSON upload answer the way the legacy ``response_parser`` did.

    A non-2xx answer, a body that is not a JSON object, a ``status_path`` value
    other than ``success_value``, or an answer without a link is a failure
    whose error names the HTTP status and the host's own message.
    """
    if not getattr(response, "ok", True):
        return UploadResult.failed(request_failure("upload failed", response, secrets))
    status = int(response.status_code or 0)
    body = str(response.body or "")
    if not 200 <= status < 300:
        return UploadResult.failed(upload_failure("upload rejected", status, body, secrets))
    data = _loads(body)
    if data is None:
        data = {}  # "null" decodes to an empty object, as in Go
    if not isinstance(data, dict):
        return UploadResult.failed(
            upload_failure("upload response was not valid JSON", status, body, secrets)
        )
    if status_path and json_value(data, status_path) != success_value:
        return UploadResult.failed(
            upload_failure("upload failed: status check did not match", status, body, secrets)
        )
    url = json_value(data, url_path)
    if not url and url_template:
        url = apply_response_template(url_template, data, file_path)
    thumb = json_value(data, thumb_path)
    if not thumb and thumb_template:
        thumb = apply_response_template(thumb_template, data, file_path, url)
    if not url.strip():
        return UploadResult.failed(
            upload_failure("upload response had no image link", status, body, secrets)
        )
    return UploadResult(url=url, thumb=thumb)
