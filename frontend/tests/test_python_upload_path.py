# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""The upload manager's Python upload path, driven by a fake sidecar.

A plugin that defines parse_upload_response uploads through a transport
session: session_open, the plugin's open_upload_session on a worker thread,
one raw http_upload job, the plugin's parser on a small pool for each raw
result, then session_close once the job and its parsing are done.
"""

import os
import queue
import threading
import time

import pytest

from modules import upload_manager
from modules.plugins.base import ImageHostPlugin, uses_python_upload_parsing
from modules.sidecar import PROCESS_RESTARTED_MSG
from modules.transport import UploadTransport
from modules.upload_results import UploadResult
from modules.upload_sessions import SessionState

INTERRUPTED = f"error: {PROCESS_RESTARTED_MSG}"


class FakeSidecar:
    """Answers session_open; records every command; delivers events on demand."""

    def __init__(self, generation=1):
        self.generation = generation
        self.sent = []
        self.requests = []
        self.listeners = []
        self.open_reply = None
        self.sessions = 0
        self.available = True

    def add_listener(self, q):
        self.listeners.append(q)

    def remove_listener(self, q):
        if q in self.listeners:
            self.listeners.remove(q)

    def send_job(self, payload):
        if not self.available:
            return None
        self.sent.append(payload)
        return self.generation

    def send_cmd(self, payload):
        return self.send_job(payload) is not None

    def request_with_generation(self, payload, timeout=0, cancel_event=None):
        self.requests.append(payload)
        if payload["action"] == "session_open":
            if self.open_reply is not None:
                return dict(self.open_reply, id=payload["id"]), self.generation
            self.sessions += 1
            reply = {"status": "success", "data": {"session_id": f"s-{self.sessions}"}}
            return dict(reply, id=payload["id"]), self.generation
        return {"id": payload["id"], "status": "success", "data": {}}, self.generation

    def request_sync(self, payload, timeout=0, cancel_event=None):
        return self.request_with_generation(payload, timeout, cancel_event)[0]

    def jobs(self):
        return [p for p in self.sent if p.get("action") == "http_upload"]

    def closes(self):
        return [p for p in self.sent if p.get("action") == "session_close"]


class ParsingPlugin:
    """A plugin on the Python path that records what it was given."""

    id = "parse.test"
    name = "Parse"
    metadata = {"credentials": [{"key": "parse_key"}]}

    def __init__(self):
        self.calls = []
        self.threads = {}
        self.options = {}
        self.session_values = {"sess_id": "sess-value-123"}
        self.open_error = None
        self.build_error_for = set()
        self.parse = lambda fp, response: UploadResult(
            f"https://h/v/{os.path.basename(fp)}", "https://h/t"
        )
        self.gate = None

    def upload_job_options(self, config):
        return self.options

    def open_upload_session(self, transport, config, creds):
        self.threads["open"] = threading.current_thread().name
        self.calls.append(("open", transport.session_id, creds.get("parse_key")))
        if self.open_error:
            raise self.open_error
        return dict(self.session_values)

    def build_raw_upload_request(self, file_path, config, session_values, creds):
        if file_path in self.build_error_for:
            raise ValueError(f"cannot upload {file_path} with key {creds.get('parse_key')}")
        return {
            "url": "https://h/upload",
            "method": "POST",
            "headers": {"X-Key": creds.get("parse_key", "")},
            "multipart_fields": {
                "file": {"type": "file", "value": file_path},
                "sess": {"type": "text", "value": session_values.get("sess_id", "")},
            },
        }

    def parse_upload_response(self, file_path, response, transport, session_values, session_state):
        self.threads["parse"] = threading.current_thread().name
        self.calls.append(("parse", file_path, response, transport, session_values, session_state))
        if self.gate is not None:
            self.gate.wait(5)
        return self.parse(file_path, response)


class LegacyPlugin:
    metadata = {}

    def build_http_request(self, file_path, config, creds):
        return {"url": "https://h/legacy", "multipart_fields": {}}


@pytest.fixture
def env(monkeypatch):
    bridge = FakeSidecar()
    monkeypatch.setattr(upload_manager.SidecarBridge, "get", staticmethod(lambda: bridge))
    progress, results, cancel = queue.Queue(), queue.Queue(), threading.Event()
    um = upload_manager.UploadManager(progress, results, cancel)
    um.current_batch_id = "b1"
    plugin = ParsingPlugin()
    monkeypatch.setattr(um.plugin_manager, "get_plugin", lambda service_id: plugin)

    class Env:
        pass

    e = Env()
    e.um, e.bridge, e.progress, e.results, e.cancel, e.plugin = (
        um,
        bridge,
        progress,
        results,
        cancel,
        plugin,
    )
    e.statuses = []
    e.result_items = []
    return e


CREDS = {"parse_key": "key-secret-99", "other_host_pass": "unrelated"}
CFG = {"service": "parse.test", "thumbnail_size": "180"}


def drain(env):
    while True:
        try:
            env.statuses.append(env.progress.get_nowait())
        except queue.Empty:
            break
    while True:
        try:
            env.result_items.append(env.results.get_nowait())
        except queue.Empty:
            break


def wait_for(env, condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        drain(env)
        if condition():
            return
        time.sleep(0.01)
    drain(env)
    raise AssertionError(f"condition not met; statuses={env.statuses} results={env.result_items}")


def status_of(env, fp):
    return [item[2] for item in env.statuses if item[0] == "status" and item[1] == fp]


def raw_result(job_id, fp, body='{"ok":1}', status_code="200"):
    return {
        "id": job_id,
        "type": "result",
        "file": fp,
        "data": {
            "response_body": body,
            "status_code": status_code,
            "final_url": "https://h/upload",
        },
    }


def finish_raw(env, job, files):
    for fp in files:
        env.um._handle_event(raw_result(job["id"], os.path.normpath(fp)))
        env.um._handle_event({"id": job["id"], "type": "status", "file": fp, "status": "Uploaded"})
    env.um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})


# --- Path selection -------------------------------------------------------------------


def test_only_plugins_that_parse_responses_use_the_python_path():
    class Parses(ImageHostPlugin):
        id = name = "x"

        def initialize_session(self, config, creds):
            return {}

        def upload_file(self, *args):
            return "", ""

        def parse_upload_response(
            self, file_path, response, transport, session_values, session_state
        ):
            return UploadResult()

    class Legacy(Parses):
        parse_upload_response = ImageHostPlugin.parse_upload_response

    assert uses_python_upload_parsing(Parses()) is True
    assert uses_python_upload_parsing(Legacy()) is False
    assert uses_python_upload_parsing(ParsingPlugin()) is True
    assert uses_python_upload_parsing(LegacyPlugin()) is False
    assert uses_python_upload_parsing(None) is False


def test_base_plugin_defaults_for_the_python_path():
    class Plain(ImageHostPlugin):
        id = name = "plain"

        def initialize_session(self, config, creds):
            return {}

        def upload_file(self, *args):
            return "", ""

    plugin = Plain()
    assert plugin.upload_job_options({}) == {}
    assert plugin.open_upload_session(None, {}, {}) == {}
    with pytest.raises(NotImplementedError):
        plugin.build_raw_upload_request("/a.jpg", {}, {}, {})
    with pytest.raises(NotImplementedError):
        plugin.parse_upload_response("/a.jpg", None, None, {}, SessionState(["/a.jpg"]))


# --- The happy path -------------------------------------------------------------------


def test_a_parsing_plugin_uploads_through_a_transport_session(env):
    files = ["/set/a.jpg", "/set/b.jpg"]
    env.um._send_job(files, CFG, CREDS)

    opened = env.bridge.requests[0]
    assert opened["action"] == "session_open" and opened["batch_id"] == "b1"
    assert env.plugin.calls[0] == ("open", "s-1", "key-secret-99")

    [job] = env.bridge.jobs()
    assert job["raw_response"] is True
    assert job["session_id"] == "s-1"
    assert job["batch_id"] == "b1" and job["id"].startswith("b1:")
    assert job["files"] == [os.path.normpath(f) for f in files]
    assert job["sequential"] is False
    assert job["creds"] == {}, "raw jobs need no credentials in the sidecar"
    assert "http_spec" not in job and "resolve_spec" not in job
    request = job["file_requests"][os.path.normpath("/set/a.jpg")]
    assert request["url"] == "https://h/upload"
    assert request["multipart_fields"]["file"] == {
        "type": "file",
        "value": os.path.normpath("/set/a.jpg"),
    }
    assert request["multipart_fields"]["sess"] == {"type": "text", "value": "sess-value-123"}
    assert request["headers"] == {"X-Key": "key-secret-99"}
    assert env.um.active_files == set(files)

    finish_raw(env, job, files)
    wait_for(env, lambda: all("Done" in status_of(env, os.path.normpath(f)) for f in files))

    assert sorted(env.result_items) == [
        (os.path.normpath("/set/a.jpg"), "https://h/v/a.jpg", "https://h/t"),
        (os.path.normpath("/set/b.jpg"), "https://h/v/b.jpg", "https://h/t"),
    ]
    _, fp, response, transport, session_values, state = env.plugin.calls[1]
    assert response.ok and response.body == '{"ok":1}' and response.status_code == 200
    assert response.final_url == "https://h/upload"
    assert isinstance(transport, UploadTransport) and transport.session_id == "s-1"
    assert session_values == {"sess_id": "sess-value-123"}
    assert isinstance(state, SessionState) and set(state.files) == {
        os.path.normpath(f) for f in files
    }
    assert "key-secret-99" in state.secrets and "sess-value-123" in state.secrets
    assert "unrelated" not in state.secrets
    # Uploaded is shown as an in-progress status before Done.
    a_status = status_of(env, os.path.normpath("/set/a.jpg"))
    assert a_status.index("Uploaded") < a_status.index("Done")
    wait_for(env, lambda: len(env.bridge.closes()) == 1)
    assert env.bridge.closes()[0]["session_id"] == "s-1"
    assert env.bridge.closes()[0]["id"]


def test_parsing_runs_on_the_pool_and_never_blocks_the_listener(env):
    env.plugin.gate = threading.Event()
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()

    start = time.monotonic()
    env.um._handle_event(raw_result(job["id"], "/a.jpg"))
    env.um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})
    assert time.monotonic() - start < 1, "the event listener waited for the parser"

    time.sleep(0.1)
    assert env.bridge.closes() == [], "the session closed while its parser was still running"
    env.plugin.gate.set()
    wait_for(env, lambda: "Done" in status_of(env, "/a.jpg") and len(env.bridge.closes()) == 1)
    assert env.plugin.threads["parse"].startswith("UploadPostProcess")


def test_session_opens_on_the_dispatch_thread_during_a_batch(env):
    class Group:
        title = "Set"
        files = ["/a.jpg"]

    env.um.start_batch({Group(): ["/a.jpg"]}, CFG, CREDS)
    deadline = time.monotonic() + 5
    while not env.bridge.jobs() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert env.plugin.threads["open"] == "UploadManagerDispatch"
    env.um.shutdown()


def test_a_plugin_without_the_optional_hooks_gets_the_base_defaults(env, monkeypatch):
    class Minimal:
        metadata = {}

        def build_raw_upload_request(self, file_path, config, session_values, creds):
            return {
                "url": "https://h/u",
                "multipart_fields": {"f": {"type": "file", "value": file_path}},
            }

        def parse_upload_response(self, file_path, response, transport, session_values, state):
            return UploadResult("https://h/v", "https://h/t")

    monkeypatch.setattr(env.um.plugin_manager, "get_plugin", lambda service_id: Minimal())
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()
    assert job["sequential"] is False
    finish_raw(env, job, ["/a.jpg"])
    wait_for(env, lambda: "Done" in status_of(env, "/a.jpg"))


# --- Failures ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parse", "want"),
    [
        (
            lambda fp, r: UploadResult.failed("upload rejected (HTTP 403): bad key key-secret-99"),
            "error: upload rejected (HTTP 403): bad key [redacted]",
        ),
        (lambda fp, r: UploadResult(), "error: Host returned no link"),
        (lambda fp, r: UploadResult(" ", "https://h/t"), "error: Host returned no link"),
        (
            lambda fp, r: 42,
            "error: could not read the host's answer: the parser returned int, not an UploadResult",
        ),
    ],
)
def test_a_parser_failure_fails_the_file_with_its_reason(env, parse, want):
    env.plugin.parse = parse
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    finish_raw(env, env.bridge.jobs()[0], ["/a.jpg"])
    wait_for(env, lambda: any(s.startswith("error") for s in status_of(env, "/a.jpg")))
    assert status_of(env, "/a.jpg")[-1] == want
    assert env.result_items == [("/a.jpg", "", "")]


def test_a_parser_exception_fails_the_file(env):
    def boom(fp, response):
        raise KeyError("data")

    env.plugin.parse = boom
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    finish_raw(env, env.bridge.jobs()[0], ["/a.jpg"])
    wait_for(env, lambda: any(s.startswith("error") for s in status_of(env, "/a.jpg")))
    assert status_of(env, "/a.jpg")[-1] == "error: could not read the host's answer: 'data'"
    wait_for(env, lambda: len(env.bridge.closes()) == 1)


def test_session_open_failure_fails_the_group_with_the_reason(env):
    env.bridge.open_reply = {"status": "failed", "msg": "batch cancelled"}
    env.um._send_job(["/a.jpg", "/b.jpg"], CFG, CREDS)
    drain(env)
    assert env.bridge.jobs() == []
    for fp in ("/a.jpg", "/b.jpg"):
        assert status_of(env, fp) == ["error: could not open an upload session: batch cancelled"]
    assert sorted(env.result_items) == [("/a.jpg", "", ""), ("/b.jpg", "", "")]


def test_stop_before_the_session_opens_cancels_the_group(env):
    env.cancel.set()
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    drain(env)
    assert env.bridge.requests == [] and env.bridge.jobs() == []
    assert status_of(env, "/a.jpg") == ["Cancelled"]


def test_login_failure_fails_the_group_and_closes_the_session(env):
    env.plugin.open_error = RuntimeError("login refused for key-secret-99")
    env.um._send_job(["/a.jpg", "/b.jpg"], CFG, CREDS)
    drain(env)
    assert env.bridge.jobs() == []
    for fp in ("/a.jpg", "/b.jpg"):
        assert status_of(env, fp) == [
            "error: upload session setup failed: login refused for [redacted]"
        ]
    assert [c["session_id"] for c in env.bridge.closes()] == ["s-1"]


def test_a_file_whose_request_cannot_be_built_fails_alone(env):
    env.plugin.build_error_for = {"/b.jpg"}
    env.um._send_job(["/a.jpg", "/b.jpg"], CFG, CREDS)
    drain(env)
    [job] = env.bridge.jobs()
    assert job["files"] == [os.path.normpath("/a.jpg")]
    assert status_of(env, "/b.jpg") == ["error: cannot upload /b.jpg with key [redacted]"]


def test_sidecar_failures_still_end_files(env):
    env.um._send_job(["/a.jpg", "/b.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()
    env.um._handle_event({"id": job["id"], "type": "status", "file": "/a.jpg", "status": "Failed"})
    env.um._handle_event(
        {"id": job["id"], "type": "error", "file": "/a.jpg", "msg": "upload stalled"}
    )
    env.um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})
    wait_for(env, lambda: len(env.bridge.closes()) == 1)
    assert status_of(env, "/a.jpg") == ["Failed", "error: upload stalled"]
    assert status_of(env, "/b.jpg") == ["error: no result received from sidecar"]


def test_a_job_level_error_ends_the_job_without_batch_complete(env):
    # The sidecar rejects a whole job (invalid job, recovered panic) with an
    # error that names no file and sends no batch_complete afterwards.
    env.plugin.options = {"sequential": True}
    env.um._send_job(["/s/1.jpg", "/s/2.jpg"], CFG, CREDS)
    first = env.bridge.jobs()[0]
    env.um._handle_event({"id": first["id"], "type": "error", "msg": "Panic: boom"})
    wait_for(env, lambda: len(env.bridge.jobs()) == 2)
    second = env.bridge.jobs()[1]
    env.um._handle_event({"id": second["id"], "type": "error", "msg": "Invalid job: no files"})
    wait_for(env, lambda: len(env.bridge.closes()) == 1)
    assert status_of(env, "/s/1.jpg") == ["error: Panic: boom"]
    assert status_of(env, "/s/2.jpg") == ["error: Invalid job: no files"]
    assert env.um._open_session_jobs == []


# --- Stop and crashes ----------------------------------------------------------------


def test_stop_cancels_the_batch_and_reports_cancelled_parses(env):
    env.plugin.gate = threading.Event()
    env.plugin.parse = lambda fp, r: UploadResult.failed("resolve upload result: Upload cancelled")
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()
    env.um._handle_event(raw_result(job["id"], "/a.jpg"))

    env.cancel.set()
    env.um.cancel_batch()
    assert env.bridge.sent[-1] == {"action": "cancel", "batch_id": "b1"}
    env.plugin.gate.set()
    env.um._handle_event({"id": job["id"], "type": "batch_complete", "status": "done"})
    wait_for(env, lambda: "Cancelled" in status_of(env, "/a.jpg"))


def test_a_crash_ends_files_still_in_the_sidecar_and_never_closes_the_dead_session(env):
    env.plugin.gate = threading.Event()
    env.um._send_job(["/a.jpg", "/b.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()
    env.um._handle_event(raw_result(job["id"], "/a.jpg"))  # /a.jpg is being parsed

    env.um._handle_event({"type": "sidecar_crashed", "generation": 1, "msg": PROCESS_RESTARTED_MSG})
    drain(env)
    assert status_of(env, "/b.jpg") == [INTERRUPTED]

    env.plugin.gate.set()
    wait_for(env, lambda: "Done" in status_of(env, "/a.jpg"))
    time.sleep(0.1)
    assert env.bridge.closes() == [], "a session of a dead process must not be closed"
    assert env.um._open_session_jobs == []


def test_a_crash_of_an_older_process_leaves_the_session_alone(env):
    env.bridge.generation = 3
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    env.um._handle_event({"type": "sidecar_crashed", "generation": 2, "msg": PROCESS_RESTARTED_MSG})
    finish_raw(env, env.bridge.jobs()[0], ["/a.jpg"])
    wait_for(env, lambda: "Done" in status_of(env, "/a.jpg") and len(env.bridge.closes()) == 1)


def test_a_failed_upload_whose_body_reached_the_host_is_recorded(env):
    env.um._send_job(["/a.jpg", "/b.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()
    state = env.um._session_jobs[job["id"]].state
    env.um._handle_event(
        {
            "id": job["id"],
            "type": "status",
            "file": "/a.jpg",
            "status": "Failed",
            "data": {"body_sent": "true"},
        }
    )
    assert state.uploaded_files == ("/a.jpg",)
    assert state.is_settled("/a.jpg")
    env.um._handle_event({"id": job["id"], "type": "status", "file": "/b.jpg", "status": "Failed"})
    assert state.uploaded_files == ("/a.jpg",)


# --- Sequential jobs -----------------------------------------------------------------


def test_a_sequential_host_uploads_the_next_file_only_after_the_last_was_parsed(env):
    env.plugin.options = {"sequential": True}
    env.plugin.gate = threading.Event()
    files = ["/s/1.jpg", "/s/2.jpg", "/s/3.jpg"]
    env.um._send_job(files, CFG, CREDS)

    [first] = env.bridge.jobs()
    assert first["files"] == [os.path.normpath("/s/1.jpg")]
    assert first["sequential"] is True and first["session_id"] == "s-1"
    finish_raw(env, first, ["/s/1.jpg"])
    time.sleep(0.1)
    assert len(env.bridge.jobs()) == 1, "the next upload started before the last was parsed"

    env.plugin.gate.set()
    wait_for(env, lambda: len(env.bridge.jobs()) == 2)
    second = env.bridge.jobs()[1]
    assert second["files"] == [os.path.normpath("/s/2.jpg")] and second["session_id"] == "s-1"
    finish_raw(env, second, ["/s/2.jpg"])
    wait_for(env, lambda: len(env.bridge.jobs()) == 3)
    finish_raw(env, env.bridge.jobs()[2], ["/s/3.jpg"])
    wait_for(env, lambda: len(env.bridge.closes()) == 1)
    assert [status_of(env, os.path.normpath(f))[-1] for f in files] == ["Done"] * 3
    assert len(env.bridge.requests) == 1, "one session serves the whole sequential job"


def test_stop_during_a_sequential_job_cancels_the_files_not_sent(env):
    env.plugin.options = {"sequential": True}
    env.um._send_job(["/s/1.jpg", "/s/2.jpg", "/s/3.jpg"], CFG, CREDS)
    first = env.bridge.jobs()[0]
    env.cancel.set()
    env.um.cancel_batch()
    env.um._handle_event(
        {"id": first["id"], "type": "status", "file": "/s/1.jpg", "status": "Cancelled"}
    )
    env.um._handle_event({"id": first["id"], "type": "batch_complete", "status": "done"})
    wait_for(env, lambda: len(env.bridge.closes()) == 1)
    assert len(env.bridge.jobs()) == 1
    assert status_of(env, "/s/2.jpg") == ["Cancelled"]
    assert status_of(env, "/s/3.jpg") == ["Cancelled"]


def test_a_crash_during_a_sequential_job_ends_the_files_not_sent(env):
    env.plugin.options = {"sequential": True}
    env.um._send_job(["/s/1.jpg", "/s/2.jpg"], CFG, CREDS)
    env.um._handle_event({"type": "sidecar_crashed", "generation": 1, "msg": PROCESS_RESTARTED_MSG})
    wait_for(env, lambda: status_of(env, "/s/2.jpg") == [INTERRUPTED])
    assert status_of(env, "/s/1.jpg") == [INTERRUPTED]
    assert len(env.bridge.jobs()) == 1 and env.bridge.closes() == []


# --- The escape hatch ---------------------------------------------------------------------


@pytest.mark.parametrize("flag", [True, "true", "1"])
def test_legacy_upload_parsing_routes_every_host_to_its_legacy_spec(env, flag):
    env.plugin.build_http_request = lambda file_path, config, creds: {
        "url": "https://h/legacy",
        "multipart_fields": {"file": {"type": "file", "value": file_path}},
        "response_parser": {"type": "json", "url_path": "url"},
    }
    env.um._send_job(["/a.jpg"], dict(CFG, legacy_upload_parsing=flag), CREDS)
    [job] = env.bridge.jobs()
    assert "raw_response" not in job and "session_id" not in job
    assert job["http_spec"]["url"] == "https://h/legacy"
    assert env.bridge.requests == [], "the legacy path opens no transport session"


def test_plugins_without_a_parser_keep_the_legacy_path(env, monkeypatch):
    monkeypatch.setattr(env.um.plugin_manager, "get_plugin", lambda service_id: LegacyPlugin())
    env.um._send_job(["/a.jpg"], CFG, CREDS)
    [job] = env.bridge.jobs()
    assert job["http_spec"]["url"] == "https://h/legacy"
    assert "raw_response" not in job


# --- SessionState --------------------------------------------------------------------------


def test_session_state_is_a_dict_that_feeds_its_result_matchers():
    state = SessionState(["/a.jpg", "/b.jpg"], secrets=["tok-123456"])
    state["gallery"] = "g1"
    assert state["gallery"] == "g1"
    state.record_uploaded("/a.jpg")
    matcher = state.result_matcher("filename")
    assert state.result_matcher("filename") is matcher
    state.record_uploaded("/b.jpg")
    state.settle("/a.jpg")
    assert matcher._position("/a.jpg") == 0 and matcher._position("/b.jpg") == 1
    assert matcher._holds("/a.jpg") is False and matcher._holds("/b.jpg") is True
    assert state.get_or_create("counter", list) is state.get_or_create("counter", list)
    state.add_secrets("short", "x")
    assert state.secrets == ["tok-123456", "short"]
