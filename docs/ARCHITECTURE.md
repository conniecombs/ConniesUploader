# Architecture

## Current Status

- **Product Version:** v3.1.0
- **Architecture Version:** v3.1.0
- **Last Updated:** 2026-09-04

Connie's Uploader is a hybrid desktop app:

- Python owns the GUI, user settings, plugin discovery, templates, galleries, ViperGirls posting, website-specific request sequencing/parsing, and output generation.
- Go runs as a local sidecar process and owns concurrent transport execution, Python-provided rate limits, retries, generic HTTP request execution, multipart upload streaming, cookie/session mechanics, and thumbnail generation.
- Python and Go communicate through JSON events over standard input and standard output.

The upload model is plugin-driven. Python plugins build HTTP upload specifications with `build_http_request()`, and the Go sidecar executes those specs through the generic runner. All host-specific logic lives in Python. The Go sidecar has no knowledge of any specific image host or forum — it is a "dumb and fast" transport runner.

The Python/Go boundary is documented in [`TRANSPORT_CONTRACT.md`](TRANSPORT_CONTRACT.md).

## Active Services

The current auto-discovered upload plugins are:

- `imagebam.com`
- `imgur.com`
- `imx.to`
- `pixhost.cc`
- `turboimagehost`
- `vipr.im`

Plugin discovery is automatic through `frontend/modules/plugin_manager.py`, which scans `modules.plugins` with `pkgutil.iter_modules()`. New plugin files do not need to be registered in `frontend/modules/plugins/__init__.py`. Special/helper modules and files ending in `_legacy` are skipped.

## Runtime Flow

```text
main.py (in frontend/)
  -> modules/ui/main_window.py compatibility wrapper
  -> modules/ui/Main_Window/ organized main-window package
  -> modules/plugin_manager.py
  -> modules/plugins/<service>.py
  -> modules/upload_manager.py
  -> modules/sidecar.py
  -> Go sidecar (in backend/): main.go, handlers.go, core/
  -> sidecar events back to Python
  -> output generation, history, optional ViperGirls posting
```

For a typical upload:

1. The GUI collects selected files, service settings, template choice, gallery choice, cover selections, and optional ViperGirls targets.
2. Upload Checks validate obvious problems before work starts, including files, credentials, gallery settings, and posting targets.
3. The selected plugin validates configuration and builds a `HttpRequestSpec` when it supports the generic runner.
4. `UploadManager` sends upload jobs to `SidecarBridge`.
5. The Go sidecar applies Python-provided rate limits, executes the upload, retries transient transport failures, and emits correlated progress/result events. Existing upload plugins still use Go's generic parser compatibility shim to convert upload responses into result events.
6. Python stores results, generates template output, saves history, copies output when enabled, and queues optional ViperGirls posts.

## Python Responsibilities

### GUI and Workflow

- Main app shell and queue: `frontend/modules/ui/Main_Window/app.py` plus focused mixins under `frontend/modules/ui/Main_Window/`
- Compatibility import wrapper: `frontend/modules/ui/main_window.py`
- Drag and drop/file scanning: `frontend/modules/dnd.py`, `frontend/modules/file_handler.py`
- Settings persistence: `frontend/modules/settings_manager.py`
- Credentials: `frontend/modules/credentials_manager.py`
- Upload orchestration: `frontend/modules/upload_manager.py`
- Sidecar lifecycle/events: `frontend/modules/sidecar.py`

The GUI keeps user-facing controls synchronized with the upload job model. Worker Count is clamped to `1-16`, Thread Limit is clamped to `1-10`, and upload checks prevent or warn on invalid preflight state before starting work.

### Plugins

Plugins live in `frontend/modules/plugins/` and inherit from `ImageHostPlugin`.

Recommended plugin responsibilities:

- `id`, `name`, and `metadata`
- `settings_schema` for declarative service settings
- `validate_configuration()` for service-specific validation
- `build_http_request()` for generic sidecar uploads
- `prepare_group()` when a service needs per-batch setup such as gallery creation
- `finalize_batch()` when a service needs post-upload finalization

Legacy `initialize_session()` and `upload_file()` hooks remain for compatibility, but new upload services should prefer schema settings plus `build_http_request()`. New non-upload workflows should use raw sidecar transport requests and parse/validate responses in Python.

### Templates and Output

`frontend/modules/template_manager.py` stores custom templates at `~/.conniesuploader/templates.json` and migrates legacy `user_templates.json` files automatically.

The template engine supports:

- Basic placeholders such as `#url#`, `#thumb_url#`, `#all_images#`
- Batch/service/thread placeholders such as `#batch_name#`, `#folder_size#`, `#service#`, `#thread_name#`, `#thread_id#`
- Nested `[if placeholder]...[/if]` conditionals
- `[for image]...[/for]` loops
- `[for cover]...[/for]` loops
- Separator options for loop output
- Automatic multi-cover output through `#cover_images#`

### Gallery Manager

The Gallery Manager UI is backed by service/plugin code and normalized gallery records:

```python
{
    "service": "pixhost.cc",
    "id": "...",
    "name": "...",
    "url": "...",
    "upload_hash": "...",
    "raw": {...}
}
```

Gallery list/create flows distinguish unsupported service, missing credentials, login failure, parse failure, empty lists, and cached fallback results. Recent gallery data, pinned state, and last-used timestamps are stored at `~/.conniesuploader/gallery_cache.json`.

### ViperGirls Posting

ViperGirls automation is a post-upload workflow, not part of the image-host upload itself.

- Saved targets: `~/.conniesuploader/saved_threads.json`
- Posting history: `~/.conniesuploader/posting_history.json`
- Scheduled posts: `~/.conniesuploader/scheduled_posts.json`
- Thread IDs are parsed and validated before upload when posting is selected.
- Optional preview/confirmation can show batch name, target name, thread ID, and generated post content before posting.
- History rows can copy post text, copy errors, and open target threads.
Python owns the ViperGirls page workflow: it logs in, fetches the live reply form through the sidecar, parses the current HTML form, copies its fields, overrides the message/title fields, and sends Go only a resolved generic HTTP request to execute.

Scheduled posts are Python-owned too. The scheduler wakes periodically, loads pending records, performs the same form-aware ViperGirls login/post path, and updates each record to `posted` or `failed`.

## Go Responsibilities

### Sidecar Process

The Go sidecar is built as `uploader.exe` on Windows and `uploader` on Linux/macOS. In packaged releases, users normally never see it because PyInstaller bundles it inside the final executable.

Go owns:

- JSON event handling from Python
- Worker pool execution
- Python-provided rate limits and generic fallback limits
- Transport retry behavior
- Multipart upload construction
- Generic HTTP request execution (uploads and standalone requests)
- Cookie/session mechanics
- Thumbnail generation
- Legacy parser/pre-request/batch-resolve compatibility for existing upload specs

Go does **not** contain any host-specific knowledge. All service-specific behavior is defined by Python modules and plugins.

### Generic HTTP Runner

The generic runner supports two action types:

**`http_upload`** — File upload with multipart construction:
- Upload request specs from Python plugins
- Shared cookies for login/session workflows
- Correlated request IDs so stale sidecar events do not satisfy the wrong upload
- Legacy response-parser compatibility for current upload result events

**`http_request`** — Standalone (non-file) HTTP requests:
- One resolved HTTP request per Python call
- Form-encoded POST requests
- Cookie reuse through the sidecar cookie jar
- Optional raw `response_body`, `status_code`, and `final_url` return fields
- Python-owned response parsing and success/failure decisions

**`http_batch_resolve`** — Deferred batch result polling compatibility:
- Polls a result page with configurable delays
- Extracts per-file links using regex patterns
- Matches extracted links to original filenames

Regex selectors are supplied by plugin code. They should be compiled with graceful errors rather than process panics; this remains a fault-tolerance hardening item when touching the Go parser.

## Data Storage

| Data | Location |
| --- | --- |
| App settings | `~/.conniesuploader/user_settings.json` |
| Credentials | System keyring |
| Session output | `Output/` |
| Persistent output history | `~/.conniesuploader/history/` |
| Templates | `~/.conniesuploader/templates.json` |
| Legacy settings/templates | repo-local `user_settings.json` and `user_templates.json` migrated automatically |
| Gallery cache/pins/last used | `~/.conniesuploader/gallery_cache.json` |
| ViperGirls targets | `~/.conniesuploader/saved_threads.json` |
| ViperGirls posting history | `~/.conniesuploader/posting_history.json` |
| ViperGirls scheduled posts | `~/.conniesuploader/scheduled_posts.json` |
| Upload activity log | `~/.conniesuploader/activity.log` |
| Runtime crash logs | `crash_log*.log` |

Files under `~/.conniesuploader/` are user data and should not be committed. Generated build/test output such as `build/`, `dist/`, `htmlcov/`, `.coverage`, `uploader`, and `uploader.exe` should also stay out of source control.

## Security Model

Current strengths:

- Credentials are stored through the operating system keyring.
- Credentials are passed to the sidecar through local stdin events, not CLI arguments.
- TLS verification remains enabled.
- Python supplies host-specific sidecar rate limits for upload and forum posting paths.
- User JSON files use atomic-save/recovery patterns where practical.

Known hardening opportunities:

- Add stronger Go-side file path validation instead of relying only on Python validation.
- Replace any `regexp.MustCompile()` path that can receive plugin-provided patterns with `regexp.Compile()` and graceful error returns.
- Continue retiring legacy Go parser compatibility by moving upload response parsing into Python.
- Consider stricter plugin trust/sandboxing if third-party plugin loading becomes a supported user feature.

## Performance Characteristics

- Worker Count is user-configurable and clamped to `1-16`.
- Upload Thread Limit is user-configurable and clamped to `1-10`.
- The sidecar streams files rather than loading whole uploads into memory.
- Large batches are supported, with Python doing UI-friendly queue/progress updates and Go handling concurrent network work.
- Thumbnail preview generation is intentionally separate from upload execution.

## Testing Strategy

Current coverage includes both Python and Go tests:

- `cd frontend && pytest tests/ -v`
- `cd backend && go test ./...`
- `cd backend && go vet ./...`
- `cd frontend && flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__`
- CI also runs `govulncheck`, `pip-audit`, and Go/Python linting.

Important tested areas include plugin discovery, schema rendering, settings validation, sidecar behavior, template parsing/migration, Gallery Manager normalization/cache behavior, ViperGirls target/history behavior, upload preflight checks, build contracts, and Go-side upload helpers.

## Adding a New Service

Preferred path:

1. Create `frontend/modules/plugins/yourservice.py`.
2. Subclass `ImageHostPlugin`.
3. Add `id`, `name`, `metadata`, and `settings_schema`.
4. Implement `validate_configuration()` if the schema cannot express all rules.
5. Implement `build_http_request()` to return a generic sidecar spec.
6. Add focused tests for config validation and generated request shape.
7. Run `cd frontend && pytest tests/ -v` and `cd backend && go test ./...`.

Only add Go code for generic transport capability. Host parsing, website decisions, and response interpretation belong in Python.

## Roadmap

Near-term hardening:

- Gracefully handle malformed plugin regex patterns in Go.
- Add Go-side path bounds validation for upload file paths.
- Move upload result parsing out of the remaining compatibility shim and into Python.
- Keep documentation and screenshots synchronized with the current UI.
- Consider stricter plugin trust/sandboxing if third-party plugin loading becomes a supported user feature.

The current architecture is production-usable and plugin-driven. The Go sidecar is host-agnostic transport code; legacy upload parser hooks remain only as compatibility scaffolding.
