# Repository Layout

This project keeps source files, developer helpers, generated build output, and local user data separate so the repository stays easy to scan.

## Source Directories

- `modules/` contains the Python application, UI, plugin manager, plugins, template system, and sidecar bridge.
- `core/`, `services/`, `handlers.go`, and `main.go` contain the Go sidecar.
- `tests/` contains the Python test suite.
- `docs/` contains user, developer, release, and troubleshooting documentation.
- `docs/assets/screenshots/` contains tutorial and README screenshots.
- `pyinstaller_hooks/` contains packaging hooks required by the Windows, Linux, and macOS builds.

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
- `user_settings.json`
- legacy `user_templates.json`

The app stores current persistent data under `~/.conniesuploader/`, including:

- `templates.json`
- `gallery_cache.json`
- `saved_threads.json`
- `posting_history.json`
- `history/`

The cleanup helper leaves local user data alone by default. To remove it intentionally, pass `--include-output` or `--include-user-data`.
