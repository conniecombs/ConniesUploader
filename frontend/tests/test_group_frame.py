# SPDX-License-Identifier: MIT
# Copyright (c) 2026 conniecombs

"""CollapsibleGroupFrame bookkeeping that runs without a Tk interpreter."""

import pytest

from modules.widgets import CollapsibleGroupFrame


class FakeWidget:
    def __init__(self, **options):
        self.options = dict(options)

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def get(self):
        return self.options.get("value")

    def set(self, value):
        self.options["value"] = value


def make_group(files=(), covers=()):
    group = CollapsibleGroupFrame.__new__(CollapsibleGroupFrame)
    group.files = list(files)
    group.cover_files = list(covers)
    group.cover_selection_manual = False
    group.is_completed = False
    group.completed_with_failures = False
    group.selected_template = "BBCode"
    group.template_var = FakeWidget(value="BBCode")
    group.template_combo = FakeWidget(values=["BBCode"])
    group.lbl_title = FakeWidget()
    group.lbl_counts = FakeWidget(text=f"({len(group.files)} files)")
    group.prog = FakeWidget()
    return group


@pytest.mark.unit
def test_removing_a_non_cover_file_updates_the_file_count_label():
    group = make_group()
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        CollapsibleGroupFrame.add_file(group, name)

    CollapsibleGroupFrame.remove_file(group, "c.jpg")

    assert group.files == ["a.jpg", "b.jpg"]
    assert group.lbl_counts.options["text"] == "(2 files)"


@pytest.mark.unit
def test_removing_a_cover_file_updates_the_file_count_label():
    group = make_group(["a.jpg", "b.jpg"], covers=["a.jpg"])

    CollapsibleGroupFrame.remove_file(group, "a.jpg")

    assert group.cover_files == []
    assert group.lbl_counts.options["text"] == "(1 files)"


@pytest.mark.unit
def test_template_dropdown_switches_a_missing_template_to_the_fallback():
    group = make_group(["a.jpg"])
    group.selected_template = "Mine"
    group.template_var.set("Mine")

    changed = CollapsibleGroupFrame.update_template_names(
        group, ["BBCode", "Markdown", "Mine v2"], "BBCode"
    )

    assert changed is True
    assert group.selected_template == "BBCode"
    assert group.template_var.get() == "BBCode"
    assert group.template_combo.options["values"] == ["BBCode", "Markdown", "Mine v2"]


@pytest.mark.unit
def test_template_dropdown_keeps_a_template_that_still_exists():
    group = make_group(["a.jpg"])
    group.selected_template = "Markdown"
    group.template_var.set("Markdown")

    changed = CollapsibleGroupFrame.update_template_names(group, ["BBCode", "Markdown"], "BBCode")

    assert changed is False
    assert group.selected_template == "Markdown"
    assert group.template_combo.options["values"] == ["BBCode", "Markdown"]


@pytest.mark.unit
def test_adding_a_file_to_a_completed_group_clears_its_completion():
    group = make_group(["a.jpg"])
    CollapsibleGroupFrame.mark_complete(group)
    group.completed_with_failures = True

    CollapsibleGroupFrame.add_file(group, "b.jpg")

    assert group.is_completed is False
    assert group.completed_with_failures is False
    assert group.lbl_counts.options["text"] == "(2 files)"
    assert group.lbl_title.options["text_color"] != "#34C759"
    assert group.prog.options["progress_color"] != "#34C759"
