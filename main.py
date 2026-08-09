# SPDX-License-Identifier: MIT
# Copyright (c) 2025 conniecombs

"""Compatibility launcher for running Connie's Uploader from the repo root."""

from __future__ import annotations

import os
import runpy
import sys
from importlib.util import find_spec
from pathlib import Path


REQUIRED_FRONTEND_MODULES = ("customtkinter", "tkinterdnd2")


def _repo_venv_python(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / "venv" / "Scripts" / "python.exe"
    return repo_root / "venv" / "bin" / "python"


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(
        os.path.abspath(os.fspath(right))
    )


def _missing_frontend_dependency() -> str | None:
    for module_name in REQUIRED_FRONTEND_MODULES:
        if find_spec(module_name) is None:
            return module_name
    return None


def _tkinterdnd_tcl_problem() -> str | None:
    try:
        import tkinter

        tcl_version = tkinter.Tcl().eval("info tclversion")
    except Exception as exc:
        return f"unable to initialize Tcl/Tk: {exc}"

    try:
        tcl_major = int(tcl_version.split(".", 1)[0])
    except ValueError:
        return None

    if tcl_major >= 9:
        return (
            f"tkinter uses Tcl/Tk {tcl_version}, but tkinterdnd2's bundled "
            "tkdnd extension requires Tcl/Tk 8.x"
        )
    return None


def _frontend_runtime_problem() -> str | None:
    missing_module = _missing_frontend_dependency()
    if missing_module is not None:
        return f"No module named {missing_module!r}"
    return _tkinterdnd_tcl_problem()


def _relaunch_with_repo_venv_if_needed(repo_root: Path, launcher_path: Path) -> None:
    runtime_problem = _frontend_runtime_problem()
    if runtime_problem is None:
        return

    venv_python = _repo_venv_python(repo_root)
    if venv_python.exists() and not _same_path(sys.executable, venv_python):
        os.execv(
            str(venv_python),
            [str(venv_python), str(launcher_path), *sys.argv[1:]],
        )

    requirements = repo_root / "frontend" / "requirements.txt"
    raise RuntimeError(
        f"Frontend runtime unavailable: {runtime_problem}. Install frontend dependencies with "
        f'"{sys.executable}" -m pip install -r "{requirements}", or run '
        f'"{venv_python}" "{launcher_path}".'
    )


def main() -> None:
    launcher_path = Path(__file__).resolve()
    repo_root = launcher_path.parent
    frontend_root = repo_root / "frontend"
    frontend_main = frontend_root / "main.py"

    if not frontend_main.exists():
        raise FileNotFoundError(f"Frontend entry point not found: {frontend_main}")

    _relaunch_with_repo_venv_if_needed(repo_root, launcher_path)

    sys.path.insert(0, str(frontend_root))
    os.chdir(frontend_root)
    sys.argv[0] = str(frontend_main)
    runpy.run_path(str(frontend_main), run_name="__main__")


if __name__ == "__main__":
    main()
