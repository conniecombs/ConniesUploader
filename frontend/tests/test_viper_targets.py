# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

import datetime
import json
from pathlib import Path

import pytest

from modules import viper_client, viper_storage, viper_ui
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
    def __init__(self, response=None, responses=None):
        self.responses = list(responses or [])
        self.response = response or {"status": "success"}
        self.requests = []

    def request_sync(self, payload, timeout=0):
        self.requests.append((payload, timeout))
        if self.responses:
            return self.responses.pop(0)
        return self.response


def point_viper_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(viper_storage, "_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(viper_storage, "THREADS_FILE", str(tmp_path / "saved_threads.json"))
    monkeypatch.setattr(
        viper_storage, "POSTING_HISTORY_FILE", str(tmp_path / "posting_history.json")
    )
    monkeypatch.setattr(
        viper_storage, "SCHEDULED_POSTS_FILE", str(tmp_path / "scheduled_posts.json")
    )


@pytest.mark.unit
def test_extract_thread_id_accepts_supported_forms():
    assert viper_storage.extract_thread_id("12345") == "12345"
    assert viper_storage.extract_thread_id("threads/12345") == "12345"
    assert viper_storage.extract_thread_id("https://vipergirls.to/threads/12345-title") == "12345"
    assert viper_storage.extract_thread_id("showthread.php?t=12345") == "12345"
    assert (
        viper_storage.extract_thread_id("https://vipergirls.to/showthread.php?t=12345") == "12345"
    )
    assert viper_storage.extract_thread_id("showthread.php?foo=1&t=12345") == "12345"
    assert viper_storage.extract_thread_id("index.php?x=1;t=12345") == "12345"


@pytest.mark.unit
def test_normalize_thread_input_rejects_non_vipergirls_urls():
    with pytest.raises(viper_storage.ThreadTargetError):
        viper_storage.normalize_thread_input("https://example.com/threads/12345")


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

    assert viper_client.parse_thread_title_from_html(html) == "Exact Site Thread Name"


@pytest.mark.unit
def test_parse_thread_title_cleans_title_suffixes():
    assert (
        viper_client.parse_thread_title_from_html(
            "<html><head><title>Real Thread Name | ViperGirls</title></head></html>"
        )
        == "Real Thread Name"
    )
    assert viper_storage.clean_thread_title("Thread: Real Thread Name") == "Real Thread Name"


@pytest.mark.unit
def test_fetch_thread_title_uses_vipergirls_headers():
    bridge = FakeBridge(
        response={
            "status": "success",
            "data": {"response_body": '<span class="threadtitle">Fetched Thread</span>'},
        }
    )

    title = viper_client.fetch_thread_title(
        "https://vipergirls.to/threads/12345-fetched",
        bridge=bridge,
    )

    assert title == "Fetched Thread"
    payload, timeout = bridge.requests[0]
    spec = payload["generic_spec"]
    assert payload["action"] == "http_request"
    assert payload["service"] == "vipergirls.to"
    assert spec["url"] == "https://vipergirls.to/threads/12345-fetched"
    assert spec["method"] == "GET"
    assert "User-Agent" in spec["headers"]
    assert spec["timeout_seconds"] == viper_client.THREAD_TITLE_TIMEOUT_SECONDS
    assert timeout == viper_client.THREAD_TITLE_TIMEOUT_SECONDS + 5


def test_fetch_thread_title_returns_empty_on_transport_failure():
    bridge = FakeBridge(
        response={"status": "failed", "msg": "Timeout waiting for sidecar response"}
    )

    assert viper_client.fetch_thread_title("https://vipergirls.to/threads/1", bridge=bridge) == ""
    assert viper_client.fetch_thread_title("https://attacker.example/t", bridge=bridge) == ""
    assert len(bridge.requests) == 1


@pytest.mark.unit
def test_vipergirls_post_reply_uses_live_reply_form_fields(monkeypatch):
    html = """
    <html>
      <head><title>Bondage Cafe - Reply to Topic</title></head>
      <body>
        <form action="newreply.php?do=postreply&amp;t=12345" method="post" name="vbform">
          <input name="title" value="Re: Bondage Cafe">
          <textarea name="message_backup"></textarea>
          <textarea name="message"></textarea>
          <input type="hidden" name="wysiwyg" value="0">
          <input type="hidden" name="s" value="">
          <input type="hidden" name="securitytoken" value="tok">
          <input type="hidden" name="do" value="postreply">
          <input type="hidden" name="t" value="12345">
          <input type="hidden" name="p" value="">
          <input type="hidden" name="specifiedpost" value="0">
          <input type="hidden" name="posthash" value="">
          <input type="hidden" name="poststarttime" value="">
          <input type="hidden" name="loggedinuser" value="412723">
          <input type="hidden" name="multiquoteempty" value="">
          <input type="submit" name="preview" value="Preview Post">
          <input type="submit" name="sbutton" value="Submit Reply">
          <input type="checkbox" name="signature" value="1" checked>
          <input type="checkbox" name="parseurl" value="1" checked>
          <select name="emailupdate"><option value="0" selected>No email</option></select>
          <select name="folderid"><option value="0" selected>Default</option></select>
        </form>
      </body>
    </html>
    """
    bridge = FakeBridge(
        responses=[
            {"status": "success", "data": {"response_body": html}},
            {"status": "success", "data": {"response_body": "Thank you for posting"}},
        ]
    )
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_client.ViperGirlsAPI()

    assert api.post_reply("12345", "hello from test") is True
    assert len(bridge.requests) == 2
    fetch_payload, fetch_timeout = bridge.requests[0]
    submit_payload, submit_timeout = bridge.requests[1]
    fetch_spec = fetch_payload["generic_spec"]
    spec = submit_payload["generic_spec"]

    assert fetch_timeout == 35
    assert fetch_spec["timeout_seconds"] == 30
    assert fetch_spec["method"] == "GET"
    assert fetch_spec["url"] == "https://vipergirls.to/newreply.php?do=newreply&t=12345"
    assert fetch_spec["include_response_body"] is True
    assert fetch_spec["include_transport_metadata"] is True
    assert "extract_fields" not in fetch_spec
    assert submit_timeout == 65
    assert spec["timeout_seconds"] == 60
    assert "pre_request" not in spec
    assert "extract_fields" not in spec
    assert "success_check" not in spec
    assert spec["url"] == "https://vipergirls.to/newreply.php?do=postreply&t=12345"
    assert spec["headers"]["Referer"] == "https://vipergirls.to/newreply.php?do=newreply&t=12345"
    assert spec["form_fields"]["title"] == "Re: Bondage Cafe"
    assert spec["form_fields"]["message"] == "hello from test"
    assert spec["form_fields"]["s"] == ""
    assert spec["form_fields"]["p"] == ""
    assert spec["form_fields"]["posthash"] == ""
    assert spec["form_fields"]["poststarttime"] == ""
    assert spec["form_fields"]["loggedinuser"] == "412723"
    assert spec["form_fields"]["sbutton"] == "Submit Reply"
    assert spec["form_fields"]["emailupdate"] == "0"
    assert "preview" not in spec["form_fields"]
    assert spec["include_response_body"] is True
    assert spec["include_transport_metadata"] is True


@pytest.mark.unit
def test_build_site_named_thread_record_uses_fetched_site_title(monkeypatch):
    monkeypatch.setattr(viper_client, "fetch_thread_title", lambda url: "Nicole Scherzinger")

    name, record, fetched = viper_client.build_site_named_thread_record(
        "Manual Name",
        "https://vipergirls.to/threads/151014-Nicole-Scherzinger",
    )

    assert fetched is True
    assert name == "Nicole Scherzinger"
    assert record["site_title"] == "Nicole Scherzinger"
    assert record["thread_id"] == "151014"


@pytest.mark.unit
def test_build_site_named_thread_record_keeps_display_title_when_key_needs_suffix(monkeypatch):
    monkeypatch.setattr(viper_client, "fetch_thread_title", lambda url: "Duplicate Title")

    name, record, fetched = viper_client.build_site_named_thread_record(
        "Manual Name",
        "12345",
        existing_names=["Duplicate Title"],
    )

    assert fetched is True
    assert name == "Duplicate Title (12345)"
    assert record["site_title"] == "Duplicate Title"


@pytest.mark.unit
def test_normalize_thread_record_preserves_created_at():
    record = viper_storage.normalize_thread_record(
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
    record = viper_storage.normalize_thread_record(
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

    loaded = viper_storage.load_saved_threads()
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

    assert viper_storage.load_saved_threads() == {}
    backups = list(tmp_path.glob("saved_threads.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


@pytest.mark.unit
def test_posting_history_backs_up_corrupt_json(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    bad_file = tmp_path / "posting_history.json"
    bad_file.write_text("{not json", encoding="utf-8")

    assert viper_storage.load_posting_history() == []
    backups = list(tmp_path.glob("posting_history.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


@pytest.mark.unit
def test_validate_saved_thread_record_reports_target_errors():
    errors = viper_storage.validate_saved_thread_record(
        "Bad",
        {"url": "https://example.com/threads/12345", "thread_id": ""},
    )

    assert "Target URL must be a ViperGirls URL." in errors

    missing_errors = viper_storage.validate_saved_thread_record("Bad", {"url": "not-a-thread"})
    assert "Target needs a parseable thread ID." in missing_errors


@pytest.mark.unit
def test_import_export_saved_threads_round_trip(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    export_path = tmp_path / "targets-export.json"
    source_targets = {
        "Alpha": viper_storage.normalize_thread_record(
            "Alpha",
            "12345",
            notes="main thread",
            tags=["vip", "alpha"],
        )
    }

    exported = viper_storage.export_saved_threads_file(str(export_path), source_targets)
    imported, imported_count, skipped = viper_storage.import_saved_threads_file(
        str(export_path),
        existing={"Beta": viper_storage.normalize_thread_record("Beta", "22222")},
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
    viper_storage.save_saved_threads(
        {"Target": viper_storage.normalize_thread_record("Target", "12345")}
    )

    updated = viper_storage.mark_thread_target_used("Target", timestamp="2026-06-21T10:00:00+00:00")
    saved = viper_storage.load_saved_threads()

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

    saved = viper_storage.append_posting_history(
        {
            "batch_name": "Batch Alpha",
            "target_name": "Thread Target",
            "thread_id": "12345",
            "status": "success",
            "post_text": "[url]example[/url]",
        }
    )

    loaded = viper_storage.load_posting_history()

    assert saved["target_url"] == "https://vipergirls.to/threads/12345"
    assert loaded == [saved]

    viper_storage.clear_posting_history()

    assert viper_storage.load_posting_history() == []


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

    history = viper_storage.load_posting_history()
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

    history = viper_storage.load_posting_history()
    assert history[0]["status"] == "failure"
    assert history[0]["error"] == "missing credentials"
    assert history[0]["thread_id"] == "54321"


@pytest.mark.unit
def test_auto_poster_marks_target_used(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    viper_storage.save_saved_threads(
        {"Target": viper_storage.normalize_thread_record("Target", "54321")}
    )
    poster = AutoPoster(
        {"vg_user": "user", "vg_pass": "password"},
        viper_storage.load_saved_threads(),
    )

    poster._mark_target_used("Target")

    assert poster.saved_threads_data["Target"]["last_used_at"]
    assert viper_storage.load_saved_threads()["Target"]["last_used_at"]


@pytest.mark.unit
def test_scheduled_posts_are_python_owned(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    bridge = FakeBridge()
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))
    api = viper_client.ViperGirlsAPI()

    assert api.schedule_post(
        "post-1",
        "54321",
        "Target",
        "scheduled body",
        "2026-06-30T22:00:00+00:00",
    )

    posts = api.list_scheduled_posts()
    assert posts[0]["id"] == "post-1"
    assert posts[0]["thread_id"] == "54321"
    assert posts[0]["message"] == "scheduled body"
    assert posts[0]["status"] == "pending"
    assert not bridge.requests

    assert api.cancel_scheduled_post("post-1") is True
    assert api.list_scheduled_posts() == []


@pytest.mark.unit
def test_python_scheduler_processes_due_posts(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    viper_storage.add_scheduled_post(
        {
            "id": "post-1",
            "thread_id": "54321",
            "thread_name": "Target",
            "message": "scheduled body",
            "scheduled_time": "2026-06-30T20:00:00+00:00",
        }
    )

    calls = []

    class FakeViperGirlsAPI:
        def login(self, username, password):
            calls.append(("login", username, password))
            return True

        def post_reply(self, thread_id, message):
            calls.append(("post_reply", thread_id, message))
            return True

    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FakeViperGirlsAPI)
    event_queue = []

    class ListQueue:
        def put_nowait(self, item):
            event_queue.append(item)

    scheduler = viper_client.ViperGirlsPostScheduler(
        {"vg_user": "user", "vg_pass": "password"},
        ListQueue(),
    )
    scheduler.process_due_posts(datetime.datetime(2026, 6, 30, 20, 1, tzinfo=datetime.timezone.utc))

    posts = viper_storage.load_scheduled_posts()
    assert calls == [
        ("login", "user", "password"),
        ("post_reply", "54321", "scheduled body"),
    ]
    assert posts[0]["status"] == "posted"
    assert posts[0]["error"] == ""
    assert event_queue[0]["type"] == "scheduled_post_completed"
    assert event_queue[0]["status"] == "posted"


@pytest.mark.unit
def test_target_manager_filters_by_tags_and_sorts_by_last_used():
    manager = viper_ui.ViperToolsWindow.__new__(viper_ui.ViperToolsWindow)
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

    filtered = viper_ui.ViperToolsWindow._filtered_sorted_targets(manager)

    assert [name for name, _data in filtered] == ["Beta"]

    manager.search_var = FakeVar("")
    manager.sort_var = FakeVar("Last Used")
    sorted_targets = viper_ui.ViperToolsWindow._filtered_sorted_targets(manager)

    assert [name for name, _data in sorted_targets] == ["Alpha", "Beta"]


@pytest.mark.unit
def test_target_manager_toggles_expanded_thread_rows():
    manager = viper_ui.ViperToolsWindow.__new__(viper_ui.ViperToolsWindow)
    manager.expanded_targets = {}
    refreshes = []
    manager.refresh_list = lambda: refreshes.append(True)

    viper_ui.ViperToolsWindow.toggle_target_expanded(manager, "Alpha")

    assert manager.expanded_targets["Alpha"] is True
    assert refreshes == [True]

    viper_ui.ViperToolsWindow.toggle_target_expanded(manager, "Alpha")

    assert manager.expanded_targets["Alpha"] is False
    assert refreshes == [True, True]


@pytest.mark.unit
def test_target_manager_display_name_uses_saved_thread_name():
    assert viper_ui.ViperToolsWindow._display_target_name("  Alpha Thread  ") == "Alpha Thread"
    assert (
        viper_ui.ViperToolsWindow._display_target_name(
            "Manual Alias",
            {"site_title": "Exact Site Thread"},
        )
        == "Exact Site Thread"
    )
    assert viper_ui.ViperToolsWindow._display_target_name("") == "Untitled target"


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


REPLY_FORM_HTML = """
<html><head><title>Thread - Reply to Topic</title></head><body>
<form action="newreply.php?do=postreply&amp;t=12345" method="post" name="vbform">
  <input name="title" value="Re: Set {HD}">
  <textarea name="message"></textarea>
  <input type="hidden" name="securitytoken" value="tok">
  <input type="hidden" name="do" value="postreply">
  <input type="hidden" name="t" value="12345">
  <input type="hidden" name="loggedinuser" value="412723">
  <input type="submit" name="sbutton" value="Submit Reply">
</form></body></html>
"""
LOGIN_PAGE_HTML = """
<html><head><title>Log in</title></head><body>
<form action="login.php?do=login" method="post">
  <input name="vb_login_username"><input name="vb_login_password">
</form></body></html>
"""
LOGGED_IN_HTML = (
    "<html><body><a href='logout.php'>Log Out</a>Thank you for logging in</body></html>"
)


def _ok(body):
    return {"status": "success", "data": {"response_body": body}}


@pytest.mark.unit
def test_login_seed_resets_cookies(monkeypatch):
    bridge = FakeBridge(responses=[_ok(""), _ok(LOGGED_IN_HTML)])
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_client.ViperGirlsAPI()

    assert api.login("user", "password") is True
    seed_payload, _ = bridge.requests[0]
    assert seed_payload["generic_spec"]["reset_cookies"] is True
    login_payload, _ = bridge.requests[1]
    assert "reset_cookies" not in login_payload["generic_spec"]


@pytest.mark.unit
def test_reply_spec_is_literal_and_unretried(monkeypatch):
    bridge = FakeBridge(responses=[_ok(REPLY_FORM_HTML), _ok("Thank you for posting")])
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_client.ViperGirlsAPI()

    assert api.post_reply("12345", "Set {HD} part 2") is True
    submit_payload, _ = bridge.requests[1]
    spec = submit_payload["generic_spec"]
    assert spec["literal_values"] is True
    assert spec["form_fields"]["message"] == "Set {HD} part 2"
    assert spec["form_fields"]["title"] == "Re: Set {HD}"
    assert submit_payload["retry_config"] == {"max_retries": 0}
    fetch_payload, _ = bridge.requests[0]
    assert "retry_config" not in fetch_payload


@pytest.mark.unit
def test_post_reply_relogs_in_once_on_login_page(monkeypatch):
    bridge = FakeBridge(
        responses=[
            _ok(""),
            _ok(LOGGED_IN_HTML),  # initial login
            _ok(LOGIN_PAGE_HTML),  # reply form fetch finds the session gone
            _ok(""),
            _ok(LOGGED_IN_HTML),  # re-login
            _ok(REPLY_FORM_HTML),  # fetch again
            _ok("Thank you for posting"),
        ]
    )
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_client.ViperGirlsAPI()
    assert api.login("user", "password") is True

    assert api.post_reply("12345", "hello") is True
    assert len(bridge.requests) == 7
    relogin_payload, _ = bridge.requests[4]
    assert relogin_payload["generic_spec"]["form_fields"]["vb_login_username"] == "user"


@pytest.mark.unit
def test_post_reply_does_not_loop_on_repeated_login_page(monkeypatch):
    bridge = FakeBridge(
        responses=[
            _ok(""),
            _ok(LOGGED_IN_HTML),
            _ok(LOGIN_PAGE_HTML),
            _ok(""),
            _ok(LOGGED_IN_HTML),
            _ok(LOGIN_PAGE_HTML),
        ]
    )
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_client.ViperGirlsAPI()
    assert api.login("user", "password") is True

    assert api.post_reply("12345", "hello") is False
    assert len(bridge.requests) == 6


@pytest.mark.unit
def test_post_reply_without_stored_credentials_does_not_relogin(monkeypatch):
    bridge = FakeBridge(responses=[_ok(LOGIN_PAGE_HTML)])
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))

    api = viper_client.ViperGirlsAPI()

    assert api.post_reply("12345", "hello") is False
    assert len(bridge.requests) == 1


@pytest.mark.unit
def test_scheduler_does_not_clobber_posts_added_mid_run(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    viper_storage.add_scheduled_post(
        {
            "id": "post-1",
            "thread_id": "54321",
            "thread_name": "Target",
            "message": "first",
            "scheduled_time": "2026-06-30T20:00:00+00:00",
        }
    )

    class FakeViperGirlsAPI:
        def login(self, username, password):
            return True

        def post_reply(self, thread_id, message):
            # The UI schedules another post while this one is being sent.
            viper_storage.add_scheduled_post(
                {
                    "id": "post-2",
                    "thread_id": "54321",
                    "thread_name": "Target",
                    "message": "second",
                    "scheduled_time": "2026-12-30T20:00:00+00:00",
                }
            )
            return True

    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FakeViperGirlsAPI)
    scheduler = viper_client.ViperGirlsPostScheduler({"vg_user": "u", "vg_pass": "p"})
    scheduler.process_due_posts(datetime.datetime(2026, 6, 30, 20, 1, tzinfo=datetime.timezone.utc))

    posts = {post["id"]: post for post in viper_storage.load_scheduled_posts()}
    assert posts["post-1"]["status"] == "posted"
    assert posts["post-2"]["status"] == "pending"


@pytest.mark.unit
def test_scheduler_reads_credentials_from_provider(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    viper_storage.add_scheduled_post(
        {
            "id": "post-1",
            "thread_id": "54321",
            "thread_name": "Target",
            "message": "body",
            "scheduled_time": "2026-06-30T20:00:00+00:00",
        }
    )
    logins = []

    class FakeViperGirlsAPI:
        def login(self, username, password):
            logins.append((username, password))
            return True

        def post_reply(self, thread_id, message):
            return True

    monkeypatch.setattr(viper_client, "ViperGirlsAPI", FakeViperGirlsAPI)
    creds = {"vg_user": "", "vg_pass": ""}
    scheduler = viper_client.ViperGirlsPostScheduler(lambda: creds)
    creds.update({"vg_user": "late-user", "vg_pass": "late-pass"})

    scheduler.process_due_posts(datetime.datetime(2026, 6, 30, 20, 1, tzinfo=datetime.timezone.utc))

    assert logins == [("late-user", "late-pass")]


@pytest.mark.unit
def test_set_scheduled_post_status_updates_one_record(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    for post_id in ("a", "b"):
        viper_storage.add_scheduled_post(
            {
                "id": post_id,
                "thread_id": "54321",
                "thread_name": "Target",
                "message": "body",
                "scheduled_time": "2026-06-30T20:00:00+00:00",
            }
        )

    updated = viper_storage.set_scheduled_post_status("a", "failed", "boom")

    assert updated["status"] == "failed" and updated["error"] == "boom"
    posts = {post["id"]: post for post in viper_storage.load_scheduled_posts()}
    assert posts["b"]["status"] == "pending"
    assert viper_storage.set_scheduled_post_status("missing", "failed") is None
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.unit
def test_concurrent_saved_thread_updates_keep_both(tmp_path, monkeypatch):
    import threading

    point_viper_storage(monkeypatch, tmp_path)
    names = [f"Target {index}" for index in range(20)]
    viper_storage.save_saved_threads(
        {
            name: viper_storage.normalize_thread_record(name, str(10000 + i))
            for i, name in enumerate(names)
        }
    )

    threads = [
        threading.Thread(target=viper_storage.mark_thread_target_used, args=(name,))
        for name in names
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    saved = viper_storage.load_saved_threads()
    assert all(saved[name]["last_used_at"] for name in names)
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.unit
def test_loaded_records_blank_foreign_urls(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    (tmp_path / "saved_threads.json").write_text(
        json.dumps(
            {
                "Evil": {"url": "https://attacker.example/x", "thread_id": "123"},
                "Legacy": "https://attacker.example/legacy?t=456",
                "NoId": {"url": "file:///etc/passwd", "thread_id": ""},
            }
        ),
        encoding="utf-8",
    )

    saved = viper_storage.load_saved_threads()

    assert saved["Evil"]["url"] == "https://vipergirls.to/threads/123"
    assert saved["Legacy"]["url"] == "https://vipergirls.to/threads/456"
    assert saved["NoId"]["url"] == ""


@pytest.mark.unit
def test_file_url_is_rejected_on_import(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    import_path = tmp_path / "import.json"
    import_path.write_text(
        json.dumps({"Bad": {"url": "file:///C:/secrets.txt", "thread_id": "789"}}),
        encoding="utf-8",
    )

    imported, _count, _skipped = viper_storage.import_saved_threads_file(str(import_path))

    assert imported["Bad"]["url"] == "https://vipergirls.to/threads/789"


@pytest.mark.unit
def test_safe_target_url_keeps_forum_links_and_drops_others():
    assert (
        viper_storage.safe_target_url("https://vipergirls.to/threads/1-a", "1")
        == "https://vipergirls.to/threads/1-a"
    )
    assert viper_storage.safe_target_url("https://attacker.example/", "55") == (
        "https://vipergirls.to/threads/55"
    )
    assert viper_storage.safe_target_url("javascript:alert(1)", "") == ""
    assert viper_storage.safe_target_url("threads/12", "12") == "https://vipergirls.to/threads/12"


@pytest.mark.unit
def test_open_supported_url_refuses_foreign_hosts(monkeypatch):
    opened = []
    monkeypatch.setattr(viper_ui.webbrowser, "open", lambda url: opened.append(url))

    assert viper_ui.open_supported_url("https://attacker.example/x") is False
    assert viper_ui.open_supported_url("") is False
    assert viper_ui.open_supported_url("https://vipergirls.to/threads/1") is True
    assert opened == ["https://vipergirls.to/threads/1"]


@pytest.mark.unit
def test_blanked_url_record_still_resolves_thread_id():
    poster = AutoPoster({"vg_user": "u", "vg_pass": "p"}, {"T": {"url": "", "thread_id": "123"}})

    assert poster._resolve_thread_id("T") == ("123", None)
    assert poster._target_url("T", "123") == "https://vipergirls.to/threads/123"


class _FakeEntry:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _FakeButton:
    def __init__(self):
        self.states = []

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.states.append(kwargs["state"])


class _InlineThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.mark.unit
def test_save_target_builds_record_off_thread(tmp_path, monkeypatch):
    point_viper_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(viper_ui.threading, "Thread", _InlineThread)
    built = []

    def fake_build(fallback_name, target, **kwargs):
        built.append(threading_name())
        return (
            "Fetched Name",
            viper_storage.normalize_thread_record("Fetched Name", "12345"),
            "Fetched",
        )

    import threading as _threading

    def threading_name():
        return _threading.current_thread().name

    monkeypatch.setattr(viper_client, "build_site_named_thread_record", fake_build)

    window = viper_ui.ViperToolsWindow.__new__(viper_ui.ViperToolsWindow)
    window.ent_name = _FakeEntry("Fallback")
    window.ent_url = _FakeEntry("12345")
    window.ent_tags = _FakeEntry("")
    window.ent_notes = _FakeEntry("")
    window.editing_name = None
    window.saved_threads = {}
    window.save_button = _FakeButton()
    window.refresh_names_button = _FakeButton()
    window.after = lambda _delay, callback: callback()
    window.cancel_edit = lambda clear_fields=True: None
    window.refresh_list = lambda: None
    window._notify_changed = lambda: None
    window._find_duplicate_thread_id = lambda thread_id, exclude=None: None

    window.save_target()

    assert "Fetched Name" in window.saved_threads
    assert viper_storage.load_saved_threads()["Fetched Name"]["thread_id"] == "12345"
    assert window.save_button.states == ["disabled", "normal"]
    assert built == ["MainThread"]  # inline fake thread; real runs use a worker thread


@pytest.mark.unit
def test_viper_api_facade_reexports_and_refuses_patches():
    from modules import viper_api

    assert viper_api.load_saved_threads is viper_storage.load_saved_threads
    assert viper_api.ViperGirlsAPI is viper_client.ViperGirlsAPI
    assert viper_api.ViperToolsWindow is viper_ui.ViperToolsWindow
    with pytest.raises(AttributeError, match="patch modules.viper_storage.THREADS_FILE"):
        viper_api.THREADS_FILE = "/tmp/elsewhere.json"


@pytest.mark.unit
def test_viper_storage_has_no_network_or_tk_dependencies():
    source = (Path(viper_storage.__file__)).read_text(encoding="utf-8")
    for forbidden in (
        "customtkinter",
        "tkinter",
        "requests",
        "modules.sidecar",
        "modules.transport",
    ):
        assert forbidden not in source, forbidden


@pytest.mark.unit
def test_login_waits_for_an_in_flight_post(monkeypatch):
    """Poster and scheduler share the sidecar cookie jar; a login (which resets
    it) must not land between another client's reply-form fetch and submit."""
    import threading
    import time as _time

    fetch_started = threading.Event()
    release_fetch = threading.Event()
    order = []

    class OrderedBridge:
        def request_sync(self, payload, timeout=0):
            spec = payload["generic_spec"]
            url = spec["url"]
            if "do=newreply" in url:
                order.append("post:fetch")
                fetch_started.set()
                release_fetch.wait(5)
                return _ok(REPLY_FORM_HTML)
            if "do=postreply" in url:
                order.append("post:submit")
                return _ok("Thank you for posting")
            if spec.get("reset_cookies"):
                order.append("login:seed")
                return _ok("")
            order.append("login:submit")
            return _ok(LOGGED_IN_HTML)

    bridge = OrderedBridge()
    monkeypatch.setattr(viper_client.SidecarBridge, "get", staticmethod(lambda: bridge))
    poster_api = viper_client.ViperGirlsAPI()
    scheduler_api = viper_client.ViperGirlsAPI()

    poster = threading.Thread(target=poster_api.post_reply, args=("12345", "hello"))
    poster.start()
    assert fetch_started.wait(2)
    login = threading.Thread(target=scheduler_api.login, args=("user", "password"))
    login.start()
    _time.sleep(0.2)  # give the login a chance to run if it is not serialized
    release_fetch.set()
    poster.join(5)
    login.join(5)

    assert order == ["post:fetch", "post:submit", "login:seed", "login:submit"]


@pytest.mark.unit
def test_viper_api_facade_refuses_sidecar_bridge_patch():
    from modules import viper_api

    with pytest.raises(AttributeError, match="patch modules.viper_client.SidecarBridge"):
        viper_api.SidecarBridge = object
