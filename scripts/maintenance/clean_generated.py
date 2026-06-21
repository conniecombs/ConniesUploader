#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Remove generated build, coverage, and runtime clutter from the repository."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DIRS = (
    "build",
    "dist",
    "htmlcov",
    ".pytest_cache",
)

DEFAULT_FILES = (
    ".coverage",
    "coverage.out",
    "uploader",
    "uploader.exe",
    "ConniesUploader",
    "ConniesUploader.exe",
    "ConniesUploader.spec",
)

DEFAULT_PATTERNS = (
    ".coverage.*",
    "crash_log*.log",
)

OPTIONAL_USER_DIRS = (
    "Output",
)

OPTIONAL_USER_FILES = (
    "user_settings.json",
    "user_templates.json",
)

SKIP_DIRS = {
    ".git",
    ".github",
    ".build-tools",
    "venv",
    ".venv",
    "env",
    "ENV",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely remove generated artifacts from the Connie's Uploader checkout."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed without deleting anything.")
    parser.add_argument("--include-output", action="store_true", help="Also remove the local Output/ folder.")
    parser.add_argument(
        "--include-user-data",
        action="store_true",
        help="Also remove legacy local user_settings.json and user_templates.json files.",
    )
    return parser.parse_args()


def is_safe_repo_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return path.resolve() != REPO_ROOT


def iter_pycache_dirs() -> list[Path]:
    matches: list[Path] = []
    for path in REPO_ROOT.rglob("__pycache__"):
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        matches.append(path)
    return matches


def collect_targets(include_output: bool, include_user_data: bool) -> list[Path]:
    targets: list[Path] = []

    targets.extend(REPO_ROOT / name for name in DEFAULT_DIRS)
    targets.extend(REPO_ROOT / name for name in DEFAULT_FILES)

    if include_output:
        targets.extend(REPO_ROOT / name for name in OPTIONAL_USER_DIRS)

    if include_user_data:
        targets.extend(REPO_ROOT / name for name in OPTIONAL_USER_FILES)

    for pattern in DEFAULT_PATTERNS:
        targets.extend(REPO_ROOT.glob(pattern))

    targets.extend(iter_pycache_dirs())

    unique: dict[Path, Path] = {}
    for target in targets:
        unique[target.resolve()] = target
    return sorted(unique.values(), key=lambda path: str(path).lower())


def remove_target(path: Path, dry_run: bool) -> str:
    if not path.exists():
        return "missing"
    if not is_safe_repo_path(path):
        return "unsafe"
    if dry_run:
        return "would remove"
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return "removed"


def main() -> int:
    args = parse_args()
    targets = collect_targets(args.include_output, args.include_user_data)

    print(f"Repository: {REPO_ROOT}")
    if args.dry_run:
        print("Mode: dry run")

    actions = {"removed": 0, "would remove": 0, "missing": 0, "unsafe": 0}
    for target in targets:
        result = remove_target(target, args.dry_run)
        actions[result] += 1
        if result != "missing":
            print(f"{result:12} {target.relative_to(REPO_ROOT)}")

    print()
    for result, count in actions.items():
        if count:
            print(f"{result}: {count}")

    return 1 if actions["unsafe"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
