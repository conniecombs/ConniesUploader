# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Match a host's result-page entries to the files of one upload job.

Some hosts answer an upload with a page that lists every image of the
upload session instead of the image just uploaded (Turbo, ImageBam). A
``ResultPageMatcher`` decides which listed entry belongs to which file,
shared by all files of one job and safe to use from several threads. Every
entry goes to at most one file.

This ports backend/core/resolve.go as of fix/v3.2.0 (f13d097), whose tests
are ported in tests/test_result_matcher.py:

- ``filename`` (and ``contains``), best first: the same file name ignoring
  case; then the same name with punctuation ignored (``Scan #1.jpg`` listed
  as ``Scan__1.jpg``); then, only on the last look at the page (or always in
  ``contains`` mode), a listed name that contains the file's name as whole
  words (``4411_beach.jpg`` for ``beach.jpg``). Names are compared in Unicode
  NFC, so macOS (NFD) file names match. An entry that another file of the job
  matches more closely is held back only for a file whose upload finished
  and that is still being resolved, never for one not uploaded yet or
  already finished; a file whose parse has not started yet (it waits in the
  parse pool's queue, where Go resolved every file in its own goroutine)
  holds back only the one entry its first look would take. Files with the
  same name take entries in upload order.
- ``first`` / ``single``: the first entry no other file holds.
- ``upload_order``: each file takes the newest entry after the last one the
  job holds, its own upload. The page also lists images of uploads that
  failed after the host stored them, so the matcher counts every upload that
  reached the host since the last claim and waits until the page lists that
  many new entries; on the last look, fewer means the host kept nothing of
  some failed uploads and the newest is taken; more cannot be told apart and
  the file fails ("cannot tell which result-page entry is this upload's"),
  with later files starting after those entries. This needs the job's files
  uploaded and resolved one at a time: declare
  ``upload_job_options(config) -> {"sequential": True}`` and the upload
  manager sends the next file only after the previous one is resolved.
  Resolve one file at a time (``match``).

The upload manager tells the matcher what happened to each file through the
job's ``SessionState`` (``record_uploaded`` when the upload reached the host:
the host answered, or got the whole body before the upload failed;
``settle`` when the file is finished); plugin code only calls ``match`` (or
``resolve_from_result_page``).
"""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence
from typing import Set, Tuple, Union
from urllib.parse import unquote, urlsplit

from .sidecar import REQUEST_CANCELLED_MSG
from .upload_results import UploadResult, compile_re2_pattern, html_field, request_failure

MODE_FILENAME = "filename"
MODE_CONTAINS = "contains"
MODE_FIRST = "first"
MODE_SINGLE = "single"
MODE_UPLOAD_ORDER = "upload_order"

# Poll schedule of the legacy result-page resolver, in milliseconds.
DEFAULT_POLL_DELAYS_MS = (500, 1000, 2000, 3000, 5000, 5000, 5000, 5000, 5000, 5000)

Pattern = Union[str, "re.Pattern[str]"]


@dataclass(frozen=True)
class ResultEntry:
    """One image a result page lists."""

    image_url: str
    thumb_url: str = ""
    name: str = ""


def _compile(pattern: Pattern) -> "re.Pattern[str]":
    """A pattern given as text matches as the legacy RE2 pattern did (compile_re2_pattern)."""
    return pattern if isinstance(pattern, re.Pattern) else compile_re2_pattern(pattern)


def _group(match: "re.Match[str]", name: str) -> str:
    """A named group's text, else the legacy positional fallback (1 = image, 2 = thumb)."""
    if name in match.re.groupindex:
        return (match.group(name) or "").strip()
    position = {"image_url": 1, "thumb_url": 2}.get(name)
    if position is not None and match.re.groups >= position:
        return (match.group(position) or "").strip()
    return ""


def extract_result_entries(pattern: Pattern, body: str) -> List[ResultEntry]:
    """The page's entries in page order, one per image URL.

    ``pattern`` has the named groups ``image_url``, ``thumb_url`` and
    optionally ``filename`` (or unnamed groups 1 and 2 for image and thumb).
    """
    regex = _compile(pattern)
    entries: List[ResultEntry] = []
    index: Dict[str, int] = {}
    for match in regex.finditer(str(body or "")):
        entry = ResultEntry(
            _group(match, "image_url"), _group(match, "thumb_url"), _group(match, "filename")
        )
        if not entry.image_url:
            continue
        if entry.image_url in index:
            seen = entries[index[entry.image_url]]
            entries[index[entry.image_url]] = ResultEntry(
                seen.image_url, seen.thumb_url or entry.thumb_url, seen.name or entry.name
            )
            continue
        index[entry.image_url] = len(entries)
        entries.append(entry)
    return entries


def extract_thumb_entries(pattern: Pattern, body: str) -> List[ResultEntry]:
    """A separate thumbnail extractor's matches in page order (``thumb_url``, ``filename``)."""
    regex = _compile(pattern)
    thumbs = []
    for match in regex.finditer(str(body or "")):
        thumb = _group(match, "thumb_url")
        if thumb:
            thumbs.append(ResultEntry("", thumb, _group(match, "filename")))
    return thumbs


# --- Names ---------------------------------------------------------------------------

_NO_MATCH, _EXACT, _SIMILAR, _LOOSE = 0, 1, 2, 3


@dataclass(frozen=True)
class _NameForms:
    exact: str
    similar: str


def _name_forms(name: str) -> _NameForms:
    exact = unicodedata.normalize("NFC", str(name).strip().lower())
    words, word = [], []
    for char in exact:
        if char.isalpha() or unicodedata.category(char) == "Nd":
            word.append(char)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return _NameForms(exact, " ".join(words))


def _base_name(path: str) -> str:
    path = str(path or "")
    cut = max(path.rfind("/"), path.rfind("\\"))
    return path[cut + 1 :] if cut >= 0 else path


def _local_name_forms(name: str) -> _NameForms:
    """A local file name; never parsed as a URL ("Scan #2.jpg" is a name)."""
    return _name_forms(_base_name(str(name).strip()))


def _url_path_base(path: str) -> str:
    trimmed = path.rstrip("/")
    if not trimmed:
        return "/" if path else "."
    return trimmed[trimmed.rfind("/") + 1 :]


_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _page_name_forms(value: str) -> _NameForms:
    """A name taken from a result page: a link counts by its last path segment."""
    value = str(value).strip()
    if "://" in value or value.startswith("/"):
        try:
            path = urlsplit(value).path
        except ValueError:
            path = ""
        if path:
            value = _url_path_base(path)
    if not _BAD_ESCAPE.search(value):
        value = unquote(value)
    value = value.lower()
    if value.endswith(".html"):
        value = value[: -len(".html")]
    return _name_forms(value)


def _name_match(page: _NameForms, local: _NameForms) -> int:
    if not page.exact or not local.exact:
        return _NO_MATCH
    if page.exact == local.exact:
        return _EXACT
    if not local.similar:
        return _NO_MATCH
    if page.similar == local.similar:
        return _SIMILAR
    if f" {local.similar} " in f" {page.similar} ":
        return _LOOSE
    return _NO_MATCH


def _entry_match(entry: ResultEntry, local: Optional[_NameForms]) -> int:
    """The best match between an entry (its listed name, else its link) and a file name."""
    if local is None:
        return _NO_MATCH
    best = _NO_MATCH
    for value in (entry.name, entry.image_url):
        if not str(value or "").strip():
            continue
        tier = _name_match(_page_name_forms(value), local)
        if tier != _NO_MATCH and (best == _NO_MATCH or tier < best):
            best = tier
    return best


def expected_file_names(
    files: Iterable[str], file_names: Optional[Mapping[str, str]] = None
) -> Dict[str, str]:
    """Each file mapped to the name the host should list it under (its base name by default)."""
    names = {}
    for fp in files:
        name = str((file_names or {}).get(fp) or "").strip()
        names[fp] = name or _base_name(fp)
    return names


# --- The matcher ---------------------------------------------------------------------


class ResultPageMatcher:
    """Assigns result-page entries to the files of one upload job. Thread-safe."""

    MODES = (MODE_FILENAME, MODE_CONTAINS, MODE_FIRST, MODE_SINGLE, MODE_UPLOAD_ORDER)

    def __init__(
        self,
        files: Sequence[str],
        mode: str = MODE_FILENAME,
        file_names: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.mode = self._normalize_mode(mode)
        self.files: Tuple[str, ...] = tuple(files)
        self._lock = threading.RLock()
        self._names: Dict[str, _NameForms] = {
            fp: _local_name_forms(name)
            for fp, name in expected_file_names(self.files, file_names).items()
        }
        self._uploaded: Dict[str, int] = {}  # file -> position among finished uploads
        self._settled: Set[str] = set()
        self._resolved: Set[str] = set()
        self._looking: Set[str] = set()  # files that looked at the page at least once
        self._claimed: Dict[str, str] = {}  # entry image URL -> file
        self._claimed_thumbs: Dict[str, str] = {}
        # upload_order: attempts that reached the host since the last claim,
        # entries a file that could not be resolved passed over, and why.
        self._sent_since_claim = 0
        self._passed_over: Set[str] = set()
        self._unresolvable: Dict[str, str] = {}

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        mode = str(mode or "").strip().lower()
        return mode or MODE_FILENAME

    @classmethod
    def needs_sequential_uploads(cls, mode: str) -> bool:
        """Whether files matched in ``mode`` must upload and resolve one at a time."""
        return cls._normalize_mode(mode) == MODE_UPLOAD_ORDER

    # Lifecycle notes (the upload manager calls these through SessionState).

    def record_uploaded(self, file_path: str) -> None:
        """``file_path``'s upload reached the host (it answered, or got the whole body).

        The host may have stored the image even if the upload then failed.
        Recording a file again does nothing.
        """
        with self._lock:
            if file_path not in self._names:
                self._names[file_path] = _local_name_forms(file_path)
            if file_path not in self._uploaded:
                self._uploaded[file_path] = len(self._uploaded)
                self._sent_since_claim += 1

    def settle(self, file_path: str) -> None:
        """``file_path`` is finished (Done or Failed) and holds back no entry any more."""
        with self._lock:
            self._settled.add(file_path)

    def claimed_by(self, image_url: str) -> Optional[str]:
        with self._lock:
            return self._claimed.get(image_url)

    def missing_reason(self, file_path: str) -> str:
        """Why the last look gave ``file_path`` no entry."""
        with self._lock:
            return self._unresolvable.get(file_path) or "result page missing 1 link(s)"

    # Matching.

    def match(
        self, file_path: str, entries: Sequence[ResultEntry], final: bool = False
    ) -> Optional[ResultEntry]:
        """The entry for one file, claimed for it, or None if none fits yet.

        ``final`` is the last look at the page: it also accepts loose name
        matches and, in upload_order, does not wait for a lagging page.
        """
        with self._lock:
            self.record_uploaded(file_path)
            return self.assign(entries, [file_path], final).get(file_path)

    def assign(
        self, entries: Sequence[ResultEntry], pending: Sequence[str], final: bool
    ) -> Dict[str, ResultEntry]:
        """Pick and claim an entry for each pending file, in upload order."""
        with self._lock:
            self._looking.update(pending)
            assigned = {}
            for fp in self._by_position(pending):
                entry = self._choose(fp, list(entries), final)
                if entry is None:
                    continue
                self._claimed[entry.image_url] = fp
                self._resolved.add(fp)
                if self.mode == MODE_UPLOAD_ORDER:
                    self._sent_since_claim = 0
                assigned[fp] = entry
            return assigned

    def assign_thumbs(
        self,
        thumbs: Sequence[ResultEntry],
        results: MutableMapping[str, Tuple[str, str]],
        final: bool,
    ) -> None:
        """Fill missing thumbnails in ``results`` (file -> (url, thumb)) from a thumb extractor."""
        with self._lock:
            waiting = self._by_position([fp for fp, pair in results.items() if not pair[1]])
            for thumb in thumbs:
                if not waiting:
                    return
                if self._claimed_thumbs.get(thumb.thumb_url):
                    continue
                pick = -1
                if not self._uses_names():
                    pick = 0
                else:
                    best = _NO_MATCH
                    probe = ResultEntry(thumb.thumb_url, "", thumb.name)
                    for index, fp in enumerate(waiting):
                        tier = _entry_match(probe, self._names.get(fp))
                        if tier == _NO_MATCH or (tier == _LOOSE and not self._allow_loose(final)):
                            continue
                        if best == _NO_MATCH or tier < best:
                            best, pick = tier, index
                if pick < 0:
                    continue
                fp = waiting.pop(pick)
                results[fp] = (results[fp][0], thumb.thumb_url)
                self._claimed_thumbs[thumb.thumb_url] = fp

    # Internals; callers hold the lock.

    def _uses_names(self) -> bool:
        return self.mode not in (MODE_FIRST, MODE_SINGLE, MODE_UPLOAD_ORDER)

    def _allow_loose(self, final: bool) -> bool:
        return final or self.mode == MODE_CONTAINS

    def _position(self, fp: str) -> int:
        return self._uploaded.get(fp, 1 << 62)

    def _by_position(self, files: Iterable[str]) -> List[str]:
        return sorted(files, key=self._position)

    def _holds(self, fp: str) -> bool:
        """Whether ``fp`` finished uploading and is still being resolved."""
        return fp in self._uploaded and fp not in self._settled and fp not in self._resolved

    def _choose(self, fp: str, entries: List[ResultEntry], final: bool) -> Optional[ResultEntry]:
        if self.mode == MODE_UPLOAD_ORDER:
            return self._choose_by_upload_order(fp, entries, final)
        if self.mode in (MODE_FIRST, MODE_SINGLE):
            return next((entry for entry in entries if entry.image_url not in self._claimed), None)
        return self._choose_by_name(fp, entries, final)

    def _choose_by_upload_order(
        self, fp: str, entries: List[ResultEntry], final: bool
    ) -> Optional[ResultEntry]:
        """The entry of the upload that just finished (resolve.go chooseLatestUpload).

        The page lists the session's images in upload order, including those of
        attempts that failed after the host stored them, so the entries after
        the last one the job holds (or passed over) belong to the attempts that
        reached the host since; this file's own upload is the newest of them.
        Until the page lists as many new entries as attempts, it may not list
        this upload yet. On the last look, fewer mean failed attempts the host
        did not keep, and the newest is taken; more cannot be told apart, so
        the file fails and later files start after those entries.
        """
        start = 0
        for index, entry in enumerate(entries):
            if entry.image_url in self._claimed or entry.image_url in self._passed_over:
                start = index + 1
        fresh = entries[start:]
        sent = max(self._sent_since_claim, 1)  # this file's own upload reached the host
        if fresh and (len(fresh) == sent or (len(fresh) < sent and final)):
            return fresh[-1]
        if fresh and len(fresh) > sent and final:
            self._unresolvable[fp] = (
                "cannot tell which result-page entry is this upload's: the page lists "
                f"{len(fresh)} new entries, but only {sent} upload(s) reached the host"
            )
            # The job's next file uploads after this look: none of these is its.
            self._passed_over.update(entry.image_url for entry in fresh)
            self._sent_since_claim = 0
        return None

    def _choose_by_name(
        self, fp: str, entries: List[ResultEntry], final: bool
    ) -> Optional[ResultEntry]:
        local = self._names.get(fp)
        if local is None:
            return None
        first_picks: Dict[str, Optional[ResultEntry]] = {}
        best = _NO_MATCH
        candidates: List[ResultEntry] = []
        for entry in entries:
            if entry.image_url in self._claimed:
                continue
            tier = _entry_match(entry, local)
            if tier == _NO_MATCH or (tier == _LOOSE and not self._allow_loose(final)):
                continue
            if self._reserved_for_another(entry, fp, tier, entries, first_picks):
                continue
            if best == _NO_MATCH or tier < best:
                best, candidates = tier, [entry]
            elif tier == best:
                candidates.append(entry)
        if not candidates:
            return None
        # Files with the same name that finished uploading earlier take the
        # earlier entries, so the host's listing order decides between them.
        ahead = self._same_name_files_ahead(fp, candidates[0], best)
        if ahead < len(candidates):
            return candidates[ahead]
        return candidates[-1] if final else None

    def _reserved_for_another(
        self,
        entry: ResultEntry,
        fp: str,
        tier: int,
        entries: List[ResultEntry],
        first_picks: Dict[str, Optional[ResultEntry]],
    ) -> bool:
        """Whether another file still being resolved matches ``entry`` more closely.

        A file that has looked at the page holds back every entry it matches
        more closely than ``fp``, as in Go. A file whose upload finished but
        whose parse has not started (it waits in the parse pool's queue)
        holds back only the entry its first look would take: in Go it would
        be resolving in its own goroutine and take that entry at once, so a
        pool busy with other files never starves ``fp`` of the rest.
        """
        for other, forms in self._names.items():
            if other == fp or not self._holds(other):
                continue
            other_tier = _entry_match(entry, forms)
            if other_tier == _NO_MATCH or other_tier >= tier:
                continue
            if other in self._looking:
                return True
            if other not in first_picks:
                first_picks[other] = self._first_pick(other, entries)
            pick = first_picks[other]
            if pick is not None and pick.image_url == entry.image_url:
                return True
        return False

    def _first_pick(self, fp: str, entries: List[ResultEntry]) -> Optional[ResultEntry]:
        """The entry ``fp``'s first look at ``entries`` would take, others' reservations aside."""
        local = self._names.get(fp)
        best = _NO_MATCH
        candidates: List[ResultEntry] = []
        for entry in entries:
            if entry.image_url in self._claimed:
                continue
            tier = _entry_match(entry, local)
            if tier == _NO_MATCH or (tier == _LOOSE and not self._allow_loose(False)):
                continue
            if best == _NO_MATCH or tier < best:
                best, candidates = tier, [entry]
            elif tier == best:
                candidates.append(entry)
        if not candidates:
            return None
        ahead = self._same_name_files_ahead(fp, candidates[0], best)
        return candidates[ahead] if ahead < len(candidates) else None

    def _same_name_files_ahead(self, fp: str, entry: ResultEntry, tier: int) -> int:
        mine = self._position(fp)
        return sum(
            1
            for other, forms in self._names.items()
            if other != fp
            and self._holds(other)
            and self._position(other) < mine
            and _entry_match(entry, forms) == tier
        )


# --- Polling a result page -----------------------------------------------------------


def resolve_from_result_page(
    transport: Any,
    result_url: str,
    file_path: str,
    matcher: ResultPageMatcher,
    *,
    link_extractor: Pattern,
    poll_delays_ms: Sequence[int] = DEFAULT_POLL_DELAYS_MS,
    thumb_extractor: Optional[Pattern] = None,
    gallery_extractor: Union[str, Callable[[str], str], None] = None,
    secrets: Iterable[str] = (),
) -> UploadResult:
    """Poll ``result_url`` on the job's transport until ``file_path`` is listed.

    The page is read once, then again after each delay of ``poll_delays_ms``;
    the last look also accepts loose matches. Each look is one request
    without the sidecar's retries, as in the legacy resolver: a look that
    fails (a 503, a timeout) waits for the next one of the schedule. ``gallery_extractor`` (a CSS
    selector, ``regex:<pattern>``, or a function of the page) gives the
    result's gallery_url. A file without both an image and a thumbnail link
    by the last look fails with the reason.
    """
    secrets = list(secrets)
    matcher.record_uploaded(file_path)
    attempts = 1 + len(poll_delays_ms)
    url = thumb = gallery_url = ""
    last_error = ""
    for attempt in range(attempts):
        if attempt:
            if not transport.pause(poll_delays_ms[attempt - 1] / 1000.0):
                return UploadResult.failed(REQUEST_CANCELLED_MSG)
        response = transport.get(result_url, retry=False)
        if getattr(response, "status", "") == "cancelled":
            return UploadResult.failed(REQUEST_CANCELLED_MSG)
        if not response.ok:
            last_error = request_failure("result page", response, secrets)
            continue
        body = response.body
        if gallery_extractor and not gallery_url:
            found = (
                gallery_extractor(body)
                if callable(gallery_extractor)
                else html_field(body, gallery_extractor)
            )
            gallery_url = str(found or "").strip()
        final = attempt == attempts - 1
        entry = matcher.match(file_path, extract_result_entries(link_extractor, body), final)
        if entry is None:
            last_error = matcher.missing_reason(file_path)
            continue
        url, thumb = entry.image_url, entry.thumb_url
        if not thumb and thumb_extractor is not None:
            results = {file_path: (url, thumb)}
            matcher.assign_thumbs(extract_thumb_entries(thumb_extractor, body), results, final)
            thumb = results[file_path][1]
        break
    if url and thumb:
        return UploadResult(url=url, thumb=thumb, gallery_url=gallery_url)
    if url:
        return UploadResult.failed(
            "resolve upload result: result page did not contain image and thumbnail links"
        )
    return UploadResult.failed(
        f"resolve upload result: {last_error or 'result page missing 1 link(s)'}"
    )
