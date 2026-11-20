# Architecture

## Current Status

- **Product Version:** v3.1.3
- **Architecture Version:** v3.1.3
- **Last Updated:** 2026-11-18

Connie's Uploader is a hybrid desktop app:

- Python owns the GUI, user settings, plugin discovery, templates, galleries, ViperGirls posting, website-specific request sequencing/parsing, and output generation.
- Go runs as a local sidecar process and owns concurrent transport execution, Python-provided rate limits, retries, generic HTTP request execution, multipart upload streaming, cookie/session mechanics, and thumbnail generation.
- Python and Go communicate through JSON events over standard input and standard output.

The upload model is plugin-driven, with two upload paths during the v3.2.0 migration (see [Upload Paths](#upload-paths)):

- **Python path** (IMX, Pixhost, Imgur): the plugin builds one resolved request per file, Go sends it on an isolated transport session and returns the host's raw answer, and the plugin's `parse_upload_response()` decides what it means.
- **Legacy path** (Turbo, Vipr, ImageBam until they migrate, and every host when the hidden `legacy_upload_parsing` setting is on): the plugin's `build_http_request()` spec carries declarative login, parser and result-page hooks that Go executes.

All host-specific logic is defined in Python. The Go sidecar has no knowledge of any specific image host or forum — it is a "dumb and fast" transport runner.

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
3. The selected plugin validates configuration. On the Python path it builds one resolved upload request per file; on the legacy path it builds a `HttpRequestSpec`.
4. `UploadManager` sends upload jobs to `SidecarBridge` (on the Python path after opening a transport session and running the plugin's login step).
5. The Go sidecar validates each file as it reaches a worker, applies Python-provided rate limits, executes the upload, retries transient transport failures, and emits correlated progress/result events. Every job carries the batch id of this Start, and `Stop Upload` sends a `cancel` for that batch. On the Python path Go reports each host answer raw and the plugin's parser, on a small worker pool, turns it into the result; on the legacy path Go's parser compatibility shim does.
6. Python stores results, generates template output, saves history, copies output when enabled, and queues optional ViperGirls posts.

## Upload Paths

`UploadManager._send_job()` picks the path per job: a plugin whose class defines `parse_upload_response()` uses the Python path unless the settings file has `"legacy_upload_parsing": true` (an escape hatch kept until the legacy hooks are removed; it is not shown in the window).

Python path, per `_send_job()` call (one group's covers or other files):

1. `session_open` for the batch opens an isolated cookie jar in the sidecar (`modules/transport.py` `open_transport_session`). The wait ends at once on Stop or when the sidecar process dies.
2. On the dispatch thread, `plugin.open_upload_session(transport, config, creds)` logs in and fetches tokens through an `UploadTransport` bound to that session; its return value is the job's `session_values`.
3. `plugin.build_raw_upload_request(file, config, session_values, creds)` gives each file's literal request; one `http_upload` job with `raw_response`, `session_id` and `file_requests` goes to the sidecar (one job per file, each after the previous file was parsed, when the plugin's `upload_job_options()` asks for `sequential`).
4. The sidecar streams each upload with the usual stall, response-wait and no-resend protections and reports the answer as a raw `result` plus the non-terminal status `Uploaded` (rows show "Processing").
5. The event listener hands each raw result to a 4-thread post-processing pool (`modules/upload_sessions.py`), which calls `plugin.parse_upload_response(file, response, transport, session_values, session_state)` and reports the result and `Done`, or `error: <reason>` with credentials and session values redacted. Parsers may make follow-up requests on the session; `session_state` is a per-job dict that also feeds the job's `ResultPageMatcher` (`modules/result_matcher.py`).
6. Once the sidecar finished the job and every parse is done, `session_close`.

Stop cancels the batch: the sidecar closes the batch's sessions, aborts its uploads and follow-ups, and files whose parse ends after Stop report `Cancelled`. A sidecar crash ends the files still in the sidecar and the unsent files of a sequential job; the dead process's sessions are never closed. A failed session open or login fails the group's files with the reason. Building blocks for parsers (JSON paths, templates, the B1 failure messages, HTML selection) live in `modules/upload_results.py`; their parity with the legacy Go parser is tested against the shared fixtures in `backend/core/testdata/upload_parity.json`.

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

Row states are `pending`, `queued`, `uploading`, and the terminal states `success`, `failed`, and `cancelled`. A row counts toward batch completion the first time it enters a terminal state; the sidecar's `Failed` status followed by an `error` event only refines the failure reason. On the Python upload path the non-terminal `Uploaded` status (the host answered, its answer is being parsed) shows as "Processing". `Stop Upload` sets the cancel flag, sends the sidecar a `cancel` for the current batch id, and the window reaches a normal completion once every row is terminal. `Start` and `Retry Failed` refuse to run while an upload is in progress or being finalized.

### Plugins

Plugins live in `frontend/modules/plugins/` and inherit from `ImageHostPlugin`.

Recommended plugin responsibilities:

- `id`, `name`, and `metadata`
- `settings_schema` for declarative service settings
- `validate_configuration()` for service-specific validation
- Python upload path: `build_raw_upload_request()` and `parse_upload_response()`, plus `open_upload_session()` for a login or token step and `upload_job_options()` for `{"sequential": True}`
- `build_http_request()` for the legacy path (kept by migrated plugins as the `legacy_upload_parsing` fallback)
- `prepare_group()` when a service needs per-batch setup such as gallery creation
- `finalize_batch()` when a service needs post-upload finalization

Legacy `initialize_session()` and `upload_file()` hooks remain for compatibility. New upload services should use schema settings plus the Python upload path; the steps are in "How to migrate a host" in [`plans/V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md`](plans/V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md). New non-upload workflows should use raw sidecar transport requests and parse/validate responses in Python.

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

IMX upload entry points require saved username/password in addition to the API transport key. Gallery service operations require an API key, including listing, sync, creation, and deletion; manual website cookies do not bypass that application requirement. First-image creation also enforces the upload policy.

IMX automatic galleries use `modules/imx_api.py` to upload the first batch image once with `create_gallery=1`. `prepare_group()` returns that completed upload in its context; UploadManager emits its result and sends only the remaining images through the Go sidecar with the returned gallery ID. This synchronous first request uses a bounded timeout and is never automatically retried, because a repeated request creates another gallery. Gallery Manager uses the same API helper with a user-selected first image. Website listing/deletion remain separate, verify login explicitly, and report Anubis challenges as `browser_required`.

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

Code layout: `modules/viper_storage.py` owns the JSON files (targets, history, scheduled posts) behind one storage lock; `modules/viper_client.py` owns the forum workflow (titles, login, replies, scheduler) and talks only to the sidecar transport; `modules/viper_ui.py` owns the Tk windows. `modules/viper_api.py` is a compatibility facade that re-exports those names and refuses assignments, so a monkeypatch must target the owning module.

ViperGirls automation is a post-upload workflow, not part of the image-host upload itself.

- Saved targets: `~/.conniesuploader/saved_threads.json`
- Posting history: `~/.conniesuploader/posting_history.json`
- Scheduled posts: `~/.conniesuploader/scheduled_posts.json`
- Thread IDs are parsed and validated before upload when posting is selected.
- Optional preview/confirmation can show batch name, target name, thread ID, and generated post content before posting.
- History rows can copy post text, copy errors, and open target threads.
Python owns the ViperGirls page workflow: it logs in, fetches the live reply form through the sidecar, parses the current HTML form, copies its fields, overrides the message/title fields, and sends Go only a resolved generic HTTP request to execute.

Scheduled posts are Python-owned too. The scheduler wakes periodically, loads pending records, performs the same form-aware ViperGirls login/post path, and updates each record to `posted` or `failed` one at a time under the shared storage lock.

The AutoPoster is session-based. At upload start the window registers, in on-screen order, the batch indexes of groups that have a posting target. A group whose upload fails or is cancelled calls `skip`, so the worker never waits on a batch that will not post. Credentials come from a provider callable, so changes in the Credentials dialog apply to the next session. Replies are sent with `literal_values`, without transport retries, and with one re-login if the session was lost.

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
- Batch cancellation (`cancel` action keyed by `batch_id`), which also closes the batch's transport sessions
- Cookie/session mechanics, including an on-demand cookie reset for logins and isolated transport sessions (`session_open` / `session_close`, reaped after 30 idle minutes)
- Raw upload responses (`raw_response`) for the Python upload path
- Thumbnail generation, capped at 50 megapixels
- Legacy parser/pre-request/batch-resolve compatibility for upload specs of hosts not yet migrated

Go does **not** contain any host-specific knowledge. All service-specific behavior is defined by Python modules and plugins.

### Generic HTTP Runner

The generic runner supports two action types:

**`http_upload`** — File upload with multipart construction:
- Raw mode (`raw_response`): one literal request per file from `file_requests`, sent on the job's transport session (`session_id`), answered with the raw `response_body`, `status_code` and `final_url` whatever the status; `sequential` uploads the files one at a time in list order
- Legacy mode: upload request specs with parser hooks from Python plugins, shared cookies for login/session workflows, and response-parser compatibility for result events
- Correlated request IDs so stale sidecar events do not satisfy the wrong upload

**`http_request`** — Standalone (non-file) HTTP requests:
- One resolved HTTP request per Python call
- Form-encoded POST requests
- Cookie reuse through the sidecar cookie jar, or through a transport session's own jar with `generic_spec.session_id`
- Optional raw `response_body`, `status_code`, and `final_url` return fields
- Python-owned response parsing and success/failure decisions

**`session_open` / `session_close`** — Isolated transport sessions: a cookie jar of their own and a client that shares the global transport. Run on the request pool.

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
| Session activity | In memory only for the current app session |
| Runtime crash logs | `crash_log*.log` |

Files under `~/.conniesuploader/` are user data and should not be committed. Generated build/test output such as `build/`, `dist/`, `htmlcov/`, `.coverage`, `uploader`, and `uploader.exe` should also stay out of source control.

## Security Model

Current strengths:

- Credentials are stored through the operating system keyring.
- Credentials are passed to the sidecar through local stdin events, not CLI arguments.
- Each upload job carries only the credentials its plugin declares in `metadata["credentials"]`; other services' passwords and keys never reach the sidecar.
- TLS verification remains enabled.
- Python supplies host-specific sidecar rate limits for upload and forum posting paths.
- User JSON files use atomic-save/recovery patterns where practical.

Known hardening opportunities:

- Continue tightening Go-side file validation (paths are validated per file; the shared 100 MB cap and regular-file checks remain, see `TRANSPORT_CONTRACT.md`).
- Replace any `regexp.MustCompile()` path that can receive plugin-provided patterns with `regexp.Compile()` and graceful error returns.
- Retire the legacy Go parser compatibility by moving upload sessions and response parsing into Python ([`plans/V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md`](plans/V3_2_0_PYTHON_UPLOAD_PARSING_DESIGN.md)). Sessions, raw uploads and the Python path are in place and IMX, Pixhost and Imgur use them; Turbo, Vipr and ImageBam migrate next, after which the Go hooks can be removed.
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
- `cd frontend && flake8 main.py modules/ --max-line-length=120 --ignore=E203,E501,W503 --exclude=__pycache__`
- `cd frontend && black --check .`
- CI also runs `govulncheck`, `pip-audit`, and Go/Python linting.

Important tested areas include plugin discovery, schema rendering, settings validation, sidecar behavior, template parsing/migration, Gallery Manager normalization/cache behavior, ViperGirls target/history behavior, upload preflight checks, build contracts, and Go-side upload helpers.

## Adding a New Service

Preferred path:

1. Create `frontend/modules/plugins/yourservice.py`.
2. Subclass `ImageHostPlugin`.
3. Add `id`, `name`, `metadata`, and `settings_schema`.
4. Implement `validate_configuration()` if the schema cannot express all rules.
5. Implement `build_raw_upload_request()` and `parse_upload_response()` (plus `open_upload_session()` if the host needs a login or token); see "How to migrate a host" in the v3.2.0 design.
6. Add focused tests for config validation, the generated request, and the parser on recorded host answers.
7. Run `cd frontend && pytest tests/ -v` and `cd backend && go test ./...`.

Only add Go code for generic transport capability. Host parsing, website decisions, and response interpretation belong in Python.

## Roadmap

Near-term hardening:

- Gracefully handle malformed plugin regex patterns in Go.
- Add Go-side path bounds validation for upload file paths.
- Migrate Turbo, Vipr and ImageBam to the Python upload path, then remove the Go parser hooks (design milestones M4 and M5).
- Keep documentation and screenshots synchronized with the current UI.
- Consider stricter plugin trust/sandboxing if third-party plugin loading becomes a supported user feature.

The current architecture is production-usable and plugin-driven. The Go sidecar is host-agnostic transport code; legacy upload parser hooks remain only as compatibility scaffolding.
