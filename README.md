# Connie's Uploader

![Current app build badge showing v3.1.0](https://img.shields.io/badge/app-v3.1.0-orange.svg)
![Latest tagged release badge showing v3.1.0](https://img.shields.io/badge/latest%20release-v3.1.0-blue.svg)
![MIT License badge](https://img.shields.io/badge/license-MIT-green.svg)
![Supported platforms: Windows, Linux, and macOS](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![Continuous integration workflow status: passing](https://github.com/conniecombs/ConniesUploader/actions/workflows/ci.yml/badge.svg?branch=main)
![Continuous delivery release workflow status: passing](https://github.com/conniecombs/ConniesUploader/actions/workflows/release.yml/badge.svg)
![Security scanning workflow status: passing](https://github.com/conniecombs/ConniesUploader/actions/workflows/security.yml/badge.svg?branch=main)
![Go programming language version 1.25.9 or higher](https://img.shields.io/badge/Go-1.25.9+-00ADD8.svg)
![Python version 3.11 or higher required](https://img.shields.io/badge/Python-3.11+-3776AB.svg)

Connie's Uploader is a desktop image-uploading tool with a CustomTkinter GUI and a Go sidecar for concurrent uploads. It supports batch uploads, gallery workflows, custom output templates, drag and drop, secure credential storage, ViperGirls posting workflows, and automated release builds for Windows, Linux, and macOS.

**Latest tagged release:** v3.1.0 "Folder Size Template Placeholder" (September 4, 2026)

**Current release branch:** `main`

## Screenshots

### Start With A Clear Drop Zone

The main screen opens directly into the upload workflow. New users get a large drop zone, centered Add Files and Add Folder actions, and host readiness feedback before they start.

![Connie's Uploader empty upload queue with Pixhost selected, ready status, and centered Add Files and Add Folder actions](docs/assets/screenshots/empty-drop-zone.png)

### Organize Batches Automatically

Folders become separate upload batches with visible thumbnails, per-batch output templates, post targets, progress, compact cover toggles, and selection-aware queue actions. Once files are present, the queue-level Add Files and Add Folder buttons move to the top toolbar.

![Connie's Uploader upload queue showing two image batches with thumbnails, templates, post target selectors, cover toggles, and progress bars](docs/assets/screenshots/batched-upload-queue.png)

### Keep Advanced Controls Out Of The Way

Everyday settings stay visible, while Worker Count and Thread Limit live together in Advanced App Settings. The app enforces the displayed ranges so workers stay within `1-16` and upload thread limits stay within `1-10`.

![Advanced App Settings expanded with Worker Count and Thread Limit controls above Pixhost upload settings](docs/assets/screenshots/advanced-app-settings.png)

### Catch Problems Before Upload

Import Checks and Upload Checks explain what needs attention inside the main window, with contextual actions for adding files, setting credentials, removing invalid files, opening problem folders, or retrying.

![Import Checks and Upload Checks panels showing rejected files, preflight warnings, and fix buttons](docs/assets/screenshots/import-upload-checks.png)

### Track Upload Activity

The activity panel records the work as it happens: host readiness, queueing, active uploads, completed files, and progress. `View > Activity Terminal` can also tail the persisted activity log in PowerShell during longer upload sessions.

![Connie's Uploader upload progress view with uploaded, uploading, and queued rows plus a visible activity timeline](docs/assets/screenshots/activity-progress.png)

### Finish With Useful Next Actions

Completion summaries show uploaded and failed counts, generated output files, clipboard status, and next-step actions such as Open Folder, Copy Output, and Retry Failed.

![Upload completion summary showing uploaded and failed counts, generated files, clipboard status, and retry actions](docs/assets/screenshots/completion-summary.png)

### Customize Output Templates

The Template Editor lets users build BBCode, Markdown, HTML, ViperGirls posting, and custom output formats with built-in template categories, search, import/export, validation, duplicate/rename/delete actions, categorized placeholders, nested conditionals, custom `[for image]` loops, and previews that include rendered output plus raw generated text.

![Template Editor with template search, duplicate rename delete import export actions, categorized image placeholders including Cover{s}, editable template text, preview, copy preview, restore, save, and save-as-new controls](docs/assets/screenshots/template-editor-v140.png)

### Manage Galleries With Clear State

The Gallery Manager can refresh host galleries, search and sort results, pin frequently used galleries, copy IDs or URLs, open known gallery links, assign a selected gallery to uploads, and fall back to clearly labeled cached results when a live refresh fails.

![Gallery Manager showing searchable galleries, pinned state, cache status, and copy/open/select actions](docs/assets/screenshots/gallery-manager.png)

## Features

- Batch upload images by file or folder, with each folder represented as its own upload group.
- Upload through the Go sidecar with worker pools, retry handling, rate limiting, and progress events.
- Select one or more cover images per batch, with optional auto-cover defaults for newly added files.
- Manage galleries for supported services, pin frequently reused galleries, use cached galleries when a live refresh fails, and optionally create one gallery per folder.
- Generate BBCode, HTML, Markdown, and custom output formats with the template editor.
- Store credentials through the operating system keyring.
- Save output files to `Output/` and keep history under `~/.conniesuploader/history/`.
- Use dark, light, or system appearance modes.
- Auto-copy completed output to the clipboard.
- Integrate with ViperGirls forum posting workflows, including live thread-title names, target search, notes/tags, import/export, preview, confirmation, scheduled posts, and posting history.

## Supported Services

The active upload plugins are:

- `imagebam.com`
- `imgur.com`
- `imx.to`
- `pixhost.cc`
- `turboimagehost`
- `vipr.im`

## Latest Changelog

### v3.1.0 - Folder Size Template Placeholder

Released September 4, 2026.

**Added**

- Added `#folder_size#` for templates, previews, ViperGirls post previews, and saved batch output.
- Rendered folder size as the total readable size of accepted files in the current batch, with up to two decimal places such as `714 KB`, `114 MB`, or `1.34 GB`.

**Changed**

- Bumped the app, build scripts, and active plugin metadata to `v3.1.0`.

Full history is available in [CHANGELOG.md](docs/CHANGELOG.md), and the full v3.1.0 release notes are available in [RELEASE_NOTES_v3.1.0.md](docs/releases/RELEASE_NOTES_v3.1.0.md).

### vBleedingEdge - Pixhost.cc & Import Performance Patch

Released July 28, 2026.

**Changed**

- Bumped the app, build scripts, and active plugin metadata to `vBleedingEdge`.
- Updated Pixhost from `pixhost.to` to `pixhost.cc` across upload, gallery, output, docs, and tests.
- Improved large-folder import responsiveness with background folder scanning, larger bounded UI batches, and deferred thumbnails.

**Fixed**

- Fixed Pixhost uploads and gallery creation/finalization for `api.pixhost.cc`.
- Preserved old `pixhost.to` saved settings, gallery cache records, selected galleries, validation, and upload thread settings by normalizing them to `pixhost.cc`.

Full history is available in [CHANGELOG.md](docs/CHANGELOG.md), and the full vBleedingEdge release notes are available in [RELEASE_NOTES_vBleedingEdge.md](docs/releases/RELEASE_NOTES_vBleedingEdge.md).

### v3.0.0 - Python-Owned Workflows & Generic Transport

Released July 12, 2026.

**Added**

- Added `Tools > Scheduled Posts` for persisted ViperGirls scheduled post records.
- Added `View > Activity Terminal` to tail `~/.conniesuploader/activity.log`.
- Added a release branch-difference record for the `Bleeding-Edge` compare against `main`.

**Changed**

- Promoted the app, build scripts, and active plugin metadata to `v3.0.0`.
- Completed the move toward Python-owned host workflows: Python now owns gallery/forum sequencing, parsing, and success checks while Go remains the generic transport runner.
- Moved host-specific default rate limits into Python job/request payloads.
- Updated the Go sidecar action surface around `http_upload`, raw `http_request`, `http_batch_resolve`, and thumbnail generation.

**Fixed**

- Fixed Turbo deferred result matching when host result pages return sanitized filenames.

The full v3.0.0 branch comparison is recorded in [BRANCH_DIFF_v3.0.0.md](docs/releases/BRANCH_DIFF_v3.0.0.md).

### v2.0.0 - Posting, Templates & Gallery Workflows

Released June 22, 2026.

**Added**

- Added ViperGirls posting workflows with saved targets, per-batch target selection, previews, optional confirmation, background posting, and posting history.
- Added a stronger Template Editor and parser with search, categories, import/export, nested conditionals, image loops, cover loops, and BBCode/HTML warnings.
- Added a dedicated Gallery Service and persistent Gallery Cache with pins, last-used timestamps, cached fallback display, and richer Gallery Manager controls.

**Changed**

- Reworked cover handling so selected covers render separately, use host-specific large thumbnail overrides, and stay out of regular `#all_images#` output.
- Replaced per-row Remove and Set Cover buttons with a compact `Cover` checkbox, selection-aware right-click actions, and queue keyboard shortcuts.
- Refreshed architecture, contributor, plugin, schema, build troubleshooting, repository layout, release, and tutorial documentation for the current app.

**Fixed**

- Improved Gallery Manager stale-response protection, inline error states, and cached fallback behavior.
- Improved ViperGirls target parsing, auto-poster failure reporting, posting-history recovery, and upload preflight blockers.
- Fixed Template Editor preview, validation, and toolbar output-format behavior for BBCode/forum workflows.

Full history is available in [CHANGELOG.md](docs/CHANGELOG.md).

## Installation

### Download a Release

Download the latest release from [GitHub Releases](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.1.0).

Expected release artifacts:

- `ConniesUploader-v3.1.0-windows-x64.zip`
- `ConniesUploader-v3.1.0-linux-x64.tar.gz`
- `ConniesUploader-v3.1.0-macos-x64.zip`

Each release artifact includes a SHA256 checksum.

### Build from Source

Prerequisites:

- Python 3.11+
- Go 1.25.9+ for local builds. CI currently builds with Go 1.26.5.

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

The cleanup helper removes generated artifacts such as `build/`, `dist/`, `htmlcov/`, coverage files, sidecar binaries, PyInstaller spec files, and crash logs. It leaves `Output/` and legacy repo-local user data files alone unless you pass the explicit `--include-output` or `--include-user-data` flags.

Manual development run on Windows PowerShell:

```powershell
cd backend
go build -ldflags="-s -w" -o ../uploader.exe .
cd ..
cd frontend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Manual development run on Linux/macOS:

```bash
cd backend
go build -ldflags="-s -w" -o ../uploader .
cd ..
cd frontend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Usage

1. Set service credentials from `Tools > Set Credentials`.
2. Choose an image host from the service dropdown.
3. Add files or folders with `File > Add Files`, `File > Add Folder`, or drag and drop.
4. Adjust gallery, thumbnail, thread, scheduling, and output settings as needed.
5. Click `Start Upload`.
6. Review generated output in `Output/` or the history directory.

Additional tools are available from the application menus:

- `Tools > Manage Galleries`
- `Tools > Template Editor`
- `Tools > ViperGirls Posting Targets`
- `Tools > ViperGirls Posting History`
- `Tools > Scheduled Posts`
- `Tools > Install Context Menu` on Windows
- `View > Execution Log`
- `View > Activity Terminal`

## Configuration and Data

- Application settings are stored in `~/.conniesuploader/user_settings.json`; legacy repo-local `user_settings.json` files are migrated there automatically.
- Credentials are stored through the system keyring.
- Session output is written to `Output/`.
- Persistent output history is written to `~/.conniesuploader/history/`.
- Custom templates are written to `~/.conniesuploader/templates.json`; legacy `user_templates.json` files are migrated automatically.
- Gallery cache, pinned galleries, and last-used gallery timestamps are written to `~/.conniesuploader/gallery_cache.json`.
- Saved ViperGirls posting targets, including fetched thread titles, are written to `~/.conniesuploader/saved_threads.json`.
- ViperGirls posting history is written to `~/.conniesuploader/posting_history.json`.
- ViperGirls scheduled posts are written to `~/.conniesuploader/scheduled_posts.json`.
- Upload activity events are written to `~/.conniesuploader/activity.log`.
- Runtime crash logs are written to `crash_log.log` when applicable.

## Architecture

Connie's Uploader uses a hybrid desktop architecture:

- `frontend/` contains the Python GUI (`main.py`) and all `modules/`.
- `backend/` contains the Go sidecar (`main.go`, `handlers.go`), along with the generic `core/` HTTP runner.
- `packaging/` contains PyInstaller build assets and custom hooks.
- `logs/` is ignored for optional local diagnostics.
- `scripts/maintenance/` contains repository cleanup and maintenance helpers.
- `scripts/diagnostics/` contains local troubleshooting helpers that are not part of the app runtime.
- Python and Go communicate through JSON events over standard input and output.

Generated folders and runtime data are intentionally kept out of source control:

- Build output: `build/`, `dist/`, `uploader`, `uploader.exe`, `packaging/ConniesUploader.spec`
- Test output: `.coverage`, `htmlcov/`, `.pytest_cache/`
- Local app data: `Output/`, legacy repo-local `user_settings.json` and `user_templates.json`, `~/.conniesuploader/*.json`, `~/.conniesuploader/history/`, `~/.conniesuploader/activity.log`
- Runtime diagnostics: `crash_log*.log`

## CI, Security, and Releases

GitHub Actions workflows:

- [CI - Build and Test](.github/workflows/ci.yml)
- [Release - Build and Publish](.github/workflows/release.yml)
- [Security Scanning](.github/workflows/security.yml)

The CI workflow builds the Go sidecar on Windows, Linux, and macOS with Go 1.26.5; runs Go vet and Go tests; installs Python dependencies; runs the Python test suite; checks dependencies with `govulncheck` and `pip-audit`; and runs Go/Python linting.

The release workflow builds Windows, Linux, and macOS artifacts, verifies that the sidecar is bundled, calculates SHA256 checksums, packages the artifacts, and publishes a GitHub release.

The security workflow runs CodeQL, gosec, govulncheck, Bandit, pip-audit, dependency review for pull requests, and TruffleHog secret scanning.

## Development

Common commands:

```bash
(cd backend && go test ./...)
(cd frontend && pytest tests/ -v)
(cd frontend && flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__)
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

- [Architecture](docs/ARCHITECTURE.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Changelog](docs/CHANGELOG.md)
- [User Tutorial](docs/guides/USER_TUTORIAL.md)
- [Build Troubleshooting](docs/guides/BUILD_TROUBLESHOOTING.md)
- [Plugin Creation Guide](docs/guides/PLUGIN_CREATION_GUIDE.md)
- [Repository Layout](docs/guides/REPOSITORY_LAYOUT.md)
- [Schema Plugin Guide](docs/guides/SCHEMA_PLUGIN_GUIDE.md)
- [Release Process](docs/releases/RELEASE_PROCESS.md)
- [Documentation Index](docs/README.md)

## Troubleshooting

**`uploader.exe` or `uploader` not found**

Build the Go sidecar with `cd backend && go build -ldflags="-s -w" -o ../uploader.exe .` on Windows or `cd backend && go build -ldflags="-s -w" -o ../uploader .` on Linux/macOS.

**Uploads fail immediately**

Check credentials, confirm the selected service settings, and open `View > Execution Log` for the sidecar error message.

**ViperGirls posting is blocked before upload**

Open `Tools > ViperGirls Posting Targets`, confirm the selected target still exists, and use `Validate` to check the thread ID. Upload Checks also offers direct buttons for credentials and target management when posting preflight fails.

**ViperGirls post fails after upload**

Open `Tools > ViperGirls Posting History` to copy the failed post text, copy the error, or open the target thread. Last-used timestamps update only after successful posts.

**Build fails**

Confirm Python 3.11+ and Go 1.25.9+ are installed, then rerun the appropriate build script with `--clean`.

**Dependency installation fails**

Recreate the virtual environment and reinstall from `frontend/requirements.txt`.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for development setup, coding standards, and pull request guidance.

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
