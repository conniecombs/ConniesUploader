# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""End to end: the real Go sidecar, UploadManager and ImageBam plugin against a
local fake ImageBam (tests/imagebam_fakes.py), on the Python path and, for
parity, on the legacy Go specs (``legacy_upload_parsing``).

The sidecar is built from backend/ (see test_python_upload_path_e2e.py); the
tests are skipped when Go is not installed. They never contact imagebam.com:
the plugin's IMAGEBAM_URL is pointed at the fake for both paths.
"""

import os
import time

import pytest

from modules.plugins import imagebam
from tests.imagebam_fakes import (
    CREDS,
    LOGIN_REFUSED,
    SCENARIOS,
    USER,
    FakeImageBamServer,
    Group,
    collect_batch,
    lost_answer,
    outcome_matches,
    run_batch,
    shut_down,
    start_batch,
)
from tests.test_python_upload_path_e2e import bridge, sidecar_binary  # noqa: F401 (fixtures)

pytestmark = [pytest.mark.integration, pytest.mark.requires_go]

PATHS = {"legacy": {"legacy_upload_parsing": True}, "python": {}}


@pytest.fixture
def fake(monkeypatch):
    """Start a FakeImageBamServer and point the plugin at it (a new one per call)."""
    monkeypatch.setattr(imagebam, "RESULT_POLL_DELAYS_MS", (20, 40, 80))
    servers = []

    def start(**options):
        server = FakeImageBamServer(**options)
        servers.append(server)
        monkeypatch.setattr(imagebam, "IMAGEBAM_URL", server.url)
        return server

    yield start
    for server in servers:
        server.close()


def make_files(tmp_path, names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"\xff\xd8\xff\xe0" + os.urandom(2048))
        paths.append(os.path.normpath(str(path)))
    return paths


def results_of(outcome, files):
    """Each file's (url, thumb, gallery_url), or None when it failed."""
    return {
        os.path.basename(fp): (
            (*outcome.links[fp], outcome.galleries.get(fp, ""))
            if outcome.final(fp) == "Done"
            else None
        )
        for fp in files
    }


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_both_paths_give_each_file_its_own_upload(tmp_path, fake, bridge, scenario):  # noqa: F811
    files = make_files(tmp_path, scenario.files)
    got = {}
    for path, options in PATHS.items():
        server = fake(**scenario.site_options)
        cfg = {"service": "imagebam.com", **options}

        outcome = run_batch({Group("Set", files): files}, cfg, CREDS)

        want = scenario.legacy if path == "legacy" else scenario.want_python
        for fp, expected in zip(files, want):
            status, link = outcome.final(fp), outcome.link(fp)
            assert outcome_matches(expected, status, link), (path, outcome.statuses)
            if status == "Done":
                assert server.site.image_of(link) == os.path.basename(fp), (path, link)
        assert len(server.site.requests_to("POST", "/upload/session")) == 1, path
        assert outcome.manager._open_session_jobs == [], "the session job never finished"
        got[path] = results_of(outcome, files)
    if not scenario.python:
        # The same (url, thumb, gallery_url) for the same answers.
        assert got["python"] == got["legacy"]


def test_login_csrf_and_one_upload_session_for_a_job_with_a_lost_answer(
    tmp_path, fake, bridge  # noqa: F811
):
    server = fake()
    files = make_files(tmp_path, ["a.jpg", "lost_b.jpg", "c.jpg"])

    outcome = run_batch({Group("Set", files): files}, {"service": "imagebam.com"}, CREDS)

    a, lost, c = files
    assert outcome.final(a) == outcome.final(c) == "Done", outcome.statuses
    # The sidecar's own message, which SiteSidecar copies for the no-Go tests.
    assert outcome.statuses[lost][-2:] == [
        "Failed",
        f"error: {lost_answer(server.url + '/upload')}",
    ]
    # The host stored the lost upload: c still gets its own image, not b's.
    assert [server.site.image_of(outcome.link(fp)) for fp in (a, c)] == ["a.jpg", "c.jpg"]
    assert outcome.link(c).endswith("/ME003")
    site = server.site
    assert site.paths("POST") == [
        "POST /auth/login",
        "POST /upload/session",
        "POST /upload",
        "POST /upload",
        "POST /upload",
    ]
    assert len(site.requests_to("GET", "/auth/login")) == 1
    [login] = site.requests_to("POST", "/auth/login")
    assert login["form"]["email"] == USER and login["form"]["remember"] == "on"
    assert login["form"]["_token"].startswith("login-")
    [opened] = site.requests_to("POST", "/upload/session")
    csrf = opened["headers"]["x-csrf-token"]
    assert csrf.startswith("csrf-") and opened["headers"]["x-requested-with"] == "XMLHttpRequest"
    for upload in site.requests_to("POST", "/upload"):
        assert upload["form"] == {"_token": csrf, "data": "780001"}
        assert upload["headers"]["referer"] == f"{server.url}/"
    assert outcome.manager._open_session_jobs == []


def test_an_auto_gallery_with_a_cover_creates_one_gallery_on_both_paths(
    tmp_path, fake, bridge  # noqa: F811
):
    files = make_files(tmp_path, ["p1.jpg", "cover.jpg", "p2.jpg"])
    got = {}
    for path, options in PATHS.items():
        server = fake()
        group = Group("Beach {2024}", files, covers=[files[1]])
        cfg = {"service": "imagebam.com", "auto_gallery": True, **options}

        outcome = run_batch({group: files}, cfg, CREDS)

        assert [outcome.final(fp) for fp in files] == ["Done"] * 3, (path, outcome.statuses)
        [opened] = server.site.requests_to("POST", "/upload/session")
        assert opened["form"]["gallery_title"] == "Beach {2024}", path
        assert [g["title"] for g in server.site.galleries] == ["Beach {2024}"], path
        assert server.site.uploaded_names() == ["cover.jpg", "p1.jpg", "p2.jpg"], path
        for fp in files:
            assert server.site.image_of(outcome.link(fp)) == os.path.basename(fp), path
            assert outcome.galleries[fp] == "https://www.imagebam.com/view/GA001", path
        got[path] = results_of(outcome, files)
    assert got["python"] == got["legacy"]


def test_a_wrong_password_fails_the_job_on_both_paths(tmp_path, fake, bridge):  # noqa: F811
    files = make_files(tmp_path, ["a.jpg", "b.jpg"])
    creds = {"imagebam_user": USER, "imagebam_pass": "wrong-pass"}
    for path, options in PATHS.items():
        server = fake()

        outcome = run_batch(
            {Group("Set", files): files}, {"service": "imagebam.com", **options}, creds
        )

        for fp in files:
            assert outcome.final(fp).startswith("error"), (path, outcome.statuses)
        assert server.site.uploaded_names() == [], path
    # The Python path names the host's reason, not a parse error.
    assert outcome.final(files[0]) == (
        f"error: upload session setup failed: ImageBam login failed: {LOGIN_REFUSED}"
    )


def test_stop_mid_batch_cancels_the_rest_and_closes_the_session(
    tmp_path, fake, bridge  # noqa: F811
):
    server = fake()
    files = make_files(tmp_path, ["a.jpg", "hold_b.jpg", "c.jpg", "d.jpg"])
    um, progress, results, cancel = start_batch(
        {Group("Set", files): files}, {"service": "imagebam.com"}, CREDS
    )
    try:
        assert server.site.held.wait(30), "hold_b.jpg never reached the host"
        cancel.set()
        um.cancel_batch()

        outcome = collect_batch(um, progress, results, files, timeout=30)

        a, held, c, d = files
        assert outcome.final(a) == "Done", outcome.statuses
        assert [outcome.final(fp) for fp in (held, c, d)] == ["Cancelled"] * 3, outcome.statuses
        assert server.site.uploaded_names() == ["a.jpg", "hold_b.jpg"]
        assert um._open_session_jobs == []
        # The host answers the held upload after Stop: nothing more is reported.
        server.site.release.set()
        time.sleep(0.5)
        late = [item for item in list(progress.queue) if item[1] in (held, c, d)]
        assert late == [] and results.empty()
        assert len(server.site.requests_to("POST", "/upload")) == 2
    finally:
        server.site.release.set()
        shut_down(um)
