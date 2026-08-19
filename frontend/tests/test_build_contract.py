import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_HOOKS_ARG = (
    '--additional-hooks-dir "..\\packaging\\pyinstaller_hooks"'
)
POSIX_HOOKS_ARG = (
    '--additional-hooks-dir "../packaging/pyinstaller_hooks"'
)


def _load_root_launcher():
    launcher_path = ROOT / "main.py"
    spec = importlib.util.spec_from_file_location(
        "root_main_launcher",
        launcher_path,
    )
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    return launcher


def test_root_main_py_launches_frontend_entrypoint(monkeypatch):
    launcher = _load_root_launcher()

    calls = {}

    def fake_chdir(path):
        calls["cwd"] = Path(path)

    def fake_run_path(path, run_name):
        calls["path"] = Path(path)
        calls["run_name"] = run_name

    monkeypatch.setattr(launcher.os, "chdir", fake_chdir)
    monkeypatch.setattr(launcher.runpy, "run_path", fake_run_path)
    monkeypatch.setattr(launcher.sys, "argv", ["main.py"])
    monkeypatch.setattr(launcher, "_frontend_runtime_problem", lambda: None)

    launcher.main()

    assert calls["cwd"] == ROOT / "frontend"
    assert calls["path"] == ROOT / "frontend" / "main.py"
    assert calls["run_name"] == "__main__"
    assert launcher.sys.argv[0] == str(ROOT / "frontend" / "main.py")


def test_root_main_py_relaunches_repo_venv_when_frontend_dependency_is_missing(
    tmp_path,
    monkeypatch,
):
    launcher = _load_root_launcher()
    repo_root = tmp_path
    launcher_path = repo_root / "main.py"
    launcher_path.write_text("# launcher", encoding="utf-8")
    venv_python = launcher._repo_venv_python(repo_root)
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    calls = {}

    def fake_execv(path, argv):
        calls["path"] = path
        calls["argv"] = argv
        raise RuntimeError("execv called")

    monkeypatch.setattr(
        launcher,
        "_frontend_runtime_problem",
        lambda: "tkinter uses Tcl/Tk 9.0",
    )
    monkeypatch.setattr(launcher.os, "execv", fake_execv)
    monkeypatch.setattr(launcher.sys, "argv", ["main.py", "--smoke"])
    monkeypatch.setattr(launcher.sys, "executable", str(repo_root / "python.exe"))

    with pytest.raises(RuntimeError, match="execv called"):
        launcher._relaunch_with_repo_venv_if_needed(repo_root, launcher_path)

    assert calls["path"] == str(venv_python)
    assert calls["argv"] == [str(venv_python), str(launcher_path), "--smoke"]


def test_system_tray_is_optional_when_pystray_is_missing(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pystray":
            raise ModuleNotFoundError("No module named 'pystray'")
        return original_import(name, *args, **kwargs)

    module_name = "system_tray_without_pystray"
    module_path = ROOT / "frontend" / "modules" / "ui" / "system_tray.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop(module_name, None)
    spec.loader.exec_module(module)

    manager = module.SystemTrayManager(main_window=object())

    assert module.pystray is None
    assert manager.icon is None


def test_windows_build_uses_local_pyinstaller_hooks_and_verifies_tkinter():
    script = (ROOT / "build_uploader.bat").read_text(encoding="utf-8")

    assert WINDOWS_HOOKS_ARG in script
    assert '/C:"_tkinter.pyd"' in script
    assert '/C:"_tcl_data"' in script
    assert '/C:"_tk_data"' in script
    assert '/C:"tcl86t.dll"' in script
    assert '/C:"tk86t.dll"' in script
    assert "Tkinter runtime bundled" in script
    assert "taskkill /F /IM" in script
    assert "Closing running %APP_NAME%.exe before rebuild" in script


def test_other_build_entrypoints_use_local_pyinstaller_hooks():
    build_script = (ROOT / "build.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert POSIX_HOOKS_ARG in build_script
    assert POSIX_HOOKS_ARG in makefile


def test_build_entrypoints_use_short_app_name_in_titles():
    for relative_path in ["build_uploader.bat", "build.sh", "Makefile"]:
        source = (ROOT / relative_path).read_text(encoding="utf-8")

        assert "Connie's Uploader Ultimate" not in source


def test_release_workflow_uses_local_pyinstaller_hooks():
    workflow_path = ROOT / ".github" / "workflows" / "release.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert '--specpath "../packaging"' in workflow
    assert workflow.count(POSIX_HOOKS_ARG) >= 3
    assert (
        workflow.count("cache-dependency-path: backend/go.sum") >= 3
    )
    assert (
        workflow.count("cache-dependency-path: frontend/requirements.txt") >= 3
    )


def test_customtkinter_hook_preserves_assets_and_adds_tcl_tk_binaries():
    hook_path = (
        ROOT / "packaging" / "pyinstaller_hooks" / "hook-customtkinter.py"
    )
    hook = hook_path.read_text(encoding="utf-8")

    assert 'collect_data_files("customtkinter")' in hook
    assert "tcltk_info.tcl_shared_library" in hook
    assert "tcltk_info.tk_shared_library" in hook
    assert 'binaries.append((library, "."))' in hook


def test_cleanup_helper_covers_generated_artifacts_and_user_data():
    cleanup_path = ROOT / "scripts" / "maintenance" / "clean_generated.py"
    cleanup = cleanup_path.read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for artifact in [
        "build",
        "dist",
        "htmlcov",
        ".coverage",
        "uploader.exe",
        "crash_log*.log",
    ]:
        assert artifact in cleanup

    assert "--include-output" in cleanup
    assert "--include-user-data" in cleanup
    assert "ConniesUploader.exe" in cleanup
    assert "taskkill" in cleanup
    assert "Output/" in gitignore
    assert "user_settings.json" in gitignore
    assert "user_templates.json" in gitignore
