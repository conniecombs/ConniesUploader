# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""UI-neutral upload data models shared by desktop and web runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(eq=False)
class UploadBatch:
    """Small duck-compatible batch object for non-Tk upload callers.

    UploadManager only needs a handful of attributes that the desktop
    CollapsibleGroupFrame already exposes. This model gives FastAPI the same
    contract without importing any Tk widgets.
    """

    title: str
    files: List[str]
    source: str = "web"
    selected_template: str = "BBCode"
    selected_thread: str = "Do Not Post"
    batch_index: int = 0
    gallery_id: str = ""
    gallery_name: str = ""
    gallery_url: str = ""
    gallery_service: str = ""
    gallery_upload_hash: str = ""
    pix_data: Dict[str, Any] | None = None
    turbo_gallery_create: bool | None = None
    turbo_gallery_name: str = ""
    turbo_upload_id: str = ""
    imagebam_gallery_title: str = ""
    cover_files: List[str] = field(default_factory=list)
    cover_selection_manual: bool = False

    def add_file(self, filepath: str) -> None:
        if filepath not in self.files:
            self.files.append(filepath)

    def remove_file(self, filepath: str) -> None:
        if filepath in self.files:
            self.files.remove(filepath)
        if filepath in self.cover_files:
            self.cover_files.remove(filepath)

    def is_cover_file(self, filepath: str) -> bool:
        return filepath in self.cover_files

    def set_cover_file(self, filepath: str, is_cover: bool = True, manual: bool = True) -> bool:
        if filepath not in self.files:
            return False
        changed = False
        if is_cover and filepath not in self.cover_files:
            self.cover_files.append(filepath)
            changed = True
        elif not is_cover and filepath in self.cover_files:
            self.cover_files.remove(filepath)
            changed = True
        if manual:
            self.cover_selection_manual = True
        return changed

    def auto_select_covers(self, count: int) -> None:
        if self.cover_selection_manual:
            return
        self.cover_files = list(self.files[: max(0, int(count))])

    def cover_filepaths(self) -> List[str]:
        cover_set = set(self.cover_files)
        return [filepath for filepath in self.files if filepath in cover_set]


@dataclass(frozen=True)
class UploadFileResult:
    file_path: str
    viewer_url: str
    thumb_url: str
    success: bool = True
    error: str = ""


@dataclass(frozen=True)
class UploadGeneratedOutput:
    group_title: str
    text: str
    output_file: str
    output_name: str
    history_file: str
    links_file: str | None = None
    links_name: str | None = None


@dataclass(frozen=True)
class UploadProgressEvent:
    kind: str
    file_path: str | None = None
    value: Any = None
