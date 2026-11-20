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
``html.parser`` instead of an HTML5 parser (``html_field`` and
``html_visible_text`` make up for what tells them apart on host pages), and
regular expressions use Python ``re`` instead of RE2: compile them with
``compile_re2_pattern`` and avoid backtracking-only constructs.
"""

from __future__ import annotations

import bisect
import dataclasses
import functools
import html
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Doctype, NavigableString, Tag

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
    Every field is text: None (``data.get("url")`` of an answer without the
    key) and other empty values become "", bytes are decoded, and anything
    else is converted with ``str``.
    """

    url: str = ""
    thumb: str = ""
    gallery_url: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        for name in ("url", "thumb", "gallery_url", "error"):
            object.__setattr__(self, name, _as_text(getattr(self, name)))

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
        return cls(error=_as_text(error) or NO_LINK_ERROR)


def _as_text(value: Any) -> str:
    """An UploadResult field as text ("" for None and other empty values)."""
    if isinstance(value, str):
        return value
    if not value:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


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
    return sorted(unique, key=lambda secret: (-len(secret), secret))


REDACTED = "[redacted]"


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    """``text`` with every secret replaced by "[redacted]", as given or escaped.

    A host may echo a credential back URL-encoded (``P%40ss`` or ``my+pass``),
    JSON-escaped (``P@ss\\/w0rd``, ``\\u00e9``) or with HTML character
    references (``&eacute;``, ``&#233;``) in text no parser decoded; those
    forms are redacted too. backend/core/response_errors.go does the same.
    """
    secrets = normalize_secrets(secrets)
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    for pattern, decode in _ESCAPE_FORMS:
        text = _redact_escaped(text, secrets, pattern, decode)
    return text


def _decode_percent(token: str) -> Optional[bytes]:
    return b" " if token == "+" else bytes([int(token[1:], 16)])


_JSON_SHORT_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _decode_json(token: str) -> Optional[bytes]:
    if not token.startswith("\\u"):
        return _JSON_SHORT_ESCAPES[token[1]].encode("utf-8")
    unit = int(token[2:6], 16)
    if len(token) == 12:  # a surrogate pair
        unit = 0x10000 + ((unit - 0xD800) << 10) + (int(token[8:12], 16) - 0xDC00)
    elif 0xD800 <= unit <= 0xDFFF:
        return None  # a lone surrogate stands for no character
    return chr(unit).encode("utf-8")


def _decode_html(token: str) -> Optional[bytes]:
    if token.startswith("&#"):
        digits = token[2:-1]
        code = int(digits[1:], 16) if digits[:1] in ("x", "X") else int(digits)
        if not 0 < code <= 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            return None
        return chr(code).encode("utf-8")
    value = html.unescape(token)
    # A name that is no entity, or only starts with one, keeps its ";".
    return None if value.endswith(";") else value.encode("utf-8")


# The escaped forms a credential may take, each a token pattern and its
# decoder (None: the token stands for nothing, and stays as written). Keep in
# step with escapeForms in backend/core/response_errors.go.
_ESCAPE_FORMS = (
    (re.compile(r"%[0-9A-Fa-f]{2}|\+"), _decode_percent),
    (
        re.compile(
            r"\\u[dD][89abAB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}"
            r'|\\u[0-9a-fA-F]{4}|\\["\\/bfnrt]'
        ),
        _decode_json,
    ),
    (
        re.compile(r"&#[0-9]{1,8};|&#[xX][0-9a-fA-F]{1,8};|&[A-Za-z][A-Za-z0-9]{0,31};"),
        _decode_html,
    ),
)


def _redact_escaped(text: str, secrets: List[str], pattern: "re.Pattern[str]", decode) -> str:
    """Redact each secret where ``text`` spells it with ``pattern``'s escapes.

    The text is decoded into bytes, escape by escape; a secret matches where
    the decoded bytes equal it and it starts and ends on whole escapes (or
    characters). Longest secrets first, left to right, never overlapping.
    """
    segments: List[Tuple[int, int, int, int, bool]] = []  # decoded and text spans
    decoded = bytearray()

    def add(text_start: int, text_end: int, value: bytes, escape: bool) -> None:
        segments.append((len(decoded), len(decoded) + len(value), text_start, text_end, escape))
        decoded.extend(value)

    cursor = 0
    for match in pattern.finditer(text):
        value = decode(match.group(0))
        if value is None:
            continue
        if match.start() > cursor:
            add(
                cursor,
                match.start(),
                text[cursor : match.start()].encode("utf-8", "surrogatepass"),
                False,
            )
        add(match.start(), match.end(), value, True)
        cursor = match.end()
    if not segments:
        return text
    if cursor < len(text):
        add(cursor, len(text), text[cursor:].encode("utf-8", "surrogatepass"), False)
    starts = [segment[0] for segment in segments]

    def text_offset(offset: int) -> Optional[int]:
        """Where a decoded offset is in ``text``; None inside an escape or a character."""
        start, end, text_start, text_end, escape = segments[bisect.bisect_right(starts, offset) - 1]
        if offset == start:
            return text_start
        if offset == end:
            return text_end
        if escape:
            return None
        try:
            return text_start + len(bytes(decoded[start:offset]).decode("utf-8", "surrogatepass"))
        except UnicodeDecodeError:
            return None

    spans: List[Tuple[int, int]] = []
    for secret in secrets:
        needle = secret.encode("utf-8", "surrogatepass")
        position = 0
        while True:
            found = decoded.find(needle, position)
            if found < 0:
                break
            start, end = text_offset(found), text_offset(found + len(needle))
            if (
                start is not None
                and end is not None
                and not any(
                    start < taken_end and taken_start < end for taken_start, taken_end in spans
                )
            ):
                spans.append((start, end))
                position = found + len(needle)
            else:
                position = found + 1
    if not spans:
        return text
    parts, last = [], 0
    for start, end in sorted(spans):
        parts.append(text[last:start])
        parts.append(REDACTED)
        last = end
    parts.append(text[last:])
    return "".join(parts)


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


def _json_number(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"number out of range: {text}")
    return number


def _no_json_constant(name: str) -> Any:
    raise ValueError(f"not JSON: {name}")


def parse_json(text: str) -> Any:
    """Decode JSON as the legacy Go parser did; raises ValueError for what Go rejects.

    Every number is a float, so integers past 2**53 round as in Go, and
    NaN, Infinity and numbers too large for a float are not JSON.
    """
    return json.loads(
        text, parse_int=_json_number, parse_float=_json_number, parse_constant=_no_json_constant
    )


def _loads(text: str) -> Any:
    try:
        return parse_json(text)
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


# Elements whose text is never visible, wherever they are.
_HIDDEN_TAGS = frozenset({"script", "style", "noscript", "template"})
# Elements an HTML5 parser keeps in <head> while no body content came yet.
_HEAD_TAGS = _HIDDEN_TAGS | {"title", "meta", "link", "base", "basefont", "bgsound"}
# Tags an HTML5 parser drops once the body started: their content joins the body.
_TRANSPARENT_TAGS = frozenset({"html", "head", "body"})
_ASCII_WHITESPACE = " \t\n\f\r"


def html_visible_text(body: str) -> str:
    """The visible text of an HTML page: its body without scripts or styles, else its title.

    "Body" is what an HTML5 parser (Go's, on the legacy path) puts there:
    everything from the first visible content on, wherever the page's own
    <html>, <head> and <body> tags are. Text a PHP error printed before
    <html> or after </html> counts, a <title> after body content is text,
    and text on both sides of a dropped tag is one piece ("a<body>b" reads
    "ab"). A <frameset> before any content means the page has no body.
    """
    soup = BeautifulSoup(body, "html.parser")
    pieces: List[str] = []
    in_body = False
    joined = False  # the next text continues the last piece (no node between)

    def walk(node: Any) -> bool:
        """Collect ``node``'s children; False once a frameset ended the document."""
        nonlocal in_body, joined
        for child in node.children:
            if isinstance(child, Tag):
                name = child.name
                if name in _TRANSPARENT_TAGS:
                    in_body = in_body or name == "body"
                    if not walk(child):
                        return False
                    continue
                if not in_body and name in _HEAD_TAGS:
                    continue  # head content
                if not in_body and name == "frameset":
                    return False  # the frameset replaces the body
                in_body, joined = True, False
                if name not in _HIDDEN_TAGS and not walk(child):
                    return False
                joined = False
            elif type(child) is NavigableString:
                text = str(child)
                if not in_body and not text.strip(_ASCII_WHITESPACE):
                    continue
                in_body = True
                if joined:
                    pieces[-1] += text
                else:
                    pieces.append(text)
                    joined = True
            elif in_body and not isinstance(child, Doctype):
                joined = False  # a comment or processing instruction is a node of its own
        return True

    walk(soup)
    text = collapse_text(" ".join(pieces))
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
        return str(value)  # not from a host's answer: parse_json gives floats
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        # Go's strconv.FormatFloat(v, 'f', -1, 64): the shortest digits that
        # read back as the same float, without an exponent ("1", "-0", "12.5").
        return format(Decimal(repr(value)).normalize(), "f")
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


# --- Links as Go's net/url reads and writes them -------------------------------------
#
# The legacy path built thumbnail links ({url_no_ext}) and upload URLs (an
# endpoint read from a host page) with Go's url.Parse, ResolveReference and
# URL.String. These port what changes such a link: which links Go refuses
# (it then keeps the link or the default URL), how a path is escaped (a
# space or "é" becomes %20 or %C3%A9; a valid escape is kept), and how dot
# segments are removed. Not ported, as no host page names such a link: how
# Go escapes a host or user info on output, its user-info checks, a few
# hosts with brackets or braces it accepts, and a relative path that starts
# with three slashes.

_GO_ALNUM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
_GO_VALID_ENCODED = frozenset("!$&'()*+,;=:@[]%")
_GO_HOST_CHARS = _GO_ALNUM | frozenset("-_.~!$&'()*+,;=:[]<>\"")
_GO_HEX = frozenset("0123456789abcdefABCDEF")
_GO_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_GO_PORT = re.compile(r"(?::[0-9]*)?")


def _go_should_escape(byte: int, mode: str) -> bool:
    """Go's shouldEscape for a path ("path") or a fragment ("fragment")."""
    char = chr(byte)
    if char in _GO_ALNUM or char in "-_.~":
        return False
    if char in "$&+,/:;=?@":
        return mode == "path" and char == "?"
    return not (mode == "fragment" and char in "!()*")


def _go_unescape(text: str, mode: str) -> Optional[bytes]:
    """Go's unescape: the bytes ``text`` stands for, or None for a bad escape."""
    raw = text.encode("utf-8", "surrogatepass")
    out = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x25:  # "%"
            pair = raw[index + 1 : index + 3].decode("latin-1")
            if len(pair) < 2 or not set(pair) <= _GO_HEX:
                return None
            if mode == "host" and int(pair[0], 16) < 8 and pair != "25":
                return None  # a host escapes only non-ASCII bytes
            out.append(int(pair, 16))
            index += 3
            continue
        if mode == "host" and byte < 0x80 and chr(byte) not in _GO_HOST_CHARS:
            return None
        out.append(byte)
        index += 1
    return bytes(out)


def _go_escaped(text: str, mode: str) -> Optional[str]:
    """Go's EscapedPath / EscapedFragment for ``text`` as written; None if Go refuses it.

    Kept as written when every character may stand there, else escaped anew.
    """
    raw = _go_unescape(text, mode)
    if raw is None:
        return None
    if all(
        char in _GO_VALID_ENCODED or (ord(char) < 0x80 and not _go_should_escape(ord(char), mode))
        for char in text
    ):
        return text
    return "".join(
        chr(byte) if not _go_should_escape(byte, mode) else f"%{byte:02X}" for byte in raw
    )


@dataclass(frozen=True)
class _GoURL:
    scheme: str
    netloc: str
    path: str  # escaped (Go's EscapedPath), or the opaque part
    query: str
    force_query: bool
    fragment: str  # escaped
    opaque: bool = False

    def string(self) -> str:
        """Go's URL.String."""
        out = f"{self.scheme}:" if self.scheme else ""
        if self.opaque:
            out += self.path
        else:
            if (self.scheme or self.netloc) and (self.netloc or self.path):
                out += "//" + self.netloc
            if self.path and not self.path.startswith("/") and self.netloc:
                out += "/"
            if not out and ":" in self.path.split("/", 1)[0]:
                out += "./"
            out += self.path
        if self.force_query or self.query:
            out += "?" + self.query
        if self.fragment:
            out += "#" + self.fragment
        return out


def _go_parse(link: str) -> Optional[_GoURL]:
    """Go's url.Parse, or None where Go refuses the link."""
    if _GO_CONTROL.search(link):
        return None
    try:
        parts = urlsplit(link)
    except ValueError:  # an unclosed IPv6 bracket
        return None
    host = parts.netloc.rpartition("@")[2]
    if host.startswith("["):
        port = host[host.find("]") + 1 :]
    else:
        port = host[host.rfind(":") :] if ":" in host else ""
        if _go_unescape(host, "host") is None:
            return None
    if not _GO_PORT.fullmatch(port):
        return None  # Go refuses a port that is not a number
    rest = link.split("#", 1)[0]
    force_query = rest.endswith("?") and rest.count("?") == 1
    fragment = _go_escaped(parts.fragment, "fragment")
    if fragment is None:
        return None
    if parts.scheme and not parts.netloc and not parts.path.startswith("/"):
        return _GoURL(parts.scheme, "", parts.path, parts.query, force_query, fragment, True)
    if not parts.scheme and not parts.netloc and ":" in parts.path.split("/", 1)[0]:
        return None  # a relative link whose first segment has a colon
    path = _go_escaped(parts.path, "path")
    if path is None:
        return None
    return _GoURL(parts.scheme, parts.netloc, path, parts.query, force_query, fragment)


def _go_resolve_path(base: str, ref: str) -> str:
    """Go's resolvePath: ``ref`` against ``base`` with dot segments removed (RFC 3986)."""
    if not ref:
        full = base
    elif not ref.startswith("/"):
        full = base[: base.rfind("/") + 1] + ref
    else:
        full = ref
    if not full:
        return ""
    out, first, elem = "/", True, ""
    elements = full.split("/")
    for elem in elements:
        if elem == ".":
            first = False
            continue
        if elem == "..":
            cut = out[1:].rfind("/")
            out, first = ("/", True) if cut < 0 else ("/" + out[1:][:cut], first)
            continue
        if not first:
            out += "/"
        out += elem
        first = False
    if elem in (".", ".."):
        out += "/"
    return out[1:] if len(out) > 1 and out[1] == "/" else out


def resolve_upload_url(upload_url: str, endpoint: str) -> str:
    """The upload URL for an endpoint read from a host page, as the legacy path built it.

    ``endpoint`` (absolute, or relative to ``upload_url``) is resolved with
    its dot segments removed and its path escaped; without a query of its
    own it takes ``upload_url``'s. An endpoint, or an upload URL, that Go's
    url.Parse refuses leaves ``upload_url``. (backend/core/http.go
    resolveUploadURL.)
    """
    endpoint = str(endpoint or "").strip()
    base = _go_parse(upload_url)
    ref = _go_parse(endpoint) if endpoint else None
    if base is None or ref is None:
        return upload_url
    if ref.scheme or ref.netloc:
        resolved = _GoURL(
            ref.scheme or base.scheme,
            ref.netloc,
            ref.path if ref.opaque else _go_resolve_path(ref.path, ""),
            ref.query,
            ref.force_query,
            ref.fragment,
            ref.opaque,
        )
    else:
        query, fragment = ref.query, ref.fragment
        if not ref.path and not ref.force_query and not ref.query:
            query = base.query
            fragment = ref.fragment or base.fragment
        resolved = _GoURL(
            base.scheme,
            base.netloc,
            _go_resolve_path(base.path, ref.path),
            query,
            ref.force_query,
            fragment,
        )
    if not resolved.query:
        resolved = dataclasses.replace(resolved, query=base.query)
    return resolved.string()


def split_url_extension(link: str) -> Tuple[str, str]:
    """Split a link into everything before its path's extension, and the extension.

    ``https://h/a/x.jpg?q#f`` -> (``https://h/a/x``, ``.jpg``). The query and
    fragment are dropped; the path is escaped as Go writes it (a valid
    escape such as ``%2F`` is kept, a space becomes ``%20``), and a link Go
    cannot parse comes back whole with no extension.
    """
    link = str(link or "").strip()
    if not link:
        return "", ""
    parts = _go_parse(link)
    if parts is None:
        return link, ""
    stripped = dataclasses.replace(parts, query="", force_query=False, fragment="").string()
    ext = "" if parts.opaque else _path_ext(parts.path)
    if not ext or not stripped.endswith(ext):
        return stripped, ""
    return stripped[: -len(ext)], ext


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


# RE2's \s: no vertical tab, no Unicode spaces.
_RE2_SPACE = "\\t\\n\\f\\r "


@functools.lru_cache(maxsize=256)
def compile_re2_pattern(pattern: str) -> "re.Pattern[str]":
    """Compile a legacy spec's regular expression so it matches what Go's RE2 matched.

    RE2's ``\\d``, ``\\w`` and ``\\b`` are ASCII (``re.ASCII``), and its
    ``\\s`` is ``[\\t\\n\\f\\r ]``: no vertical tab, no NBSP. Remaining
    differences, unused by the host patterns: under ``(?i)`` Python's ASCII
    mode does not fold the Kelvin sign and long s to k and s as RE2 does,
    ``\\S`` inside a class still excludes the vertical tab, ``$`` also
    matches before a final newline, and POSIX classes (``[[:digit:]]``)
    are RE2 only.
    """
    return re.compile(_re2_classes(pattern), re.ASCII)


def _re2_classes(pattern: str) -> str:
    """``pattern`` with ``\\s`` and ``\\S`` spelled out as RE2 means them."""
    out: List[str] = []
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            pair = pattern[index : index + 2]
            if pair == "\\s":
                out.append(_RE2_SPACE if in_class else f"[{_RE2_SPACE}]")
            elif pair == "\\S" and not in_class:
                out.append(f"[^{_RE2_SPACE}]")
            else:
                out.append(pair)
            index += 2
            continue
        if not in_class and char == "[":
            start = index + 1
            if pattern[start : start + 1] == "^":
                start += 1
            if pattern[start : start + 1] == "]":
                start += 1  # a "]" first in a class is literal
            out.append(pattern[index:start])
            index, in_class = start, True
            continue
        if in_class and char == "]":
            in_class = False
        out.append(char)
        index += 1
    return "".join(out)


_SELECTION_ATTRIBUTES = ("value", "content", "action", "href", "src", "data-url")


def html_field(body: str, selector: str) -> str:
    """One value from an HTML page, as the legacy ``extract_fields`` read it.

    ``regex:<pattern>`` returns the first match's first group (else the whole
    match). Otherwise ``selector`` is a CSS selector and the first match gives
    its value, content, action, href, src or data-url attribute (the first
    that is not blank), else its text.

    The element is the one goquery picks on Go's HTML5 parser: nothing inside
    <noscript> counts (with scripting on, its content is raw text), and an
    attribute given twice keeps its first value.
    """
    if not selector:
        return ""
    if selector.startswith("regex:"):
        match = compile_re2_pattern(selector[len("regex:") :]).search(str(body or ""))
        if not match:
            return ""
        value = match.group(1) if match.re.groups >= 1 else match.group(0)
        return (value or "").strip()
    soup = BeautifulSoup(str(body or ""), "html.parser", on_duplicate_attribute="ignore")
    element = next(
        (found for found in soup.select(selector) if found.find_parent("noscript") is None),
        None,
    )
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
