# Repository Layout

This project keeps source files, developer helpers, generated build output, and local user data separate so the repository stays easy to scan.

## Source Directories

- `modules/` contains the Python application, UI, plugin manager, plugins, template system, and sidecar bridge.
- `core/`, `services/`, `handlers.go`, and `main.go` contain the Go sidecar.
- `tests/` contains the Python test suite.
- `docs/` contains user, developer, release, and troubleshooting documentation.
- `docs/assets/screenshots/` contains tutorial and README screenshots.
- `pyinstaller_hooks/` contains packaging hooks required by the Windows, Linux, and macOS builds.

The repository root intentionally keeps the primary `README.md`, project entrypoints, build scripts, configuration files, and the root Go sidecar tests. The `uploader*_test.go` files use `package main` internals such as the sidecar HTTP client, job handlers, and package-level compatibility wrappers, so they should stay beside `main.go` and `handlers.go` unless the sidecar is first refactored into an importable package.

Large Python modules should be split only when a real ownership boundary is clear. In particular, `modules/ui/main_window.py` owns the main queue shell and `modules/dnd.py` owns queue selection, drag/reorder, and context-menu behavior. Move code out of those files only with focused contract updates and verification, not as a cosmetic layout cleanup.

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
- `ConniesUploader.spec`
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
