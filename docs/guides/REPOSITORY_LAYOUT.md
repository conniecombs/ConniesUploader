# Repository Layout

This project keeps source files, developer helpers, generated build output, and local user data separate so the repository stays easy to scan.

## Source Directories

- `frontend/` contains the Python application (`main.py`), `modules/`, UI, plugins, templates, and Python test suite (`tests/`).
- `backend/` contains the Go sidecar (`main.go`, `handlers.go`), along with `core/` logic and Go tests.
- `packaging/` contains PyInstaller build assets and custom hooks (`packaging/pyinstaller_hooks/`).
- `logs/` contains the application execution logs.
- `docs/` contains user, developer, release, and troubleshooting documentation.
- `docs/assets/screenshots/` contains tutorial and README screenshots.

The repository root intentionally keeps the primary `README.md`, build scripts, and cross-project configuration files. The `uploader*_test.go` files inside `backend/` use `package main` internals such as the sidecar HTTP client, job handlers, and package-level compatibility wrappers, so they stay beside `main.go` and `handlers.go`.

Large Python modules should be split only when a real ownership boundary is clear. In particular, `frontend/modules/ui/main_window.py` owns the main queue shell and `frontend/modules/dnd.py` owns queue selection, drag/reorder, and context-menu behavior. Move code out of those files only with focused contract updates and verification, not as a cosmetic layout cleanup.

## Developer Helpers

- `scripts/maintenance/` contains maintenance tasks such as license-header and cleanup helpers.
- `scripts/diagnostics/` contains local troubleshooting helpers, including plugin discovery and sidecar-location checks.

Common commands:

```bash
python scripts/maintenance/clean_generated.py --dry-run
python scripts/maintenance/clean_generated.py
python scripts/diagnostics/check_plugins.py
python scripts/diagnostics/check_sidecar_location.py
```

## Generated Artifacts

These files and folders are generated locally and should not be committed:

- `build/`
- `dist/`
- `htmlcov/`
- `.coverage` and `.coverage.*`
- `.pytest_cache/`
- `.build-tools/`
- `uploader` and `uploader.exe`
- `ConniesUploader` and `ConniesUploader.exe`
- `packaging/ConniesUploader.spec`
- `crash_log*.log`

Use `python scripts/maintenance/clean_generated.py` to remove these safely.

## Local User Data

These files are user-specific runtime data and should not be committed:

- `Output/`
- legacy repo-local `user_settings.json`
- legacy `user_templates.json`

The app stores current persistent data under `~/.conniesuploader/`, including:

- `user_settings.json`
- `templates.json`
- `gallery_cache.json`
- `saved_threads.json`
- `posting_history.json`
- `history/`

The cleanup helper leaves local user data alone by default. To remove it intentionally, pass `--include-output` or `--include-user-data`.
