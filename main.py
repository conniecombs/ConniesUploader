# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Compatibility launcher for running Connie's Uploader from the repo root."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    frontend_root = repo_root / "frontend"
    frontend_main = frontend_root / "main.py"

    if not frontend_main.exists():
        raise FileNotFoundError(f"Frontend entry point not found: {frontend_main}")

    sys.path.insert(0, str(frontend_root))
    os.chdir(frontend_root)
    sys.argv[0] = str(frontend_main)
    runpy.run_path(str(frontend_main), run_name="__main__")


if __name__ == "__main__":
    main()
