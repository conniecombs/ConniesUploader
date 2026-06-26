# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import json

import pytest

from modules import viper_api
from modules.auto_poster import AutoPoster
from modules.widgets import CollapsibleGroupFrame


class FakeCombo:
    def __init__(self):
        self.values = []

    def configure(self, **kwargs):
        if "values" in kwargs:
            self.values = list(kwargs["values"])


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, html):
        self.html = html
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeResponse(self.html)


class FakeBridge:
    def __init__(self, response=None):
        self.response = response or {"status": "success"}
        self.requests = []

    def request_sync(self, payload, timeout=0):
        self.requests.append((payload, timeout))
        return self.response


def point_viper_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(viper_api, "_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(viper_api, "THREADS_FILE", str(tmp_path / "saved_threads.json"))
    monkeypatch.setattr(
        viper_api, "POSTING_HISTORY_FILE", str(tmp_path / "posting_history.json")
    )


@pytest.mark.unit
def test_extract_thread_id_accepts_supported_forms():
    assert viper_api.extract_thread_id("12345") == "12345"
    assert viper_api.extract_thread_id("threads/12345") == "12345"
    assert viper_api.extract_thread_id("https://vipergirls.to/threads/12345-title") == "12345"
    assert viper_api.extract_thread_id("showthread.php?t=12345") == "12345"
    assert viper_api.extract_thread_id("https://vipergirls.to/showthread.php?t=12345") == "12345"
    assert viper_api.extract_thread_id("showthread.php?foo=1&t=12345") == "12345"
    assert viper_api.extract_thread_id("index.php?x=1;t=12345") == "12345"


@pytest.mark.unit
def test_normalize_thread_input_rejects_non_vipergirls_urls():
    with pytest.raises(viper_api.ThreadTargetError):
        viper_api.normalize_thread_input("https://example.com/threads/12345")


@pytest.mark.unit
def test_parse_thread_title_prefers_forum_threadtitle():
    html = """
    <html>
      <head><title>Fallback Title | ViperGirls</title></head>
      <body>
        <h1>Thread: Noisy Title</h1>
        <span class="threadtitle">Exact Site Thread Name</span>
      </body>
    </html>
    """

    assert viper_api.parse_thread_title_from_html(html) == "Exact Site Thread Name"


@pytest.mark.unit
def test_parse_thread_title_cleans_title_suffixes():
    assert (
        viper_api.parse_thread_title_from_html(
            "<html><head><title>Real Thread Name | ViperGirls</title></head></html>"
        )
        == "Real Thread Name"
    )
    assert viper_api.clean_thread_title("Thread: Real Thread Name") == "Real Thread Name"


@pytest.mark.unit
def test_fetch_thread_title_uses_vipergirls_headers():
    session = FakeSession('<span class="threadtitle">Fetched Thread</span>')

    title = viper_api.fetch_thread_title(
        "https://vipergirls.to/threads/12345-fetched",
        session=session,
    )

    assert title == "Fetched Thread"
    assert session.requests[0][0] == "https://vipergirls.to/threads/12345-fetched"
    assert "User-Agent" in session.requests[0][1]["headers"]


@pytest.mark.unit
def test_vipergirls_post_reply_uses_live_reply_form_fields(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(viper_api.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_api.ViperGirlsAPI()

    assert api.post_reply("12345", "hello from test") is True
    assert len(bridge.requests) == 1
    payload, timeout = bridge.requests[0]
    spec = payload["generic_spec"]

    assert timeout == 60
    assert spec["pre_request"]["action"] == "vg_get_reply_form"
    assert spec["pre_request"]["url"] == "https://vipergirls.to/newreply.php?do=newreply&t=12345"
    assert spec["pre_request"]["extract_fields"]["loggedinuser"] == "input[name='loggedinuser']"
    assert spec["pre_request"]["extract_fields"]["reply_title"] == "input[name='title']"
    assert spec["headers"]["Referer"] == "https://vipergirls.to/newreply.php?do=newreply&t=12345"
    assert spec["form_fields"]["title"] == "{reply_title}"
    assert spec["form_fields"]["loggedinuser"] == "{loggedinuser}"
    assert spec["form_fields"]["sbutton"] == "Submit Reply"
    assert spec["form_fields"]["emailupdate"] == "0"
    assert spec["success_check"]["type"] == "any"
    assert any(
        check.get("field") == "__final_url__"
        for check in spec["success_check"]["any"]
    )


@pytest.mark.unit
def test_build_site_named_thread_record_uses_fetched_site_title(monkeypatch):
    monkeypatch.setattr(viper_api, "fetch_thread_title", lambda url: "Nicole Scherzinger")

    name, record, fetched = viper_api.build_site_named_thread_record(
        "Manual Name",
        "https://vipergirls.to/threads/151014-Nicole-Scherzinger",
    )

    assert fetched is True
    assert name == "Nicole Scherzinger"
    assert record["site_title"] == "Nicole Scherzinger"
    assert record["thread_id"] == "151014"


@pytest.mark.unit
def test_build_site_named_thread_record_keeps_display_title_when_key_needs_suffix(monkeypatch):
    monkeypatch.setattr(viper_api, "fetch_thread_title", lambda url: "Duplicate Title")

    name, record, fetched = viper_api.build_site_named_thread_record(
        "Manual Name",
        "12345",
        existing_names=["Duplicate Title"],
    )

    assert fetched is True
    assert name == "Duplicate Title (12345)"
    assert record["site_title"] == "Duplicate Title"


@pytest.mark.unit
def test_normalize_thread_record_preserves_created_at():
    record = viper_api.normalize_thread_record(
        "Thread",
        "12345",
        existing={
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_used_at": "later",
            "notes": "existing note",
            "tags": ["One", "one", "Two"],
            "site_title": "Existing Site Title",
        },
    )

    assert record["url"] == "https://vipergirls.to/threads/12345"
    assert record["thread_id"] == "12345"
    assert record["created_at"] == "2026-01-01T00:00:00+00:00"
    assert record["last_used_at"] == "later"
    assert record["notes"] == "existing note"
    assert record["tags"] == ["One", "Two"]
    assert record["site_title"] == "Existing Site Title"
    assert record["updated_at"] != record["created_at"]


@pytest.mark.unit
def test_normalize_thread_record_accepts_notes_and_comma_tags():
    record = viper_api.normalize_thread_record(
        "Thread",
        "12345",
        notes="watch this one",
        tags="vip, new, vip",
    )

    assert record["notes"] == "watch this one"
    assert record["tags"] == ["vip", "new"]
    assert record["site_title"] == ""


@pytest.mark.unit
def test_load_saved_threads_migrates_legacy_url_records(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    (tmp_path / "saved_threads.json").write_text(
        json.dumps({"Legacy": {"url": "https://vipergirls.to/threads/12345-title"}}),
        encoding="utf-8",
    )

    loaded = viper_api.load_saved_threads()
    saved = json.loads((tmp_path / "saved_threads.json").read_text(encoding="utf-8"))

    assert loaded["Legacy"]["thread_id"] == "12345"
    assert loaded["Legacy"]["url"] == "https://vipergirls.to/threads/12345-title"
    assert loaded["Legacy"]["notes"] == ""
    assert loaded["Legacy"]["tags"] == []
    assert loaded["Legacy"]["site_title"] == ""
    assert saved["Legacy"]["thread_id"] == "12345"
    assert saved["Legacy"]["notes"] == ""
    assert saved["Legacy"]["tags"] == []
    assert saved["Legacy"]["site_title"] == ""
    assert "created_at" in saved["Legacy"]
    assert "updated_at" in saved["Legacy"]


@pytest.mark.unit
def test_load_saved_threads_backs_up_corrupt_json(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    bad_file = tmp_path / "saved_threads.json"
    bad_file.write_text("{not json", encoding="utf-8")

    assert viper_api.load_saved_threads() == {}
    backups = list(tmp_path.glob("saved_threads.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


@pytest.mark.unit
def test_posting_history_backs_up_corrupt_json(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    bad_file = tmp_path / "posting_history.json"
    bad_file.write_text("{not json", encoding="utf-8")

    assert viper_api.load_posting_history() == []
    backups = list(tmp_path.glob("posting_history.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


@pytest.mark.unit
def test_validate_saved_thread_record_reports_target_errors():
    errors = viper_api.validate_saved_thread_record(
        "Bad",
        {"url": "https://example.com/threads/12345", "thread_id": ""},
    )

    assert "Target URL must be a ViperGirls URL." in errors

    missing_errors = viper_api.validate_saved_thread_record("Bad", {"url": "not-a-thread"})
    assert "Target needs a parseable thread ID." in missing_errors


@pytest.mark.unit
def test_import_export_saved_threads_round_trip(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    export_path = tmp_path / "targets-export.json"
    source_targets = {
        "Alpha": viper_api.normalize_thread_record(
            "Alpha",
            "12345",
            notes="main thread",
            tags=["vip", "alpha"],
        )
    }

    exported = viper_api.export_saved_threads_file(str(export_path), source_targets)
    imported, imported_count, skipped = viper_api.import_saved_threads_file(
        str(export_path),
        existing={"Beta": viper_api.normalize_thread_record("Beta", "22222")},
    )

    assert exported == 1
    assert imported_count == 1
    assert skipped == 0
    assert sorted(imported) == ["Alpha", "Beta"]
    assert imported["Alpha"]["notes"] == "main thread"
    assert imported["Alpha"]["tags"] == ["vip", "alpha"]


@pytest.mark.unit
def test_mark_thread_target_used_updates_saved_target(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    viper_api.save_saved_threads(
        {"Target": viper_api.normalize_thread_record("Target", "12345")}
    )

    updated = viper_api.mark_thread_target_used(
        "Target", timestamp="2026-06-21T10:00:00+00:00"
    )
    saved = viper_api.load_saved_threads()

    assert updated["last_used_at"] == "2026-06-21T10:00:00+00:00"
    assert saved["Target"]["last_used_at"] == "2026-06-21T10:00:00+00:00"


@pytest.mark.unit
def test_auto_poster_prefers_normalized_thread_id():
    poster = AutoPoster(
        {"vg_user": "user", "vg_pass": "password"},
        {"Target": {"url": "https://vipergirls.to/no-thread-here", "thread_id": "98765"}},
    )

    assert poster._get_thread_id("Target") == "98765"


@pytest.mark.unit
def test_auto_poster_explains_missing_and_invalid_targets():
    poster = AutoPoster(
        {"vg_user": "user", "vg_pass": "password"},
        {"Bad Target": {"url": "https://vipergirls.to/not-a-thread", "thread_id": ""}},
    )

    missing_id, missing_error = poster._resolve_thread_id("Deleted Target")
    invalid_id, invalid_error = poster._resolve_thread_id("Bad Target")

    assert missing_id is None
    assert missing_error == "target 'Deleted Target' is missing"
    assert invalid_id is None
    assert invalid_error == "target 'Bad Target' has an invalid thread ID"


@pytest.mark.unit
def test_posting_history_is_persisted_and_clearable(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)

    saved = viper_api.append_posting_history(
        {
            "batch_name": "Batch Alpha",
            "target_name": "Thread Target",
            "thread_id": "12345",
            "status": "success",
            "post_text": "[url]example[/url]",
        }
    )

    loaded = viper_api.load_posting_history()

    assert saved["target_url"] == "https://vipergirls.to/threads/12345"
    assert loaded == [saved]

    viper_api.clear_posting_history()

    assert viper_api.load_posting_history() == []


@pytest.mark.unit
def test_auto_poster_records_history_for_post_attempt(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    poster = AutoPoster(
        {"vg_user": "user", "vg_pass": "password"},
        {"Target": {"url": "https://vipergirls.to/threads/54321", "thread_id": "54321"}},
    )
    poster.queue_post(0, "post body", "Target", batch_name="Batch Alpha")
    item = poster.post_queue[0]

    poster._record_history_item(item, "failure", "54321", "post rejected")

    history = viper_api.load_posting_history()
    assert history[0]["batch_name"] == "Batch Alpha"
    assert history[0]["target_name"] == "Target"
    assert history[0]["thread_id"] == "54321"
    assert history[0]["status"] == "failure"
    assert history[0]["error"] == "post rejected"
    assert history[0]["post_text"] == "post body"


@pytest.mark.unit
def test_auto_poster_records_pending_failure_states(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    poster = AutoPoster(
        {"vg_user": "", "vg_pass": ""},
        {"Target": {"url": "https://vipergirls.to/threads/54321", "thread_id": "54321"}},
    )
    poster.queue_post(0, "post body", "Target", batch_name="Batch Alpha")

    poster._record_all_pending_failures("missing credentials")

    history = viper_api.load_posting_history()
    assert history[0]["status"] == "failure"
    assert history[0]["error"] == "missing credentials"
    assert history[0]["thread_id"] == "54321"


@pytest.mark.unit
def test_auto_poster_marks_target_used(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    viper_api.save_saved_threads(
        {"Target": viper_api.normalize_thread_record("Target", "54321")}
    )
    poster = AutoPoster(
        {"vg_user": "user", "vg_pass": "password"},
        viper_api.load_saved_threads(),
    )

    poster._mark_target_used("Target")

    assert poster.saved_threads_data["Target"]["last_used_at"]
    assert viper_api.load_saved_threads()["Target"]["last_used_at"]


@pytest.mark.unit
def test_target_manager_filters_by_tags_and_sorts_by_last_used():
    manager = viper_api.ViperToolsWindow.__new__(viper_api.ViperToolsWindow)
    manager.saved_threads = {
        "Beta": {
            "url": "https://vipergirls.to/threads/22222",
            "thread_id": "22222",
            "notes": "",
            "tags": ["slow"],
            "last_used_at": "2026-06-20T00:00:00+00:00",
        },
        "Alpha": {
            "url": "https://vipergirls.to/threads/11111",
            "thread_id": "11111",
            "notes": "",
            "tags": ["vip"],
            "last_used_at": "2026-06-21T00:00:00+00:00",
        },
    }
    manager.search_var = FakeVar("slow")
    manager.sort_var = FakeVar("Name")

    filtered = viper_api.ViperToolsWindow._filtered_sorted_targets(manager)

    assert [name for name, _data in filtered] == ["Beta"]

    manager.search_var = FakeVar("")
    manager.sort_var = FakeVar("Last Used")
    sorted_targets = viper_api.ViperToolsWindow._filtered_sorted_targets(manager)

    assert [name for name, _data in sorted_targets] == ["Alpha", "Beta"]


@pytest.mark.unit
def test_target_manager_toggles_expanded_thread_rows():
    manager = viper_api.ViperToolsWindow.__new__(viper_api.ViperToolsWindow)
    manager.expanded_targets = {}
    refreshes = []
    manager.refresh_list = lambda: refreshes.append(True)

    viper_api.ViperToolsWindow.toggle_target_expanded(manager, "Alpha")

    assert manager.expanded_targets["Alpha"] is True
    assert refreshes == [True]

    viper_api.ViperToolsWindow.toggle_target_expanded(manager, "Alpha")

    assert manager.expanded_targets["Alpha"] is False
    assert refreshes == [True, True]


@pytest.mark.unit
def test_target_manager_display_name_uses_saved_thread_name():
    assert viper_api.ViperToolsWindow._display_target_name("  Alpha Thread  ") == "Alpha Thread"
    assert (
        viper_api.ViperToolsWindow._display_target_name(
            "Manual Alias",
            {"site_title": "Exact Site Thread"},
        )
        == "Exact Site Thread"
    )
    assert viper_api.ViperToolsWindow._display_target_name("") == "Untitled target"


@pytest.mark.unit
def test_group_thread_dropdown_refreshes_and_resets_missing_selection():
    group = CollapsibleGroupFrame.__new__(CollapsibleGroupFrame)
    group.thread_combo = FakeCombo()
    group.thread_var = FakeVar("Deleted Target")
    group.selected_thread = "Deleted Target"

    CollapsibleGroupFrame.update_thread_names(group, ["Beta", "Alpha"])

    assert group.thread_combo.values == ["Do Not Post", "Alpha", "Beta"]
    assert group.thread_var.get() == "Do Not Post"
    assert group.selected_thread == "Do Not Post"
