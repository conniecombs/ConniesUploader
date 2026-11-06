# v3.1.2 Lifecycle Hardening: Design

Status: **Approved design for v3.1.2. Implementation tracked in [V3_1_2_LIFECYCLE_HARDENING_PLAN.md](V3_1_2_LIFECYCLE_HARDENING_PLAN.md).**

Created: 2026-11-06
Baseline: `main` at `57c2554` (v3.1.1 plus CI hardening and the RAM-first archive plan)

## 1. Why

A full review of the repository at the baseline found that the upload, stop,
retry, and auto-posting lifecycle can wedge or misbehave in ways the test suite
does not cover. Three failures were reproduced against the built sidecar and
the poster module:

1. One filename containing `..` (for example `photo..jpg`) makes the Go
   validator reject the whole job with a single error event that carries no
   file path. Python only logs that event, so no row reaches a terminal state
   and the window stays in "Uploading..." until Clear List.
2. The auto-poster only ever pops the next batch index and never skips a
   missing one, while batch indexes are assigned across every group in the
   list. A "Do Not Post" group ahead of a posting group, a failed group, or a
   second upload in the same session leaves the worker spinning forever and
   every later run is refused as "Already running".
3. Go passes every form value of a generic request through template
   substitution, so any posted text containing `{...}` fails with "unresolved
   template tokens" and the whole post body is logged at ERROR level.

Code review confirmed further defects: failed uploads are counted twice so a
batch "completes" early; Stop Upload cannot stop anything and wedges the
window; Retry Failed and Start are re-entrant during an upload; the poster and
scheduler hold a stale credentials dict; three JSON files are read-modify-
written from several threads with no lock; any sidecar restart silently logs
the poster out; Go retries the forum reply POST; the close button hides the
window even when the tray icon failed; the crash-restart backoff sleeps while
holding the lock `send_cmd` needs; plus the low-severity items in section 8.

v3.1.2 fixes all of them, adds regression tests, removes dead code, aligns the
packaging paths and CI pins, and updates the documentation.

## 2. Decisions

| Decision | Choice |
| --- | --- |
| Stop Upload | Real cancellation: a `cancel` action in the sidecar protocol aborts in-flight and queued uploads for the batch. |
| Literal values in generic requests | A `literal_values` flag on `generic_spec`; old specs keep substitution. |
| Dead code | Delete `frontend/modules/controller.py`, `frontend/modules/validation.py`, their tests, `archive/legacy_plugins/`, and the root `VGPost.txt`. |
| Low-severity items | All included, tooling and docs too. |
| Release | Version `3.1.2` everywhere; no git tag is pushed by this work (a tag triggers the release workflow). |

## 3. Sidecar protocol changes (Go)

### 3.1 Batch identity and cancellation

- `JobRequest` gains `batch_id` (`json:"batch_id,omitempty"`). Python sets it
  on every upload job of one Start.
- New action `cancel` with `batch_id`. `ValidateJobRequest` accepts it without
  `service` or `files`. The stdin loop in `main.go` handles it directly (not
  through the worker pool) so it works while every worker is busy.
- A `core` registry maps `batch_id` to a cancellable context and a
  "cancelled" flag. `processUploadFiles` derives its per-file contexts from the
  batch context. When a queued job for a cancelled batch reaches a worker, it
  emits `status: Cancelled` for every file and `batch_complete`, and uploads
  nothing. Registry entries are released on `batch_complete`.
- A file whose context is cancelled reports `status: Cancelled` (not `Failed`
  or `Timeout`) and an `error` event explaining the cancellation.

### 3.2 Per-file validation

- `ValidateJobRequest` keeps the action, service, and "no files" checks and
  stops validating each path up front.
- `processUploadFiles` validates each path as it is dequeued. A bad path gets
  `status: Failed` plus an `error` event with the reason and is skipped; the
  rest of the job proceeds; `batch_complete` always fires.
- `ValidateFilePath` rejects `..` only as a whole path component, so
  `photo..jpg` and folders like `v1..v2` are accepted. The 100 MiB limit,
  regular-file check, and empty-path check stay.
- `generate_thumb` keeps validating its single path up front (unchanged
  behaviour, now via the same per-file helper).

### 3.3 Generic request flags

`GenericHttpRequestSpec` gains:

- `literal_values` (bool): skip template substitution for `url`, `headers`,
  and `form_fields`. Pre-request chains are unaffected.
- `timeout_seconds` (int): per-request context deadline. Values above the
  client ceiling (180 s) are clamped to it; zero means the default.
- `reset_cookies` (bool): replace the shared cookie jar before executing, so a
  login attempt cannot ride an older session. Upload pre-request clients use
  isolated jars and are not affected.

### 3.4 Thumbnail cap

`handleGenerateThumb` decodes the image header first and refuses images above
50 megapixels with the error "Image too large to preview".

### 3.5 Terminal event semantics (documented, not changed)

For a failed file Go emits `status: Failed` followed by `error` with the
reason. Python treats the second event as the reason for the first, never as a
second completion.

## 4. Upload manager (Python)

- `start_batch` generates a uuid `batch_id`; each job gets `id =
  f"{batch_id}:{n}"`. The manager keeps `current_batch_id` and a map of job id
  to its files.
- The event listener thread stops only on shutdown (`_stop_events`), never on
  `cancel_event`.
- Events whose `id` belongs to a job of another batch are dropped. Events
  without an id (sidecar log lines, `sidecar_stopped`) keep their current
  handling.
- `error` with a job id but no file path fails every still-active file of that
  job with `status: error: <msg>`.
- `batch_complete` fails any file of that job that never received a terminal
  event ("no result received from sidecar").
- `status: Cancelled` is forwarded as a terminal status.
- `cancel_batch()` sends `{"action": "cancel", "batch_id": ...}`. The dispatch
  thread, on seeing `cancel_event`, emits `Cancelled` for every file it has not
  dispatched instead of returning silently.
- The `sidecar_stopped` handler also fails files of the current batch that are
  still active (unchanged).

## 5. Main window

### 5.1 Terminal states and counting

- Row states: `pending`, `queued`, `uploading`, `success`, `failed`,
  `cancelled`. `cancelled` is terminal, drawn grey, counted toward completion,
  included in the completion summary ("N cancelled"), and retryable.
- `upload_count` increments only when a row moves from a non-terminal state to
  a terminal one. A later terminal event for a terminal row only refreshes the
  reason text.
- Group completion treats `cancelled` like `failed` (output skipped, failed
  group output generated).

### 5.2 Stop

`stop_upload` sets `cancel_event`, calls `upload_manager.cancel_batch()`, and
shows "Stopping...". Completion then follows the normal path once every row is
terminal; the summary says how many were cancelled.

### 5.3 Re-entrancy

- `start_upload` and `retry_failed` return with an activity message while
  `is_uploading` or `_finalizing` is true.
- The Retry Failed button is disabled while uploading or finalizing.
- `finish_upload` sets `_finalizing = True` and keeps `is_uploading = True`
  until `_on_upload_complete`, which clears both.

### 5.4 Window close

`WM_DELETE_WINDOW` hides to the tray only when `system_tray.is_available()`
(pystray imported, icon built, and the icon thread started); otherwise it calls
`graceful_shutdown`.

## 6. AutoPoster session model

- `begin_session(expected_indexes, credentials)` records, in order, the batch
  indexes of groups that have a posting target, stops and joins any previous
  worker, clears state, and snapshots credentials from the provider.
- `queue_post(index, ...)` stores content for a registered index.
  `skip(index, reason)` marks a registered index as skipped (failed or
  cancelled group). Unregistered indexes are ignored with a log line.
- The worker walks the registered indexes in order. For each it waits until the
  index is queued or skipped, posts or records the skip, and advances. It ends
  when every registered index is resolved, or when `cancel_event` or the
  poster's own stop event is set. Sleeps use `Event.wait` so stop is immediate.
- `start_processing` refuses only while a worker thread is alive.
- The main window passes `credentials_provider=lambda: self.creds`; the
  scheduler does the same. Credential changes apply at the next session or
  scheduler tick.
- Posting a batch records history exactly as today.

## 7. ViperGirls client and persistence

- `login` sets `reset_cookies: true` on the seed request. The success check
  stays, now valid because no older session can satisfy it.
- `post_reply` sends `retry_config: {"max_retries": 0}` and
  `timeout_seconds` equal to Python's wait; Python waits that long plus a
  five-second margin. If the reply form or the post response is a login page,
  the client re-logs in once and retries the fetch-and-post.
- `execute_transport_request` gains `retry: bool = True` and
  `timeout_seconds` plumbing; `build_transport_spec` gains `literal_values`
  and `reset_cookies`. The reply spec builder sets `literal_values: true`.
- `fetch_thread_title` goes through the sidecar transport. The target window
  runs title fetches on a worker thread and applies results with `after()`.
- A module-level re-entrant lock guards every load-modify-save on
  `saved_threads.json`, `posting_history.json`, and `scheduled_posts.json`.
  Writers use uniquely named temp files in the same directory before
  `os.replace`. The scheduler updates one post's status at a time (re-reading
  under the lock) rather than writing back a stale snapshot.
- `_normalize_loaded_record` and the import path keep the thread id but blank
  the URL when the host is not ViperGirls. Every "Open" path refuses URLs that
  fail the host check.
- `ViperGirlsAPI.close` and `is_logged_in` are removed along with the redundant
  bridge reassignments in the posting UI.

## 8. Gallery, bridge, and smaller items

- `GalleryCache` takes a class-level lock around load-modify-save and writes
  through uniquely named temp files.
- Gallery Manager result callbacks (`_handle_sync_all_result`,
  `_handle_create_result`, `_handle_delete_result`, the sync progress lambda)
  return early when the window no longer exists.
- IMX gallery service methods close their `requests.Session` in `finally`.
- `SidecarBridge._handle_crash` computes the delay under the lock but sleeps
  outside it; `_dispatch_event` blocks at most one second per terminal event.

## 9. Tooling, docs, cleanup, release

- Delete: `frontend/modules/controller.py`, `frontend/tests/test_controller.py`,
  `frontend/modules/validation.py`, `frontend/tests/test_validation.py`,
  `archive/legacy_plugins/`, `VGPost.txt`. Update `docs/README.md`,
  `docs/archive/README.md`, `docs/guides/USER_TUTORIAL.md`, and the stale
  RenameWorker comment in `app.py`.
- CI code-quality job: add `black --check` (black 26.10.1 from
  `frontend/requirements.txt`); pin golangci-lint to `v2.15.0`, gosec to
  `v2.30.0`, bandit to `1.9.4`. The repair and security workflows use the same
  pins.
- Apply black to `frontend/` in its own commit.
- `Makefile` `build-python` delegates to `scripts/maintenance/package_app.py`
  so one packaging path exists; `build.sh` and `build_uploader.bat` keep their
  current behaviour.
- Docs: `TRANSPORT_CONTRACT.md` (cancel, per-file validation, the three flags,
  terminal event semantics), `ARCHITECTURE.md` (poster session model, Stop,
  row states), README and `CONTRIBUTING.md` (Go 1.26 or newer, CI on 1.26.x),
  `BUILD_TROUBLESHOOTING.md`, `USER_TUTORIAL.md` (Stop and Cancelled rows).
- Version `3.1.2` in `config.APP_VERSION`, `Makefile`, `build.sh`,
  `build_uploader.bat`, plugin metadata, README badges and download names,
  `docs/CHANGELOG.md`, new `docs/releases/RELEASE_NOTES_v3.1.2.md`,
  `docs/releases/RELEASE_NOTES.md`, and `docs/README.md`.

## 10. Testing

Go (`backend/`):

- cancel action: in-flight upload aborts with `Cancelled`; queued job for a
  cancelled batch emits `Cancelled` per file and `batch_complete`.
- per-file validation: a job with one bad path uploads the others and emits
  `Failed` + `error` for the bad one; `photo..jpg` is accepted; `a/../b` is
  rejected.
- `literal_values`, `timeout_seconds`, `reset_cookies` behaviour.
- thumbnail cap.

Python (`frontend/tests/`):

- upload manager: stale-batch events dropped; `error` without file fails the
  job's files; `batch_complete` fails stragglers; cancel sends the action and
  marks undispatched files.
- main window: double terminal event counts once; Stop reaches a terminal
  state with cancelled rows; `start_upload`/`retry_failed` refuse while
  uploading or finalizing; close falls back to shutdown without a tray icon.
- auto-poster: the "Do Not Post ahead" and "second upload" scenarios post;
  skipped groups do not block; stop interrupts a sleep; credentials refresh.
- ViperGirls: login seed resets cookies; reply spec is literal and unretried;
  login-page response triggers one re-login; non-ViperGirls URLs are blanked;
  concurrent scheduler and UI writes do not lose updates.
- gallery cache: concurrent upserts keep both records.
- sidecar bridge: `send_cmd` is not blocked during restart backoff.
- build/CI contract: black in CI, pinned tool versions, Makefile delegates to
  the packaging script, version strings agree.

Every commit must pass `go vet`, `go test ./...`, `pytest`, `flake8`, and
`black --check`.

## 11. Out of scope

- Any part of the RAM-first archive plan.
- Changing how Go parses upload responses (legacy parser bridge).
- New image hosts or template features.
