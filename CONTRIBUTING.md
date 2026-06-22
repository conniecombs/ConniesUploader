# Contributing to Connie's Uploader Ultimate

Thank you for helping improve Connie's Uploader Ultimate. This guide explains how to set up the project, make changes safely, test them, and keep documentation current.

## Code of Conduct

- Be respectful and constructive.
- Keep bug reports and reviews focused on reproducible behavior.
- Preserve user data and generated files when testing locally.

## Development Setup

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/ConniesUploader.git
cd ConniesUploader
```

Set up Go:

```bash
go mod download
go build -ldflags="-s -w" -o uploader .
```

On Windows, build the sidecar as `uploader.exe`:

```powershell
go build -ldflags="-s -w" -o uploader.exe .
```

Set up Python:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the app from source:

```bash
python main.py
```

Prerequisites:

- Python 3.11 or newer. The Windows build script accepts Python 3.11 through 3.13 because the pinned PyInstaller version supports Python `<3.14`.
- Go 1.25.9 or newer for local builds. CI currently installs Go 1.26.4.

## Project Layout

```text
ConniesUploader/
├── main.py                    # Python GUI entry point
├── main.go                    # Go sidecar entry point
├── handlers.go                # Go sidecar request handlers
├── core/                      # Go upload utilities, HTTP runner, retry, rate limits, output
├── services/                  # Go compatibility/service helpers
├── modules/
│   ├── ui/                    # CustomTkinter windows and main app UI
│   ├── plugins/               # Auto-discovered image-host plugins
│   ├── gallery_cache.py       # Persistent gallery cache/pin/last-used storage
│   ├── gallery_manager.py     # Gallery Manager window
│   ├── gallery_service.py     # Gallery normalization/list/create service layer
│   ├── sidecar.py             # Go sidecar process bridge
│   ├── template_manager.py    # Template storage, validation, parser, rendering
│   ├── upload_manager.py      # Upload job orchestration
│   └── viper_api.py           # ViperGirls target/history UI and posting helpers
├── tests/                     # Python test suite
├── scripts/
│   ├── diagnostics/           # Local troubleshooting helpers
│   └── maintenance/           # Cleanup and maintenance helpers
├── pyinstaller_hooks/         # Local PyInstaller hooks
├── docs/                      # User, developer, release, and historical docs
├── .github/workflows/         # CI, release, and security workflows
├── build_uploader.bat         # Windows build script
├── build.sh                   # Linux/macOS build script
├── Makefile                   # Cross-platform build helpers
├── go.mod                     # Go dependencies
└── requirements.txt           # Python dependencies
```

Generated/user data should stay out of commits:

- `build/`, `dist/`, `htmlcov/`, `.coverage*`, `.pytest_cache/`
- `uploader`, `uploader.exe`, `ConniesUploader.spec`
- `Output/`, `user_settings.json`, legacy `user_templates.json`
- `~/.conniesuploader/*.json`
- `crash_log*.log`

Use the cleanup helper when local generated files get noisy:

```bash
python scripts/maintenance/clean_generated.py --dry-run
python scripts/maintenance/clean_generated.py
```

## Pull Request Workflow

1. Create a feature branch.

```bash
git checkout -b feature/short-description
```

2. Make a focused change.

- Follow existing patterns.
- Keep refactors separate unless they are needed for the fix.
- Add or update tests for behavioral changes.
- Update docs when behavior, setup, UI, workflows, or user-facing text changes.

3. Run relevant checks.

```bash
go test ./...
go vet ./...
pytest tests/ -v
flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__
```

4. Test the affected workflow manually.

- For UI changes, run `python main.py` and test the exact window/control you changed.
- For packaging changes, run the platform build script.
- For upload changes, test one small batch before larger batches.
- For ViperGirls or gallery changes, test missing credentials and invalid target/gallery states as well as the success path.

5. Commit and open a pull request.

```bash
git add .
git commit -m "type: short description"
git push origin feature/short-description
```

PR descriptions should include:

- What changed.
- Why it changed.
- What was tested.
- Screenshots for visible UI changes.
- Any known follow-up work.

## Coding Standards

### Python

- Follow PEP 8 and the local style.
- Use `snake_case` for functions/variables and `PascalCase` for classes.
- Prefer explicit error messages over silent failure.
- Use `getattr()`/`setattr()` for dynamic attributes rather than direct `__dict__` access.
- Specify `encoding="utf-8"` when reading text files in tests or tooling.
- Keep UI work on the Tkinter thread and long-running work off the UI thread.

### Go

- Run `gofmt`.
- Handle errors explicitly.
- Close response bodies.
- Prefer `regexp.Compile()` with graceful errors for dynamic/plugin-provided patterns.
- Keep generic runner behavior in `core/` when possible.
- Add Go service code only when a host workflow cannot be represented reasonably by a plugin HTTP spec.

### UI

- Keep common actions visible and advanced actions tucked behind clear affordances.
- Use inline error states where the user can act on them.
- Keep windows resizable when content can grow.
- Update screenshots and tutorial steps after visible UI changes.

## Adding or Updating Image Hosts

New hosts should be Python plugin-first.

1. Add `modules/plugins/yourservice.py`.
2. Subclass `ImageHostPlugin`.
3. Define `id`, `name`, `metadata`, and `settings_schema`.
4. Add `validate_configuration()` for service-specific rules.
5. Implement `build_http_request()` to return the generic sidecar HTTP spec.
6. Use `prepare_group()` for per-batch setup such as gallery creation.
7. Use `finalize_batch()` for service-specific finalization after uploads.
8. Add tests for generated request shape, validation, and any gallery/finalization behavior.

Do not register the plugin in `modules/plugins/__init__.py`; plugin discovery is automatic through `modules/plugin_manager.py`. Modules named `base`, `helpers`, `schema_renderer`, or ending in `_legacy` are skipped.

Only add Go code under `services/` when the generic HTTP runner cannot cover the service behavior. Document why Go support is necessary and keep the Go surface narrow.

## Testing Checklist

Run the automated checks that match the change:

```bash
pytest tests/ -v
go test ./...
go vet ./...
flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__
```

Manual workflow checks:

- Add files and folders.
- Reorder files, including multi-select drag/move behavior.
- Mark and clear cover images.
- Upload one small batch.
- Retry failed uploads when applicable.
- Create/select galleries when gallery code changed.
- Preview and save templates when template code changed.
- Validate ViperGirls targets and inspect posting history when posting code changed.
- Switch dark/light appearance for UI changes.

## Building for Testing

Preferred platform scripts:

```batch
build_uploader.bat --clean
```

```bash
./build.sh --clean
```

```bash
make build
```

Manual Windows PyInstaller build, matching the current build script:

```batch
go build -ldflags="-s -w" -o uploader.exe .

pyinstaller ^
  --noconsole ^
  --onefile ^
  --clean ^
  --noupx ^
  --name "ConniesUploader" ^
  --icon "logo.ico" ^
  --add-data "uploader.exe;." ^
  --add-data "logo.ico;." ^
  --additional-hooks-dir "pyinstaller_hooks" ^
  --collect-all tkinterdnd2 ^
  --collect-submodules modules.plugins ^
  --hidden-import modules.plugins.imx ^
  --hidden-import modules.plugins.pixhost ^
  --hidden-import modules.plugins.vipr ^
  --hidden-import modules.plugins.turbo ^
  --hidden-import modules.plugins.imagebam ^
  --hidden-import modules.plugins.imgur ^
  main.py
```

The packaged executable should include the Go sidecar, Tk/Tcl runtime, tkinterdnd2 assets, and all active plugin modules. Use `python scripts/diagnostics/check_sidecar_location.py` when diagnosing source-run sidecar lookup problems.

## Documentation Rules

Update documentation when you change:

- User-visible workflows or labels.
- Build, install, or release steps.
- Plugin architecture or schema behavior.
- Template syntax/placeholders.
- Gallery Manager or ViperGirls behavior.
- Stored file locations or migration behavior.
- Workflow or dependency versions.

Useful docs:

- [README.md](README.md)
- [CHANGELOG.md](CHANGELOG.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [User Tutorial](docs/guides/USER_TUTORIAL.md)
- [Plugin Creation Guide](docs/guides/PLUGIN_CREATION_GUIDE.md)
- [Schema Plugin Guide](docs/guides/SCHEMA_PLUGIN_GUIDE.md)
- [Build Troubleshooting](docs/guides/BUILD_TROUBLESHOOTING.md)
- [Release Process](docs/releases/RELEASE_PROCESS.md)

## Versioning

The project follows [Semantic Versioning](https://semver.org/):

- MAJOR: incompatible behavior or packaging changes
- MINOR: backward-compatible features
- PATCH: backward-compatible bug fixes

When preparing a release, update versioned files consistently and document the release in `CHANGELOG.md`.

## Questions

Open a GitHub issue for contributor questions that need project-owner input. Include the branch, operating system, Python version, Go version, command output, and relevant logs/screenshots.

By contributing, you agree that your contributions are licensed under the MIT License.
