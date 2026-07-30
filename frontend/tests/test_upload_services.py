# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

from datetime import datetime

import pytest

from modules import upload_session
from modules.upload_models import UploadBatch, UploadFileResult
from modules.upload_output import generate_failed_group_output, generate_group_output
from modules.upload_session import UploadSession


class FakeTemplateManager:
    def __init__(self):
        self.calls = []

    def apply(self, template_name, context, group_results):
        self.calls.append((template_name, dict(context), list(group_results)))
        return f"{context['batch_name']}|{context['gallery_id']}|{len(group_results)}"


@pytest.mark.unit
def test_upload_batch_is_hashable_and_preserves_cover_order():
    batch = UploadBatch("Batch", ["one.jpg", "two.jpg", "three.jpg"])

    assert {batch: list(batch.files)}[batch] == ["one.jpg", "two.jpg", "three.jpg"]
    assert batch.set_cover_file("three.jpg")
    assert batch.cover_filepaths() == ["three.jpg"]

    batch.auto_select_covers(2)

    assert batch.cover_filepaths() == ["three.jpg"]


@pytest.mark.unit
def test_generate_group_output_writes_output_history_and_links(tmp_path):
    first = str(tmp_path / "first.jpg")
    second = str(tmp_path / "second.jpg")
    third = str(tmp_path / "third.jpg")
    batch = UploadBatch(
        "Batch Alpha",
        [first, second, third],
        selected_template="BBCode",
        selected_thread="Target",
        gallery_id="G123",
        gallery_name="Site Gallery",
        gallery_url="https://pixhost.cc/gallery/G123",
        gallery_service="pixhost.cc",
    )
    batch.set_cover_file(third)
    template_manager = FakeTemplateManager()

    output = generate_group_output(
        batch,
        [
            (first, "https://img.test/first", "https://img.test/t-first"),
            (second, "https://img.test/second", "https://img.test/t-second"),
            (third, "https://img.test/third", "https://img.test/t-third"),
        ],
        {"service": "pixhost.cc", "pix_thumb": "200", "pix_links": True},
        template_manager,
        output_dir=str(tmp_path / "output"),
        history_dir=str(tmp_path / "history"),
        saved_threads_data={"Target": {"thread_id": "98765"}},
        now=datetime(2026, 7, 10, 12, 34),
    )

    assert output is not None
    assert output.context["gallery_id"] == "G123"
    assert output.context["gallery_name"] == "Site Gallery"
    assert output.context["thread_id"] == "98765"
    assert output.group_results[0] == (
        "https://img.test/third",
        "https://img.test/t-third",
        "https://img.test/third",
    )
    assert output.text == "Batch Alpha|G123|3"
    assert output.output_file.endswith("Batch_Alpha_20260710_1234.txt")
    assert output.history_file.endswith("Batch_Alpha_20260710_1234.txt")
    assert output.links_file and output.links_file.endswith("Batch_Alpha_20260710_1234_links.txt")
    assert template_manager.calls[0][0] == "BBCode"


@pytest.mark.unit
def test_generate_group_output_skips_incomplete_results(tmp_path):
    first = str(tmp_path / "first.jpg")
    second = str(tmp_path / "second.jpg")
    batch = UploadBatch("Batch Alpha", [first, second], selected_template="BBCode")
    template_manager = FakeTemplateManager()

    output = generate_group_output(
        batch,
        [
            (first, "https://img.test/first", "https://img.test/t-first"),
            (second, "", ""),
        ],
        {"service": "pixhost.cc", "pix_thumb": "200"},
        template_manager,
        output_dir=str(tmp_path / "output"),
        history_dir=str(tmp_path / "history"),
        now=datetime(2026, 7, 10, 12, 34),
    )

    assert output is None
    assert template_manager.calls == []
    assert not (tmp_path / "output").exists()


@pytest.mark.unit
def test_generate_failed_group_output_writes_non_copyable_report(tmp_path):
    first = str(tmp_path / "first.jpg")
    second = str(tmp_path / "second.jpg")
    batch = UploadBatch("Batch Alpha", [first, second])

    output = generate_failed_group_output(
        batch,
        [
            UploadFileResult(first, "https://img.test/first", "https://img.test/t-first"),
            UploadFileResult(second, "", "", success=False, error="server rejected upload"),
        ],
        {"service": "pixhost.to"},
        output_dir=str(tmp_path / "output"),
        history_dir=str(tmp_path / "history"),
        now=datetime(2026, 7, 10, 12, 34),
    )

    assert output is not None
    assert output.copyable is False
    assert output.failed_report is True
    assert output.context["service"] == "pixhost.cc"
    assert output.output_file.endswith("Batch_Alpha_20260710_1234_FAILED.txt")
    assert "Status: FAILED" in output.text
    assert "server rejected upload" in output.text
    assert (tmp_path / "history" / "Batch_Alpha_20260710_1234_FAILED.txt").exists()


@pytest.mark.unit
def test_upload_session_starts_neutral_batches_and_drains_results(monkeypatch, tmp_path):
    created_managers = []
    worker_counts = []

    class FakeUploadManager:
        def __init__(self, progress_queue, result_queue, cancel_event):
            self.progress_queue = progress_queue
            self.result_queue = result_queue
            self.cancel_event = cancel_event
            self.started = None
            created_managers.append(self)

        def start_batch(self, pending_by_group, settings, credentials):
            self.started = (pending_by_group, settings, credentials)

    monkeypatch.setattr(
        upload_session.SidecarBridge,
        "set_worker_count",
        lambda count: worker_counts.append(count),
    )
    monkeypatch.setattr(upload_session.config, "OUTPUT_DIR", str(tmp_path / "web-output"))
    monkeypatch.setattr(upload_session.config, "HISTORY_DIR", str(tmp_path / "web-history"))

    batch = UploadBatch("Batch", ["one.jpg"])
    session = UploadSession(
        [batch],
        {"service": "pixhost.to", "global_worker_count": 1, "global_thread_limit": 8},
        {"token": "secret"},
        manager_factory=FakeUploadManager,
        template_manager=FakeTemplateManager(),
        session_id="test-session",
    )

    session.start()
    manager = created_managers[0]
    pending_by_group, settings, credentials = manager.started

    assert worker_counts == [1]
    assert list(pending_by_group.keys()) == [batch]
    assert settings["global_thread_limit"] == 1
    assert settings["threads"] == 1
    assert credentials == {"token": "secret"}

    session.result_queue.put(("one.jpg", "https://img.test/one", "https://img.test/t-one"))
    events = session.drain_events()
    snapshot = session.snapshot()

    assert events[0].kind == "result"
    assert snapshot.state == "complete"
    assert snapshot.completed_files == 1
    assert snapshot.results == [
        UploadFileResult("one.jpg", "https://img.test/one", "https://img.test/t-one")
    ]
    assert snapshot.output_files[0].group_title == "Batch"
    assert snapshot.output_files[0].text == "Batch||1"
    assert snapshot.output_files[0].output_name.endswith(".txt")
    assert snapshot.output_files[0].copyable is True
