# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""Regression tests for folder/file import: bad files, limits, duplicates, sorting."""

import os
import queue
from threading import Lock

import pytest

from modules import config
from modules import file_handler
from modules.exceptions import InvalidFileException
from modules.ui.main_window import UploaderApp
from tests.app_factory import make_app
from tests.test_main_window_contract import FakeGroup, FakeLabel, FakeVar


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _import_app(separate_batches=False):
    app = make_app()
    app.lock = Lock()
    app.lbl_eta = FakeLabel()
    app.var_show_previews = FakeVar(False)
    app.var_separate_batches = FakeVar(separate_batches)
    app.activity = []
    app.import_checks = []
    app.add_activity = lambda message, level="info": app.activity.append((level, message))
    app._set_completion_summary = lambda summary: None
    app._set_import_checks = lambda issues: app.import_checks.append(list(issues))
    app._refresh_queue_state = lambda: None

    def create_group(title, refresh=True):
        group = FakeGroup(title)
        app.groups.append(group)
        return group

    app._create_group = create_group
    return app


def _drain_rows(app):
    while app.pending_ui_rows:
        _epoch, filepath, group, _preview = app.pending_ui_rows.popleft()
        group.add_file(filepath)
        app.file_widgets[filepath] = {"group": group, "state": "pending"}
        app.pending_filepaths.discard(filepath)


# --- E10: size text --------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (1048575, "1 MB"),
        (1073741823, "1 GB"),
        (1024 * 1024 - 5000, "1019.12 KB"),
        (1048576, "1 MB"),
    ],
)
def test_format_file_size_promotes_unit_when_rounding_reaches_1024(size, expected):
    assert file_handler.format_file_size(size) == expected


# --- E6: natural sort ------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("name", ["x1²2.jpg", "1²2.jpg", "³.jpg", "a①b.jpg"])
def test_natural_sort_key_tolerates_non_ascii_digit_characters(name):
    config.natural_sort_key(name)


@pytest.mark.unit
def test_natural_sort_key_orders_ascii_numbers_numerically():
    names = ["img10.jpg", "img2.jpg", "x1²2.jpg", "img1.jpg"]
    assert sorted(names, key=config.natural_sort_key) == [
        "img1.jpg",
        "img2.jpg",
        "img10.jpg",
        "x1²2.jpg",
    ]


@pytest.mark.unit
def test_folder_with_superscript_digit_name_imports(tmp_path):
    folder = tmp_path / "Set"
    for name in ("1.jpg", "2.jpg", "x1²2.jpg"):
        _touch(str(folder / name))

    result = _import_app()._scan_import_inputs([str(folder)])

    assert result["file_count"] == 3
    assert result["rejected_details"] == []


@pytest.mark.unit
def test_import_worker_failure_still_completes_the_import():
    app = _import_app()
    app.ui_queue = queue.Queue()
    import_id, epoch = app._register_import()

    def explode(_inputs):
        raise RuntimeError("scan blew up")

    app._scan_import_inputs = explode

    UploaderApp._scan_import_worker(app, import_id, epoch, ["/x"], None, False, False)

    item = app.ui_queue.get_nowait()
    assert item[0] == "import_complete"
    UploaderApp._handle_import_complete(app, *item[1:])
    assert app.active_import_ids == set()
    assert any("scan blew up" in issue for issue in app.import_checks[-1])


# --- E8: scan limit counts only importable files ---------------------------


@pytest.mark.unit
def test_folder_scan_limit_ignores_files_that_would_not_be_queued(tmp_path, monkeypatch):
    monkeypatch.setattr(file_handler, "MAX_SCAN_FILES", 5)
    for index in range(5):
        _touch(str(tmp_path / f"{index}.jpg"))
    _touch(str(tmp_path / "zz_notes" / "readme.txt"))

    assert len(file_handler.get_files_from_directory(str(tmp_path))) == 5

    _touch(str(tmp_path / "zz_more" / "6.jpg"))
    with pytest.raises(InvalidFileException, match="Too many files"):
        file_handler.get_files_from_directory(str(tmp_path))


@pytest.mark.unit
def test_scan_inputs_limit_ignores_non_images_and_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(file_handler, "MAX_SCAN_FILES", 5)
    folder = tmp_path / "big"
    for index in range(5):
        _touch(str(folder / f"{index}.jpg"))
    notes = _touch(str(tmp_path / "notes.txt"))

    assert len(file_handler.scan_inputs([str(folder), notes])) == 5
    assert len(file_handler.scan_inputs([str(folder)] * 3)) == 5


# --- E1: one bad file must not reject a whole folder -----------------------


@pytest.mark.unit
def test_oversized_file_is_skipped_without_rejecting_folder(tmp_path):
    folder = tmp_path / "Set1"
    for name in ("1.jpg", "2.jpg", "3.jpg"):
        _touch(str(folder / name))
    with open(folder / "huge.png", "wb") as handle:
        handle.truncate(config.MAX_FILE_SIZE + 1)

    result = _import_app()._scan_import_inputs([str(folder)])

    assert result["file_count"] == 3
    assert [os.path.basename(f) for f in result["folder_batches"][0][1]] == [
        "1.jpg",
        "2.jpg",
        "3.jpg",
    ]
    assert len(result["rejected_details"]) == 1
    assert result["rejected_details"][0].startswith("huge.png: ")
    assert "too large" in result["rejected_details"][0]


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_dangling_symlink_is_skipped_without_rejecting_folder(tmp_path):
    folder = tmp_path / "Set1"
    for name in ("1.jpg", "2.jpg"):
        _touch(str(folder / name))
    os.symlink(str(folder / "gone.jpg"), str(folder / "dangling.jpg"))

    result = _import_app()._scan_import_inputs([str(folder)])

    assert result["file_count"] == 2
    assert result["folder_count"] == 1
    assert len(result["rejected_details"]) == 1
    assert result["rejected_details"][0].startswith("dangling.jpg: ")


@pytest.mark.unit
def test_folder_with_only_bad_files_reports_them_not_empty(tmp_path):
    folder = tmp_path / "Set1"
    folder.mkdir()
    with open(folder / "huge.png", "wb") as handle:
        handle.truncate(config.MAX_FILE_SIZE + 1)

    result = _import_app()._scan_import_inputs([str(folder)])

    assert result["file_count"] == 0
    assert result["empty_folders"] == []
    assert result["rejected_details"][0].startswith("huge.png: ")


@pytest.mark.unit
def test_partial_import_lists_each_skipped_file_in_import_checks(tmp_path):
    folder = tmp_path / "Set1"
    for name in ("1.jpg", "2.jpg"):
        _touch(str(folder / name))
    with open(folder / "huge.png", "wb") as handle:
        handle.truncate(config.MAX_FILE_SIZE + 1)
    app = _import_app()

    app._process_files([str(folder)])
    _drain_rows(app)

    assert [(g.title, len(g.files)) for g in app.groups] == [("Set1", 2)]
    assert any(issue.startswith("huge.png: ") for issue in app.import_checks[-1])
    assert "(1 rejected)" in app.lbl_eta.text


# --- E9: one canonical path form for duplicate detection --------------------


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_same_image_via_symlinked_folder_and_as_file_is_queued_once(tmp_path):
    root = tmp_path.resolve()
    real = root / "real" / "Set1"
    _touch(str(real / "1.jpg"))
    os.symlink(str(root / "real"), str(root / "link"))
    via_link_dir = os.path.join(str(root), "link", "Set1")
    via_link_file = os.path.join(via_link_dir, "1.jpg")
    app = _import_app()

    app._process_files([via_link_dir])
    _drain_rows(app)
    app._process_files([via_link_file])
    _drain_rows(app)

    assert len(app.file_widgets) == 1
    assert [(g.title, len(g.files)) for g in app.groups if g.files] == [("Set1", 1)]


@pytest.mark.unit
def test_dropped_file_is_queued_under_its_canonical_path(tmp_path):
    image = _touch(str(tmp_path / "a" / ".." / "a" / "1.jpg"))

    result = _import_app()._scan_import_inputs([image])

    assert result["misc_files"] == [str((tmp_path / "a" / "1.jpg").resolve())]


# --- E7: no empty batch for a re-dropped folder/file -----------------------


@pytest.mark.unit
def test_dropping_already_queued_folder_does_not_create_empty_group(tmp_path):
    folder = tmp_path / "Set1"
    for name in ("1.jpg", "2.jpg"):
        _touch(str(folder / name))
    app = _import_app()

    app._process_files([str(folder)])
    _drain_rows(app)
    app._process_files([str(folder)])
    _drain_rows(app)

    assert [(g.title, len(g.files)) for g in app.groups] == [("Set1", 2)]
    assert app.lbl_eta.text == "No new files were added."


@pytest.mark.unit
def test_separate_batches_redrop_does_not_create_empty_group(tmp_path):
    loose = _touch(str(tmp_path / "x.png"))
    app = _import_app(separate_batches=True)

    app._process_files([loose])
    _drain_rows(app)
    app._process_files([loose])
    _drain_rows(app)

    assert [(g.title, len(g.files)) for g in app.groups] == [("x.png", 1)]


@pytest.mark.unit
def test_misc_group_not_created_when_all_loose_files_are_duplicates(tmp_path):
    loose = _touch(str(tmp_path / "x.png"))
    app = _import_app()
    app._process_files([loose])
    _drain_rows(app)
    app.groups[0].title = "Renamed"

    app._process_files([loose])
    _drain_rows(app)

    assert [g.title for g in app.groups] == ["Renamed"]
