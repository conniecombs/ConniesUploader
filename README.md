# Connie's Uploader Ultimate

![Project version badge showing v1.4.0](https://img.shields.io/badge/version-1.4.0-blue.svg)
![MIT License badge](https://img.shields.io/badge/license-MIT-green.svg)
![Supported platforms: Windows, Linux, and macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![Continuous integration workflow status: passing](https://github.com/conniecombs/ConniesUploader/actions/workflows/ci.yml/badge.svg?branch=main)
![Continuous delivery release workflow status: passing](https://github.com/conniecombs/ConniesUploader/actions/workflows/release.yml/badge.svg)
![Security scanning workflow status: passing](https://github.com/conniecombs/ConniesUploader/actions/workflows/security.yml/badge.svg?branch=main)
![Go programming language version 1.25](https://img.shields.io/badge/Go-1.25-00ADD8.svg)
![Python version 3.11 or higher required](https://img.shields.io/badge/Python-3.11+-3776AB.svg)

Connie's Uploader Ultimate is a desktop image-uploading tool with a CustomTkinter GUI and a Go sidecar for concurrent uploads. It supports batch uploads, gallery workflows, custom output templates, drag and drop, secure credential storage, and automated release builds for Windows, Linux, and macOS.

**Latest release:** v1.4.0 "User Experience Polish & Safer Upload Controls" (June 20, 2026)

## Screenshots

### Start With A Clear Drop Zone

The main screen opens directly into the upload workflow. New users get a large drop zone, centered Add Files and Add Folder actions, and host readiness feedback before they start.

![Connie's Uploader 1.4.0 empty upload queue with Pixhost selected, ready status, and centered Add Files and Add Folder actions](docs/assets/screenshots/empty-drop-zone.png)

### Organize Batches Automatically

Folders become separate upload batches with visible thumbnails, per-batch output templates, post targets, progress, and remove actions. Once files are present, the queue-level Add Files and Add Folder buttons move to the top toolbar.

![Connie's Uploader upload queue showing two image batches with thumbnails, templates, post target selectors, progress bars, and remove buttons](docs/assets/screenshots/batched-upload-queue.png)

### Keep Advanced Controls Out Of The Way

Everyday settings stay visible, while Worker Count and Thread Limit live together in Advanced App Settings. The app enforces the displayed ranges so workers stay within `1-16` and upload thread limits stay within `1-10`.

![Advanced App Settings expanded with Worker Count and Thread Limit controls above Pixhost upload settings](docs/assets/screenshots/advanced-app-settings.png)

### Catch Problems Before Upload

Import Checks and Upload Checks explain what needs attention inside the main window, with contextual actions for adding files, setting credentials, removing invalid files, opening problem folders, or retrying.

![Import Checks and Upload Checks panels showing rejected files, preflight warnings, and fix buttons](docs/assets/screenshots/import-upload-checks.png)

### Track Upload Activity Inline

The activity panel records the work as it happens: host readiness, queueing, active uploads, completed files, and progress. It can be hidden when users want the queue to take more space.

![Connie's Uploader upload progress view with uploaded, uploading, and queued rows plus a visible activity timeline](docs/assets/screenshots/activity-progress.png)

### Finish With Useful Next Actions

Completion summaries show uploaded and failed counts, generated output files, clipboard status, and next-step actions such as Open Folder, Copy Output, and Retry Failed.

![Upload completion summary showing uploaded and failed counts, generated files, clipboard status, and retry actions](docs/assets/screenshots/completion-summary.png)

### Customize Output Templates

The Template Editor lets users build BBCode, Markdown, HTML, ViperGirls posting, and custom output formats with built-in template categories, search, import/export, validation, duplicate/rename/delete actions, categorized placeholders, nested conditionals, custom `[for image]` loops, and previews that include rendered output plus raw generated text.

![Template Editor with BBCode formatting toolbar, gallery placeholders, editable template text, preview, restore, save, and save-as-new controls](docs/assets/screenshots/template-editor-v140.png)

## Features

- Batch upload images by file or folder, with each folder represented as its own upload group.
- Upload through the Go sidecar with worker pools, retry handling, rate limiting, and progress events.
- Select one or more cover images per batch, with optional auto-cover defaults for newly added files.
- Manage galleries for supported services and optionally create one gallery per folder.
- Generate BBCode, HTML, Markdown, and custom output formats with the template editor.
- Store credentials through the operating system keyring.
- Save output files to `Output/` and keep history under `~/.conniesuploader/history/`.
- Use dark, light, or system appearance modes.
- Auto-copy completed output to the clipboard.
- Integrate with ViperGirls forum posting workflows, including live thread-title names, target search, notes/tags, import/export, preview, confirmation, and posting history.

## Supported Services

The active upload plugins are:

- `imagebam.com`
- `imgur.com`
- `imx.to`
- `pixhost.to`
- `turboimagehost`
- `vipr.im`

## Latest Changelog

### v1.4.0 - User Experience Polish & Safer Upload Controls

Released June 20, 2026.

**Added**

- Added a real empty queue drop zone with primary Add Files and Add Folder actions.
- Added in-app import checks, upload preflight checks, activity history, and completion summaries.
- Added inline retry and failed-reason visibility for upload rows.

**Changed**

- Moved advanced worker and thread controls into a compact Advanced App Settings section.
- Rendered service settings from plugin schemas, including Imgur-friendly settings labels.
- Improved queue readability with clearer states, stable row actions, and reclaimed row space when previews are off.

**Fixed**

- Clamped worker counts to `1-16` and upload thread limits to `1-10` throughout the UI, settings, and upload job path.
- Ensured `build_uploader.bat --ci` can build the packaged executable automatically.
- Added recovery options for corrupted local templates.

Full history is available in [CHANGELOG.md](CHANGELOG.md).

## Installation

### Download a Release

Download the latest release from [GitHub Releases](https://github.com/conniecombs/ConniesUploader/releases/tag/v1.4.0).

Expected release artifacts:

- `ConniesUploader-v1.4.0-windows-x64.zip`
- `ConniesUploader-v1.4.0-linux-x64.tar.gz`
- `ConniesUploader-v1.4.0-macos-x64.zip`

Each release artifact includes a SHA256 checksum.

### Build from Source

Prerequisites:

- Python 3.11+
- Go 1.25+

Windows:

```bat
build_uploader.bat
```

Linux/macOS:

```bash
./build.sh
```

Makefile:

```bash
make build
```

Useful build-script options:

- `--clean` cleans build artifacts before building.
- `clean` removes build artifacts and exits.
- `--ci` runs without interactive pauses or opening `dist/`.

Local cleanup without a full build:

```bash
python scripts/maintenance/clean_generated.py --dry-run
python scripts/maintenance/clean_generated.py
```

The cleanup helper removes generated artifacts such as `build/`, `dist/`, `htmlcov/`, coverage files, sidecar binaries, PyInstaller spec files, and crash logs. It leaves `Output/`, `user_settings.json`, and legacy `user_templates.json` alone unless you pass the explicit `--include-output` or `--include-user-data` flags.

Manual development run on Windows PowerShell:

```powershell
go build -ldflags="-s -w" -o uploader.exe .
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Manual development run on Linux/macOS:

```bash
go build -ldflags="-s -w" -o uploader .
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

1. Set service credentials from `Tools > Set Credentials`.
2. Choose an image host from the service dropdown.
3. Add files or folders with `File > Add Files`, `File > Add Folder`, or drag and drop.
4. Adjust gallery, thumbnail, thread, and output settings as needed.
5. Click `Start Upload`.
6. Review generated output in `Output/` or the history directory.

Additional tools are available from the application menus:

- `Tools > Manage Galleries`
- `Tools > Template Editor`
- `Tools > ViperGirls Posting Targets`
- `Tools > ViperGirls Posting History`
- `Tools > Install Context Menu` on Windows
- `View > Execution Log`

## Configuration and Data

- Application settings are stored in `user_settings.json`.
- Credentials are stored through the system keyring.
- Session output is written to `Output/`.
- Persistent output history is written to `~/.conniesuploader/history/`.
- Custom templates are written to `~/.conniesuploader/templates.json`; legacy `user_templates.json` files are migrated automatically.
- Saved ViperGirls posting targets, including fetched thread titles, are written to `~/.conniesuploader/saved_threads.json`.
- ViperGirls posting history is written to `~/.conniesuploader/posting_history.json`.
- Runtime crash logs are written to `crash_log.log` when applicable.

## Architecture

Connie's Uploader uses a hybrid desktop architecture:

- `main.py` starts the Python GUI.
- `modules/ui/` contains the CustomTkinter interface.
- `modules/plugins/` contains service plugins and plugin helpers.
- `modules/sidecar.py` manages the Go sidecar process.
- `main.go` and `handlers.go` provide the Go sidecar entry point and request handlers.
- `core/` contains shared Go upload utilities such as validation, retry, rate limiting, HTTP helpers, and output handling.
- `services/` contains Go service integrations.
- `scripts/maintenance/` contains repository cleanup and maintenance helpers.
- `scripts/diagnostics/` contains local troubleshooting helpers that are not part of the app runtime.
- Python and Go communicate through JSON events over standard input and output.

Generated folders and runtime data are intentionally kept out of source control:

- Build output: `build/`, `dist/`, `uploader`, `uploader.exe`, `ConniesUploader.spec`
- Test output: `.coverage`, `htmlcov/`, `.pytest_cache/`
- Local app data: `Output/`, `user_settings.json`, legacy `user_templates.json`
- Runtime diagnostics: `crash_log*.log`

## CI, Security, and Releases

GitHub Actions workflows:

- [CI - Build and Test](.github/workflows/ci.yml)
- [Release - Build and Publish](.github/workflows/release.yml)
- [Security Scanning](.github/workflows/security.yml)

The CI workflow builds the Go sidecar on Windows, Linux, and macOS; runs Go vet and Go tests; installs Python dependencies; runs the Python test suite; checks dependencies with `govulncheck` and `pip-audit`; and runs Go/Python linting.

The release workflow builds Windows, Linux, and macOS artifacts, verifies that the sidecar is bundled, calculates SHA256 checksums, packages the artifacts, and publishes a GitHub release.

The security workflow runs CodeQL, gosec, govulncheck, Bandit, pip-audit, dependency review for pull requests, and TruffleHog secret scanning.

## Development

Common commands:

```bash
go test ./...
pytest tests/ -v
flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__
```

Build helpers:

```bash
make build
make quick
make clean
```

Maintenance and diagnostics:

```bash
python scripts/maintenance/clean_generated.py --dry-run
python scripts/diagnostics/check_plugins.py
python scripts/diagnostics/check_sidecar_location.py
```

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Build Troubleshooting](docs/guides/BUILD_TROUBLESHOOTING.md)
- [Plugin Creation Guide](docs/guides/PLUGIN_CREATION_GUIDE.md)
- [Repository Layout](docs/guides/REPOSITORY_LAYOUT.md)
- [Schema Plugin Guide](docs/guides/SCHEMA_PLUGIN_GUIDE.md)
- [Release Process](docs/releases/RELEASE_PROCESS.md)
- [Documentation Index](docs/README.md)

## Troubleshooting

**`uploader.exe` or `uploader` not found**

Build the Go sidecar with `go build -ldflags="-s -w" -o uploader.exe .` on Windows or `go build -ldflags="-s -w" -o uploader .` on Linux/macOS.

**Uploads fail immediately**

Check credentials, confirm the selected service settings, and open `View > Execution Log` for the sidecar error message.

**ViperGirls posting is blocked before upload**

Open `Tools > ViperGirls Posting Targets`, confirm the selected target still exists, and use `Validate` to check the thread ID. Upload Checks also offers direct buttons for credentials and target management when posting preflight fails.

**ViperGirls post fails after upload**

Open `Tools > ViperGirls Posting History` to copy the failed post text, copy the error, or open the target thread. Last-used timestamps update only after successful posts.

**Build fails**

Confirm Python 3.11+ and Go 1.25+ are installed, then rerun the appropriate build script with `--clean`.

**Dependency installation fails**

Recreate the virtual environment and reinstall from `requirements.txt`.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and pull request guidance.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgments

- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2)
- [goquery](https://github.com/PuerkitoBio/goquery)
- [loguru](https://github.com/Delgan/loguru)
- [logrus](https://github.com/sirupsen/logrus)
- [imaging](https://github.com/disintegration/imaging)

## Responsible Use

This tool is intended for personal use and legitimate content sharing. Users are responsible for following the terms of service for each image hosting platform they use.
