# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""ResultPageMatcher: result-page entries matched to a job's files.

The tests port backend/core/batch_resolve_test.go, resolve_upload_order_test.go,
resolve_reservation_test.go, resolve_unicode_test.go and the result-page tests
of backend/uploader_http_runner_test.go (fix/v3.2.0 at f13d097). Where an upload
in Go would be retried after a 5xx, the Python path never retries an upload, so
the file fails instead; the expectations say so.
"""

import threading
import unicodedata
from urllib.parse import quote

import pytest

from modules import result_matcher
from modules.result_matcher import (
    ResultEntry,
    ResultPageMatcher,
    extract_result_entries,
    extract_thumb_entries,
    resolve_from_result_page,
)
from modules.transport import TransportResponse

TURBO_LIKE = (
    r"(?is)\[url=(?P<image_url>https?://[^\]]+?/p/[0-9]+/(?P<filename>[^/\]]+?)\.html)\]\s*"
    r"\[img\](?P<thumb_url>https?://[^\]]+?)\[/img\]\s*\[/url\]"
)
VIEW_LINKS = (
    r"\[URL=(?P<image_url>https://img\.example/view/[^\]]+)\]"
    r"\[IMG\](?P<thumb_url>https://thumbs\.example/[^\]]+)\[/IMG\]\[/URL\]"
)


def turbo_page(entries):
    lines = [
        f"[URL=https://img.example/p/{i}/{name}.html][IMG]https://thumbs.example/t/{i}_{name}[/IMG][/URL]"
        for i, name in entries
    ]
    return "<textarea>\n" + "\n".join(lines) + "\n</textarea>"


def view_page(ids):
    return " ".join(
        f"[URL=https://img.example/view/{i}][IMG]https://thumbs.example/{i}_t.jpg[/IMG][/URL]"
        for i in ids
    )


def entry_id(entry):
    return int(entry.image_url.split("/p/")[1].split("/")[0])


def batch_resolve(files, pages, mode="filename"):
    """Go's ExecuteBatchResolve: files finished in the order given; one poll per page."""
    matcher = ResultPageMatcher(files, mode=mode)
    for fp in files:
        matcher.record_uploaded(fp)
    results, pending = {}, list(files)
    for attempt, page in enumerate(pages):
        final = attempt == len(pages) - 1
        entries = extract_result_entries(TURBO_LIKE if mode != "upload_order" else VIEW_LINKS, page)
        for fp, entry in matcher.assign(entries, pending, final).items():
            results[fp] = entry
            pending.remove(fp)
    return results


# --- Ported from resolve.go's tests --------------------------------------------------


@pytest.mark.parametrize(
    ("files", "page", "want"),
    [
        pytest.param(
            ["/in/cover.jpg", "/in/back_cover.jpg"],
            [(1, "back_cover.jpg"), (2, "cover.jpg")],
            {"/in/cover.jpg": 2, "/in/back_cover.jpg": 1},
            id="cover does not take back_cover",
        ),
        pytest.param(
            ["/in/2.jpg", "/in/12.jpg"],
            [(1, "12.jpg"), (2, "2.jpg")],
            {"/in/2.jpg": 2, "/in/12.jpg": 1},
            id="2.jpg does not take 12.jpg",
        ),
        pytest.param(
            ["/in/Scan #1.jpg", "/in/Scan #2.jpg"],
            [(1, "Scan__2.jpg"), (2, "Scan__1.jpg")],
            {"/in/Scan #1.jpg": 2, "/in/Scan #2.jpg": 1},
            id="local names are not parsed as URLs",
        ),
        pytest.param(
            ["/in/Scan #1.jpg", "/in/Scan #2.jpg"],
            [(1, quote("Scan #2.jpg")), (2, quote("Scan #1.jpg"))],
            {"/in/Scan #1.jpg": 2, "/in/Scan #2.jpg": 1},
            id="percent-encoded page names",
        ),
        pytest.param(
            ["/in/imx api.jpg", "/in/imx.jpg"],
            [(1, "imx.jpg"), (2, "imx_api.jpg")],
            {"/in/imx api.jpg": 2, "/in/imx.jpg": 1},
            id="host replaced spaces with underscores",
        ),
        pytest.param(
            ["/in/setA/01.jpg", "/in/setB/01.jpg"],
            [(1, "01.jpg"), (2, "01.jpg")],
            {"/in/setA/01.jpg": 1, "/in/setB/01.jpg": 2},
            id="same base name in two folders",
        ),
        pytest.param(
            ["/in/beach.jpg"],
            [(1, "4411_beach.jpg")],
            {"/in/beach.jpg": 1},
            id="host prefix falls back to a looser match",
        ),
    ],
)
def test_exact_file_names_win(files, page, want):
    results = batch_resolve(files, [turbo_page(page), turbo_page(page)])
    assert {fp: entry_id(entry) for fp, entry in results.items()} == want


def test_filename_mode_waits_for_the_exact_entry_before_a_loose_match():
    pages = [turbo_page([(1, "back_cover.jpg")])] + [
        turbo_page([(1, "back_cover.jpg"), (2, "cover.jpg")])
    ] * 2
    results = batch_resolve(["/in/cover.jpg"], pages)
    assert entry_id(results["/in/cover.jpg"]) == 2


def test_single_mode_never_gives_one_entry_to_two_files():
    page = view_page(["A"])
    matcher = ResultPageMatcher(["/in/a.jpg", "/in/b.jpg"], mode="single")
    for fp in matcher.files:
        matcher.record_uploaded(fp)
    entries = extract_result_entries(VIEW_LINKS, page)
    assigned = matcher.assign(entries, list(matcher.files), final=True)
    assert len(assigned) == 1


class TurboLikeHost:
    """Lists every upload of a shared session, names sanitized like Turbo's."""

    def __init__(self):
        self.lock = threading.Lock()
        self.uploads = []  # (id, page name, file)

    def upload(self, fp):
        with self.lock:
            image_id = 1000 + len(self.uploads)
            name = fp.rsplit("/", 1)[-1].replace(" ", "_")
            self.uploads.append((image_id, name, fp))
            return image_id

    def page(self):
        with self.lock:
            return turbo_page([(image_id, name) for image_id, name, _ in self.uploads])

    def file_of(self, entry):
        with self.lock:
            return next(fp for image_id, _, fp in self.uploads if image_id == entry_id(entry))


def test_per_file_resolve_gives_each_file_of_a_job_its_own_entry():
    files = [
        "/in/back_cover.jpg",
        "/in/cover.jpg",
        "/in/12.jpg",
        "/in/2.jpg",
        "/in/setA/01.jpg",
        "/in/setB/01.jpg",
        "/in/Scan #1.jpg",
        "/in/Scan #2.jpg",
    ]
    host = TurboLikeHost()
    matcher = ResultPageMatcher(files)
    for fp in files:
        host.upload(fp)
        entry = matcher.match(fp, extract_result_entries(TURBO_LIKE, host.page()))
        assert entry is not None, fp
        assert host.file_of(entry) == fp
        matcher.settle(fp)


def test_concurrent_per_file_resolve_never_shares_an_entry():
    files = [
        "/a/01.jpg",
        "/b/01.jpg",
        "/c/01.jpg",
        "/d/01.jpg",
        "/in/cover.jpg",
        "/in/back_cover.jpg",
    ]
    host = TurboLikeHost()
    matcher = ResultPageMatcher(files)
    links = {}
    barrier = threading.Barrier(len(files))

    def run(fp):
        host.upload(fp)
        matcher.record_uploaded(fp)
        barrier.wait()
        for attempt in range(3):
            entry = matcher.match(fp, extract_result_entries(TURBO_LIKE, host.page()), attempt == 2)
            if entry:
                links[fp] = entry
                break
        matcher.settle(fp)

    threads = [threading.Thread(target=run, args=(fp,)) for fp in files]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert len(links) == len(files)
    assert len({entry.image_url for entry in links.values()}) == len(files)
    for fp, entry in links.items():
        if not fp.endswith("01.jpg"):
            assert host.file_of(entry) == fp


@pytest.mark.parametrize("session_per_upload", [False, True])
def test_upload_order_gives_each_upload_the_entry_it_added(session_per_upload):
    files = ["/in/cover.jpg", "/in/a.jpg", "/in/b.jpg", "/in/c.jpg"]
    matcher = ResultPageMatcher(files, mode="upload_order")
    shared = []
    for n, fp in enumerate(files):
        image_id = f"ME{n:03d}"
        matcher.record_uploaded(fp)
        shared.append(image_id)
        page = view_page([image_id] if session_per_upload else shared)
        entry = matcher.match(fp, extract_result_entries(VIEW_LINKS, page))
        assert entry is not None and entry.image_url.endswith(image_id), fp
        assert image_id in entry.thumb_url
        matcher.settle(fp)


def test_turbo_result_pages():
    page = """<input id="imgCodeGG" value="https://www.turboimagehost.com/album/394761/miscellaneous">
        <textarea id="imgCodeURF">
            [URL=https://www.turboimagehost.com/p/123/other.jpg.html][IMG]https://s8d8.turboimg.net/t1/123_other.jpg[/IMG][/URL]
            [URL=https://www.turboimagehost.com/p/124/turbo-upload.jpg.html][IMG]https://s8d8.turboimg.net/t1/124_turbo-upload.jpg[/IMG][/URL]
        </textarea>"""
    matcher = ResultPageMatcher(["/tmp/turbo-upload.jpg"])
    entry = matcher.match("/tmp/turbo-upload.jpg", extract_result_entries(TURBO_LIKE, page))
    assert entry.image_url == "https://www.turboimagehost.com/p/124/turbo-upload.jpg.html"
    assert entry.thumb_url == "https://s8d8.turboimg.net/t1/124_turbo-upload.jpg"

    sanitized = (
        "[URL=https://www.turboimagehost.com/p/123691283/imx_api.jpg.html]"
        "[IMG]https://s8d9.turboimg.net/t1/123691283_imx_api.jpg[/IMG][/URL]"
    )
    matcher = ResultPageMatcher(["/tmp/imx api.jpg"])
    entry = matcher.match("/tmp/imx api.jpg", extract_result_entries(TURBO_LIKE, sanitized))
    assert entry.image_url == "https://www.turboimagehost.com/p/123691283/imx_api.jpg.html"


def test_extract_entries_keeps_page_order_and_merges_duplicates():
    page = (
        "[URL=https://img.example/view/A][IMG][/IMG][/URL]"
        "[URL=https://img.example/view/B][IMG]https://thumbs.example/B[/IMG][/URL]"
        "[URL=https://img.example/view/A][IMG]https://thumbs.example/A[/IMG][/URL]"
    )
    pattern = r"\[URL=(https://img\.example/view/[^\]]+)\]\[IMG\]([^\[]*)\[/IMG\]"
    assert extract_result_entries(pattern, page) == [
        ResultEntry("https://img.example/view/A", "https://thumbs.example/A", ""),
        ResultEntry("https://img.example/view/B", "https://thumbs.example/B", ""),
    ]
    thumbs = extract_thumb_entries(r"(?P<thumb_url>https://thumbs\.example/\w+)", page)
    assert [thumb.thumb_url for thumb in thumbs] == [
        "https://thumbs.example/B",
        "https://thumbs.example/A",
    ]


def test_separate_thumbnail_extractor_fills_missing_thumbs_by_name():
    matcher = ResultPageMatcher(["/in/a.jpg", "/in/b.jpg"])
    for fp in matcher.files:
        matcher.record_uploaded(fp)
    results = {"/in/a.jpg": ("https://h/v/a", ""), "/in/b.jpg": ("https://h/v/b", "")}
    thumbs = [
        ResultEntry("", "https://t/b.jpg", "b.jpg"),
        ResultEntry("", "https://t/a.jpg", "a.jpg"),
    ]
    matcher.assign_thumbs(thumbs, results, final=False)
    assert results == {
        "/in/a.jpg": ("https://h/v/a", "https://t/a.jpg"),
        "/in/b.jpg": ("https://h/v/b", "https://t/b.jpg"),
    }


def test_needs_sequential_uploads():
    assert ResultPageMatcher.needs_sequential_uploads("upload_order") is True
    for mode in ("", "filename", "contains", "single", "first"):
        assert ResultPageMatcher.needs_sequential_uploads(mode) is False


# --- upload_order after each upload, holding back, NFC --------------------------------


def test_upload_order_skips_entries_left_by_failed_uploads():
    # The host stored b.jpg's upload but the upload failed (lost answer, 5xx
    # after the body, or no link): its entry must never shift later files.
    files = ["/in/a.jpg", "/in/b.jpg", "/in/c.jpg", "/in/d.jpg"]
    matcher = ResultPageMatcher(files, mode="upload_order")

    matcher.record_uploaded("/in/a.jpg")
    a = matcher.match("/in/a.jpg", extract_result_entries(VIEW_LINKS, view_page(["A"])))
    matcher.settle("/in/a.jpg")
    matcher.record_uploaded("/in/b.jpg")  # body sent, then the upload failed
    matcher.settle("/in/b.jpg")
    matcher.record_uploaded("/in/c.jpg")
    c = matcher.match("/in/c.jpg", extract_result_entries(VIEW_LINKS, view_page(["A", "B", "C"])))
    matcher.settle("/in/c.jpg")
    matcher.record_uploaded("/in/d.jpg")
    d = matcher.match(
        "/in/d.jpg", extract_result_entries(VIEW_LINKS, view_page(["A", "B", "C", "D"]))
    )

    assert [entry.image_url[-1] for entry in (a, c, d)] == ["A", "C", "D"]


def test_upload_order_waits_while_the_page_lags_behind_a_failed_upload():
    files = ["/in/a.jpg", "/in/b.jpg", "/in/c.jpg"]
    matcher = ResultPageMatcher(files, mode="upload_order")
    matcher.record_uploaded("/in/a.jpg")
    matcher.match("/in/a.jpg", extract_result_entries(VIEW_LINKS, view_page(["A"])))
    matcher.settle("/in/a.jpg")
    matcher.record_uploaded("/in/b.jpg")
    matcher.settle("/in/b.jpg")  # failed after its body was sent; the host may list it
    matcher.record_uploaded("/in/c.jpg")

    lagging = extract_result_entries(VIEW_LINKS, view_page(["A", "B"]))
    assert matcher.match("/in/c.jpg", lagging) is None, "B may be the failed upload's entry"
    caught_up = extract_result_entries(VIEW_LINKS, view_page(["A", "B", "C"]))
    assert matcher.match("/in/c.jpg", caught_up).image_url.endswith("/C")


def test_upload_order_failed_upload_the_host_did_not_store_does_not_block_on_the_last_look():
    files = ["/in/a.jpg", "/in/b.jpg", "/in/c.jpg"]
    matcher = ResultPageMatcher(files, mode="upload_order")
    matcher.record_uploaded("/in/a.jpg")
    matcher.match("/in/a.jpg", extract_result_entries(VIEW_LINKS, view_page(["A"])))
    matcher.settle("/in/a.jpg")
    matcher.record_uploaded("/in/b.jpg")
    matcher.settle("/in/b.jpg")  # rejected; the host kept nothing
    matcher.record_uploaded("/in/c.jpg")
    page = extract_result_entries(VIEW_LINKS, view_page(["A", "C"]))
    assert matcher.match("/in/c.jpg", page, final=False) is None
    assert matcher.match("/in/c.jpg", page, final=True).image_url.endswith("/C")


def test_upload_order_never_reuses_an_entry_and_never_gives_an_older_one():
    matcher = ResultPageMatcher(["/in/a.jpg", "/in/b.jpg"], mode="upload_order")
    matcher.record_uploaded("/in/a.jpg")
    matcher.match("/in/a.jpg", extract_result_entries(VIEW_LINKS, view_page(["A"])))
    matcher.settle("/in/a.jpg")
    matcher.record_uploaded("/in/b.jpg")
    # The page still lists only a.jpg's image: b.jpg must wait, not take it.
    assert (
        matcher.match("/in/b.jpg", extract_result_entries(VIEW_LINKS, view_page(["A"])), True)
        is None
    )


def test_reservation_only_holds_entries_for_files_already_uploaded():
    # "Scan 1.jpg" uploads first; the host lists it as Scan_1.jpg, which is an
    # exact name for the job's other file, not uploaded yet.
    files = ["/in/Scan 1.jpg", "/in/x/Scan_1.jpg"]
    matcher = ResultPageMatcher(files)
    matcher.record_uploaded("/in/Scan 1.jpg")
    first = matcher.match(
        "/in/Scan 1.jpg", extract_result_entries(TURBO_LIKE, turbo_page([(1, "Scan_1.jpg")]))
    )
    assert first is not None and entry_id(first) == 1
    matcher.settle("/in/Scan 1.jpg")

    matcher.record_uploaded("/in/x/Scan_1.jpg")
    second = matcher.match(
        "/in/x/Scan_1.jpg",
        extract_result_entries(TURBO_LIKE, turbo_page([(1, "Scan_1.jpg"), (2, "Scan_1.jpg")])),
    )
    assert entry_id(second) == 2


def test_an_uploaded_file_still_resolving_keeps_its_closer_entry():
    files = ["/in/Scan 1.jpg", "/in/x/Scan_1.jpg"]
    matcher = ResultPageMatcher(files)
    matcher.record_uploaded("/in/x/Scan_1.jpg")  # uploaded, resolving
    matcher.record_uploaded("/in/Scan 1.jpg")
    page = extract_result_entries(TURBO_LIKE, turbo_page([(7, "Scan_1.jpg")]))
    assert matcher.match("/in/Scan 1.jpg", page, final=False) is None


def test_a_settled_file_releases_its_reservations():
    files = ["/in/Scan 1.jpg", "/in/x/Scan_1.jpg"]
    matcher = ResultPageMatcher(files)
    matcher.record_uploaded("/in/x/Scan_1.jpg")
    matcher.settle("/in/x/Scan_1.jpg")  # its upload failed
    matcher.record_uploaded("/in/Scan 1.jpg")
    page = extract_result_entries(TURBO_LIKE, turbo_page([(7, "Scan_1.jpg")]))
    assert entry_id(matcher.match("/in/Scan 1.jpg", page)) == 7


def test_equal_matches_go_by_upload_order():
    files = ["/in/setB/01.jpg", "/in/setA/01.jpg"]
    matcher = ResultPageMatcher(files)
    matcher.record_uploaded("/in/setA/01.jpg")
    matcher.record_uploaded("/in/setB/01.jpg")
    entries = extract_result_entries(TURBO_LIKE, turbo_page([(1, "01.jpg"), (2, "01.jpg")]))
    assert entry_id(matcher.match("/in/setB/01.jpg", entries)) == 2
    assert entry_id(matcher.match("/in/setA/01.jpg", entries)) == 1


class LossySessionHost:
    """resolve_upload_order_test.go's lossySessionHost, driven through the Python path.

    One shared session lists every stored image in upload order. misbehave maps
    the 1-based upload number to: "drop" (stored, answer lost: body sent),
    "502" (stored, then 502), "nolink" (stored, 200 without a link), "refuse"
    (403 without storing). lateListing hides a good upload's image from the
    first look at the page after it.
    """

    def __init__(self, misbehave=None, late_listing=False):
        self.misbehave = misbehave or {}
        self.late_listing = late_listing
        self.session = []
        self.contents = {}
        self.uploads = 0

    def upload(self, fp, matcher):
        """Upload fp; return the transport pages to resolve it with, or None if it failed."""
        self.uploads += 1
        mode = self.misbehave.get(self.uploads, "")
        # Every one of these attempts reached the host: the upload manager
        # records a raw result, or a Failed status with body_sent.
        matcher.record_uploaded(fp)
        if mode == "refuse":
            matcher.settle(fp)
            return None
        image_id = f"ME{len(self.contents) + 1:03d}"
        self.session.append(image_id)
        self.contents[image_id] = fp
        if mode:
            matcher.settle(fp)
            return None
        full = view_page(self.session)
        if self.late_listing:
            return [view_page([i for i in self.session if i != image_id]), full]
        return [full]


def resolve_lossy(host, files):
    matcher = ResultPageMatcher(files, mode="upload_order")
    got = []
    for fp in files:
        pages = host.upload(fp, matcher)
        if pages is None:
            got.append("")
            continue
        result = resolve_from_result_page(
            PageTransport(pages),
            "https://img.example/complete",
            fp,
            matcher,
            link_extractor=VIEW_LINKS,
            poll_delays_ms=[5, 5],
        )
        matcher.settle(fp)
        if not result.ok:
            got.append("error: " + result.error)
            continue
        image_id = result.url.rsplit("/", 1)[1]
        assert host.contents[image_id] == fp, f"{fp} got another file's image {image_id}"
        got.append(image_id)
    return got


@pytest.mark.parametrize(
    ("misbehave", "late", "want"),
    [
        pytest.param({1: "drop"}, False, ["", "ME002", "ME003"], id="drop"),
        # Go retries the 502 (the same file then gets ME002); the Python path
        # never re-sends an upload, so that file fails.
        pytest.param({1: "502"}, False, ["", "ME002", "ME003"], id="502"),
        pytest.param({1: "nolink"}, False, ["", "ME002", "ME003"], id="nolink"),
        pytest.param({1: "refuse"}, False, ["", "ME001", "ME002"], id="refused without storing"),
        pytest.param({1: "drop"}, True, ["", "ME002", "ME003"], id="drop, listed late"),
        pytest.param({1: "502"}, True, ["", "ME002", "ME003"], id="502, listed late"),
        pytest.param({2: "drop", 3: "502"}, False, ["ME001", "", ""], id="two failures in a row"),
        pytest.param({2: "drop"}, False, ["ME001", "", "ME003"], id="failure in the middle"),
    ],
)
def test_upload_order_gives_each_file_its_own_last_upload(misbehave, late, want):
    files = ["/in/a.jpg", "/in/b.jpg", "/in/c.jpg"]
    assert resolve_lossy(LossySessionHost(misbehave, late), files) == want


def test_upload_order_fails_a_file_whose_entry_is_ambiguous():
    host = LossySessionHost()
    host.session = ["XX001"]  # an image the job did not upload
    host.contents["XX001"] = "someone else's image"

    got = resolve_lossy(host, ["/in/a.jpg", "/in/b.jpg", "/in/c.jpg"])

    assert got[0] == (
        "error: resolve upload result: cannot tell which result-page entry is this "
        "upload's: the page lists 2 new entries, but only 1 upload(s) reached the host"
    )
    # resolve_lossy also checks that each id is that file's own image.
    assert got[1:] == ["ME003", "ME004"]


def test_upload_order_waits_for_as_many_new_entries_as_attempts_reached_the_host():
    files = ["/in/a.jpg", "/in/b.jpg"]
    matcher = ResultPageMatcher(files, mode="upload_order")
    matcher.record_uploaded("/in/a.jpg")
    matcher.settle("/in/a.jpg")  # failed after reaching the host
    matcher.record_uploaded("/in/b.jpg")
    one_new = extract_result_entries(VIEW_LINKS, view_page(["A"]))
    assert matcher.match("/in/b.jpg", one_new) is None
    # More new entries than attempts: wait, then fail on the last look.
    three_new = extract_result_entries(VIEW_LINKS, view_page(["A", "B", "C"]))
    assert matcher.match("/in/b.jpg", three_new) is None
    assert matcher.match("/in/b.jpg", three_new, final=True) is None
    assert "cannot tell which result-page entry" in matcher.missing_reason("/in/b.jpg")


def test_name_match_holds_entries_only_for_finished_uploads():
    # resolve_reservation_test.go: "Scan 1.jpg" uploads first and is listed as
    # Scan_1.jpg, an exact match for the job's other file, not uploaded yet.
    host = TurboLikeHost()
    files = ["/in/Scan 1.jpg", "/in/x/Scan_1.jpg"]
    matcher = ResultPageMatcher(files)
    for fp in files:
        host.upload(fp)
        matcher.record_uploaded(fp)
        entry = matcher.match(fp, extract_result_entries(TURBO_LIKE, host.page()), final=True)
        assert entry is not None and host.file_of(entry) == fp
        matcher.settle(fp)


def test_name_match_ignores_files_whose_upload_failed():
    files = ["/in/Scan 1.jpg", "/in/x/Scan_1.jpg"]
    host = TurboLikeHost()
    matcher = ResultPageMatcher(files)
    matcher.record_uploaded("/in/x/Scan_1.jpg")  # the host refused it
    matcher.settle("/in/x/Scan_1.jpg")
    host.upload("/in/Scan 1.jpg")
    entry = matcher.match("/in/Scan 1.jpg", extract_result_entries(TURBO_LIKE, host.page()))
    assert host.file_of(entry) == "/in/Scan 1.jpg"


def test_name_match_holds_entries_for_finished_unclaimed_files():
    def entry(image_id, name):
        return ResultEntry(
            f"https://img.example/p/{image_id}/{name}.html", f"https://thumbs.example/{image_id}"
        )

    matcher = ResultPageMatcher(["/in/Scan 1.jpg", "/x/Scan_1.jpg"])
    matcher.record_uploaded("/x/Scan_1.jpg")
    matcher.record_uploaded("/in/Scan 1.jpg")
    assert matcher.assign([entry("1", "Scan_1.jpg")], ["/in/Scan 1.jpg"], final=True) == {}

    same = ResultPageMatcher(["/a/01.jpg", "/b/01.jpg", "/c/01.jpg"])
    same.record_uploaded("/b/01.jpg")
    same.record_uploaded("/a/01.jpg")
    entries = [entry("1", "01.jpg"), entry("2", "01.jpg")]
    assert same.assign(entries, ["/a/01.jpg"], False)["/a/01.jpg"] == entries[1]
    assert same.assign(entries, ["/b/01.jpg"], False)["/b/01.jpg"] == entries[0]


@pytest.mark.parametrize(
    ("local", "page", "tier"),
    [
        ("café.jpg", "café.jpg", result_matcher._EXACT),
        (unicodedata.normalize("NFD", "café.jpg"), "café.jpg", result_matcher._EXACT),
        (unicodedata.normalize("NFD", "/in/Café 1.jpg"), "café_1.jpg", result_matcher._SIMILAR),
        (
            unicodedata.normalize("NFD", "café.jpg"),
            "https://img.example/p/1/caf%C3%A9.jpg.html",
            result_matcher._EXACT,
        ),
    ],
)
def test_nfd_local_names_match_nfc_page_names(local, page, tier):
    # resolve_unicode_test.go
    got = result_matcher._name_match(
        result_matcher._page_name_forms(page), result_matcher._local_name_forms(local)
    )
    assert got == tier


def test_names_are_compared_in_unicode_nfc():
    local = "/in/" + unicodedata.normalize("NFD", "Café.jpg")  # macOS file names
    page_name = unicodedata.normalize("NFC", "Café.jpg")
    matcher = ResultPageMatcher([local])
    entry = matcher.match(local, extract_result_entries(TURBO_LIKE, turbo_page([(3, page_name)])))
    assert entry is not None and entry_id(entry) == 3


# --- Polling a result page -----------------------------------------------------------


class PageTransport:
    def __init__(self, pages, cancel_after=None):
        self.pages = list(pages)
        self.gets = []
        self.retries = []
        self.pauses = []
        self.cancel_after = cancel_after

    def get(self, url, *, retry=True, **_):
        self.gets.append(url)
        self.retries.append(retry)
        page = self.pages[min(len(self.gets), len(self.pages)) - 1]
        if isinstance(page, int):
            return TransportResponse(
                False, "failed", "", 0, url, {}, {}, f"HTTP {page}: <p>gone sess-secret-1</p>"
            )
        return TransportResponse(True, "success", page, 200, url, {}, {})

    def pause(self, seconds):
        self.pauses.append(seconds)
        return self.cancel_after is None or len(self.pauses) < self.cancel_after


def test_resolve_from_result_page_polls_until_the_file_is_listed():
    gallery = '<a id="gallery-name" href="https://h/g/9">G</a>'
    transport = PageTransport(
        [
            404,
            gallery + turbo_page([(1, "other.jpg")]),
            gallery + turbo_page([(1, "other.jpg"), (2, "a.jpg")]),
        ]
    )
    matcher = ResultPageMatcher(["/in/a.jpg", "/in/other.jpg"])
    result = resolve_from_result_page(
        transport,
        "https://h/result",
        "/in/a.jpg",
        matcher,
        link_extractor=TURBO_LIKE,
        poll_delays_ms=[500, 1000, 2000],
        gallery_extractor="a#gallery-name",
    )
    assert result.ok
    assert entry_id(ResultEntry(result.url)) == 2
    assert result.thumb.endswith("2_a.jpg")
    assert result.gallery_url == "https://h/g/9"
    assert transport.pauses == [0.5, 1.0]
    # Each look is one request, as in the legacy resolver: a failed look waits
    # for the next one of the schedule, not for the sidecar's retry backoff.
    assert transport.retries == [False, False, False]


def test_resolve_from_result_page_reports_why_it_gave_up():
    transport = PageTransport([404])
    result = resolve_from_result_page(
        transport,
        "https://h/result",
        "/in/a.jpg",
        ResultPageMatcher(["/in/a.jpg"]),
        link_extractor=TURBO_LIKE,
        poll_delays_ms=[1],
        secrets=["sess-secret-1"],
    )
    assert result.error == "resolve upload result: result page (HTTP 404): gone [redacted]"

    transport = PageTransport([turbo_page([(1, "other.jpg")])])
    result = resolve_from_result_page(
        transport,
        "https://h/r",
        "/in/a.jpg",
        ResultPageMatcher(["/in/a.jpg"]),
        link_extractor=TURBO_LIKE,
        poll_delays_ms=[1],
    )
    assert result.error == "resolve upload result: result page missing 1 link(s)"


def test_resolve_from_result_page_stops_when_cancelled():
    transport = PageTransport([turbo_page([])], cancel_after=1)
    result = resolve_from_result_page(
        transport,
        "https://h/r",
        "/in/a.jpg",
        ResultPageMatcher(["/in/a.jpg"]),
        link_extractor=TURBO_LIKE,
        poll_delays_ms=[1, 1, 1],
    )
    assert result.error == "Upload cancelled"
    assert len(transport.gets) == 1
