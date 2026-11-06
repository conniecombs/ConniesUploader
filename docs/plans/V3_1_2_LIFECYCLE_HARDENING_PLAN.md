# v3.1.2 Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v3.1.2 with every defect from the November 2026 review fixed, regression-tested, and documented, on branch `ccr-c7a6caec-wpl3wv`.

**Architecture:** Go gains batch identity, a `cancel` action, per-file validation, and three generic-request flags; Python's upload manager keeps its listener alive and filters by batch; the main window gets a third terminal row state and re-entrancy guards; the auto-poster becomes session-based; shared JSON files get a lock. Tooling, docs, and version strings follow.

**Tech Stack:** Go 1.26 (`backend/`), Python 3.11+ with CustomTkinter (`frontend/`), pytest, `go test`, flake8, black 26.10.1, GitHub Actions.

**Spec:** `docs/plans/V3_1_2_LIFECYCLE_HARDENING_DESIGN.md`

## Global Constraints

- Every commit passes, from the repo root: `cd backend && go vet ./... && go test ./...`; `cd frontend && python -m pytest tests -q -o addopts='' && flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__ && black --check .`
- Production Go files must not contain host names (`frontend/tests/test_transport_contract.py::test_production_go_stays_host_agnostic` enforces it).
- New Python files carry the `# SPDX-License-Identifier: MIT` / `# Copyright (c) 2026 conniecombs` header; new Go files carry the `//` form.
- Version string everywhere is `3.1.2`; release date is `2026-11-06`; release name is "Lifecycle Hardening".
- No git tag is created or pushed.
- Commit messages end with the attribution lines given in the session's system reminder.

## Review Focus

Inputs the spec implies but the task tests do not otherwise cover; each has a pinned test in the task named.

1. Stop pressed before the dispatch thread has sent anything: every queued row must still end `Cancelled` and the window must reach a terminal state (Task 7, `test_stop_before_dispatch_marks_rows_cancelled`).
2. A `cancel` for an unknown or already finished `batch_id` must be a no-op that does not crash the sidecar (Task 3, `TestCancelUnknownBatchIsNoop`).
3. `timeout_seconds` larger than the client ceiling must clamp to 180 s, not disable the deadline (Task 4, `TestGenericRequestTimeoutClampsToClientCeiling`).
4. A posting target whose saved record has a blank URL (after the host filter blanks it) must still post by thread id (Task 13, `test_blanked_url_record_still_resolves_thread_id`).
5. A group whose every file was cancelled must mark its poster index skipped so later groups still post (Task 10, `test_cancelled_group_skips_poster_index`).

---

### Task 1: Black formatting and CI tool pins

**Files:**
- Modify: `.github/workflows/ci.yml` (code-quality job), `.github/workflows/security.yml` (gosec, bandit steps), `.github/workflows/repair.yml` (no pin change; verify only)
- Modify: `Makefile:66-90` (`build-python`)
- Modify: every file under `frontend/` that `black --check` lists
- Test: `frontend/tests/test_build_contract.py`

**Interfaces:**
- Produces: a CI code-quality job that runs `black --check .` in `frontend/`; `Makefile` target `build-python` that runs `scripts/maintenance/package_app.py`.

- [ ] **Step 1: Write the failing contract tests** in `frontend/tests/test_build_contract.py`

```python
def test_ci_code_quality_runs_black_and_pins_tools():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    security = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    assert "black==26.10.1" in ci
    assert "black --check ." in ci
    assert "golangci-lint@v2.15.0" in ci
    assert "gosec@v2.30.0" in security
    assert "bandit[sarif]==1.9.4" in security
    assert "@latest" not in ci and "@latest" not in security


def test_makefile_delegates_packaging_to_shared_script():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "scripts/maintenance/package_app.py" in makefile
    assert "--add-data \"../$(GO_OUTPUT)" not in makefile
```

Change `test_other_build_entrypoints_use_local_pyinstaller_hooks` to assert `POSIX_HOOKS_ARG` only in `build.sh` (the Makefile no longer invokes PyInstaller directly).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && python -m pytest tests/test_build_contract.py -q -o addopts=''`
Expected: the two new tests FAIL on the first assert.

- [ ] **Step 3: Edit the workflows and Makefile**

In `ci.yml` code-quality: replace `golangci-lint@latest` with `golangci-lint@v2.15.0`; after the flake8 step add `pip install black==26.10.1` and `black --check .` (working-directory `frontend`). In `security.yml`: `gosec@v2.30.0`; `pip install "bandit[sarif]==1.9.4"`. In the Makefile, `build-python: build-go` becomes a single recipe line `$(PYTHON) scripts/maintenance/package_app.py`; drop the PyInstaller flag block and `PYINSTALLER_FLAGS`.

- [ ] **Step 4: Format the frontend**

Run: `cd frontend && black .` then `flake8 main.py modules/ --max-line-length=120 --ignore=E501,W503 --exclude=__pycache__` and `python -m pytest tests -q -o addopts=''`.
Expected: black reformats 26 files; flake8 clean; all tests pass.

- [ ] **Step 5: Commit**

```bash
git add -A frontend .github Makefile
git commit -m "chore: enforce black in CI, pin lint tools, unify packaging path"
```

---

### Task 2: Per-file validation and the `..` component check (Go)

**Files:**
- Modify: `backend/core/validate.go`
- Modify: `backend/handlers.go:129-210` (`processUploadFiles`)
- Create: `backend/core/validate_test.go`, `backend/events_capture_test.go`, `backend/uploader_validation_test.go`

**Interfaces:**
- Produces: `func captureSidecarEvents(t *testing.T, run func()) []OutputEvent` in `backend/events_capture_test.go` (swaps `os.Stdout` for a pipe, runs `run`, decodes one JSON `OutputEvent` per line; used by Tasks 3 and 5).
- `core.ValidateJobRequest` no longer validates upload paths; `core.ValidateFilePath` is called per file by `processUploadFiles`.

- [ ] **Step 1: Write the failing core tests** in `backend/core/validate_test.go`

```go
func TestValidateFilePathAcceptsDoubleDotInsideName(t *testing.T) // writes t.TempDir()/"photo..jpg", expects nil
func TestValidateFilePathRejectsParentComponent(t *testing.T)     // dir/"../x.jpg" -> error containing "path traversal"
func TestValidateJobRequestDoesNotStatUploadFiles(t *testing.T)   // http_upload with Files ["/nonexistent/a.jpg"] -> nil error
```

- [ ] **Step 2: Write the failing handler test** in `backend/uploader_validation_test.go`

`TestUploadJobSkipsInvalidFileAndUploadsTheRest`: httptest server returning `{"status":"success","data":{"image_url":"u","thumbnail_url":"t"}}`; job with `Files: [goodTmpFile, "/nonexistent/bad.jpg"]`, `HttpSpec` using the server, `Config{"threads":"1"}`; capture events; assert one `result` for the good file, a `status` `Failed` and an `error` whose `FilePath` is the bad file, and exactly one `batch_complete`.

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && go test ./... -run 'TestValidateFilePath|TestValidateJobRequestDoesNotStat|TestUploadJobSkipsInvalid'`
Expected: FAIL (`photo..jpg` rejected; whole job rejected).

- [ ] **Step 4: Implement**

`ValidateFilePath`: replace the substring check with a loop over `strings.Split(filepath.ToSlash(filePath), "/")` rejecting a component equal to `..`. `ValidateJobRequest`: for `http_upload` keep only `len(job.Files) == 0`; keep per-path validation for `generate_thumb`. In `processUploadFiles`' worker loop, before `limiter.acquire()`: `if err := core.ValidateFilePath(fp); err != nil { status Failed; error "Invalid file: " + err.Error(); continue }`.

- [ ] **Step 5: Run the Go suite**

Run: `cd backend && go vet ./... && go test ./...`
Expected: PASS. (Existing tests that pass nonexistent files to `handleJob` only assert no panic.)

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "fix(sidecar): validate upload files individually and allow '..' inside names"
```

---

### Task 3: Batch registry and `cancel` action (Go)

**Files:**
- Create: `backend/core/batch.go`, `backend/core/batch_test.go`
- Modify: `backend/core/types.go` (`JobRequest.BatchID`), `backend/core/validate.go` (accept `cancel`), `backend/handlers.go` (`handleJob`, `processUploadFiles`, `processFileGeneric`), `backend/main.go` (stdin loop)
- Create: `backend/uploader_cancel_test.go`

**Interfaces:**
- Produces in `core`:
  - `func RegisterBatch(batchID string) (context.Context, func())` — context cancelled by `CancelBatch`; the returned func releases the registration. Empty id returns `context.Background()` and a no-op.
  - `func CancelBatch(batchID string) bool` — cancels the live context (if any), records the id as cancelled, returns true if the id was live.
  - `func BatchCancelled(batchID string) bool`
- `JobRequest.BatchID string \`json:"batch_id,omitempty"\``
- `processFileGeneric(fp string, job *JobRequest)` keeps its signature and delegates to `processFileGenericCtx(ctx context.Context, fp string, job *JobRequest)`.
- Event contract: cancelled files emit `status: "Cancelled"` then `error` with `Msg: "Upload cancelled"`.

- [ ] **Step 1: Write failing core tests** in `backend/core/batch_test.go`

```go
func TestCancelBatchCancelsRegisteredContext(t *testing.T) // RegisterBatch("b1"); CancelBatch("b1") == true; ctx.Err() == context.Canceled
func TestBatchCancelledPersistsForLaterJobs(t *testing.T)   // CancelBatch("b2") == false; BatchCancelled("b2") == true
func TestCancelUnknownBatchIsNoop(t *testing.T)             // CancelBatch("") == false; CancelBatch("nope") == false; no panic
```

- [ ] **Step 2: Write failing handler tests** in `backend/uploader_cancel_test.go`

- `TestCancelActionAbortsInFlightUpload`: httptest handler blocks on a channel; run `handleJob` for batch `"b-live"` in a goroutine; wait for the server to receive the request; `handleJob(JobRequest{Action:"cancel", BatchID:"b-live"})`; unblock; captured events contain `status Cancelled` for the file and one `batch_complete`.
- `TestQueuedJobForCancelledBatchIsSkipped`: `handleJob(cancel "b-queued")` first, then an upload job for `"b-queued"` whose server handler calls `t.Fatal` if reached; events are one `Cancelled` per file plus `batch_complete`.
- `TestValidateJobRequestAcceptsCancel`: `ValidateJobRequest(&JobRequest{Action:"cancel", BatchID:"x"}) == nil` and `Action:"cancel"` with empty `BatchID` returns an error.

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && go test ./... -run 'Batch|Cancel'`
Expected: FAIL (undefined symbols).

- [ ] **Step 4: Implement**

`core/batch.go`: a mutex-guarded `map[string]*batchEntry{ctx, cancel, refs int}` plus `cancelled map[string]bool`. `handleJob`: `case "cancel": core.CancelBatch(job.BatchID); sendJobEvent(log "Batch cancelled: <id>")`. `main.go` loop: handle `job.Action == "cancel"` before `jobQueue <- job`. `processUploadFiles`: `batchCtx, release := core.RegisterBatch(job.BatchID); defer release`; if `core.BatchCancelled(job.BatchID)` emit `Cancelled` per file and `batch_complete`, return; in the worker loop check `batchCtx.Err()` before acquiring the limiter and emit `Cancelled`; processor signature becomes `func(context.Context, string, *JobRequest)`. `processFileGenericCtx`: `ctx, cancel := context.WithTimeout(parent, core.ClientTimeout)`; in both the error branch and the `ctx.Done()` branch, if `parent.Err() == context.Canceled` emit `Cancelled`/`Upload cancelled` instead of `Failed`/`Timeout`.

- [ ] **Step 5: Run the Go suite with the race detector**

Run: `cd backend && go vet ./... && go test -race ./...`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(sidecar): add batch ids and a cancel action for in-flight uploads"
```

---

### Task 4: Generic request flags and thumbnail cap (Go)

**Files:**
- Modify: `backend/core/types.go` (`GenericHttpRequestSpec`), `backend/core/http.go:1027-1190` (`ExecuteGenericRequest`), `backend/handlers.go` (`handleHttpRequest`, `handleGenerateThumb`), `backend/main.go` (`initHTTPClient`)
- Create: `backend/core/cookies.go`, `backend/core/cookies_test.go`
- Test: `backend/core/http_test.go`, `backend/uploader_test.go`

**Interfaces:**
- `GenericHttpRequestSpec` fields: `LiteralValues bool \`json:"literal_values,omitempty"\``, `TimeoutSeconds int \`json:"timeout_seconds,omitempty"\``, `ResetCookies bool \`json:"reset_cookies,omitempty"\``.
- `core.SwappableJar` implementing `http.CookieJar` with `func NewSwappableJar() *SwappableJar` and `func (j *SwappableJar) Reset()`; `core.ResetCookieJar(client *http.Client)` resets when `client.Jar` is a `*SwappableJar`.
- `core.RequestTimeout(seconds int) time.Duration` — `ClientTimeout` when `seconds <= 0`, else `min(seconds*time.Second, ClientTimeout)`.
- `maxThumbnailPixels = 50_000_000` in `handlers.go`; error message `"Image too large to preview"`.

- [ ] **Step 1: Write failing tests**

In `backend/core/http_test.go`:
```go
func TestExecuteGenericRequestLiteralValuesKeepsBraces(t *testing.T)      // form field "Set {HD}" arrives verbatim at the server
func TestExecuteGenericRequestSubstitutesWhenNotLiteral(t *testing.T)     // unchanged behaviour: "{missing}" -> error
func TestGenericRequestTimeoutClampsToClientCeiling(t *testing.T)         // RequestTimeout(999) == ClientTimeout; RequestTimeout(0) == ClientTimeout; RequestTimeout(7) == 7s
```
In `backend/core/cookies_test.go`: `TestSwappableJarResetDropsCookies` (set a cookie, `Reset()`, `Cookies(u)` empty) and `TestResetCookieJarIgnoresPlainJars` (a `cookiejar.Jar` client is left untouched).
In `backend/uploader_test.go`: `TestHandleHttpRequestResetCookiesStartsFresh` (server sets cookie on `/a`; second job with `ResetCookies: true` to `/b` sees no `Cookie` header) and `TestGenerateThumbRejectsOversizedImage` (build a PNG from a 1×1 `image/png` encode, overwrite the IHDR width/height at byte offsets 16–23 with 8000, recompute CRC32 over bytes 12–28 into 29–32; expect an `error` event with `Msg == "Image too large to preview"`).

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && go test ./... -run 'Literal|Timeout|SwappableJar|ResetCookie|Oversized'`
Expected: FAIL.

- [ ] **Step 3: Implement**

`ExecuteGenericRequest`: a local `resolve := func(s string) (string, error)` that returns `s, nil` when `spec.LiteralValues`, else `substituteValues(s, extractedValues)`; use it for URL, headers, and form fields (both the initial body and the retry re-build). `handleHttpRequest`: `if spec.ResetCookies { core.ResetCookieJar(client) }`; `context.WithTimeout(context.Background(), core.RequestTimeout(spec.TimeoutSeconds))`. `initHTTPClient`: `Jar: core.NewSwappableJar()`. `handleGenerateThumb`: `image.DecodeConfig` on the open file, reject when `Width*Height > maxThumbnailPixels`, `f.Seek(0, io.SeekStart)`, then decode as before.

- [ ] **Step 4: Run the Go suite**

Run: `cd backend && go vet ./... && go test -race ./...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(sidecar): literal values, request timeouts, cookie reset, thumbnail size cap"
```

---

### Task 5: Transport helper flags (Python)

**Files:**
- Modify: `frontend/modules/transport.py`
- Test: `frontend/tests/test_transport_contract.py`

**Interfaces:**
- `build_transport_spec(url, method="GET", headers=None, form_fields=None, use_cookies=True, include_response_body=True, include_transport_metadata=True, literal_values=False, reset_cookies=False) -> dict` — adds `"literal_values": True` / `"reset_cookies": True` only when set.
- `execute_transport_request(spec, *, service="", timeout=30.0, bridge=None, rate_limits=None, retry=True) -> TransportResponse` — sets `spec["timeout_seconds"] = ceil(timeout)` when absent, waits `timeout + 5.0` on the bridge, and sends `payload["retry_config"] = {"max_retries": 0}` when `retry` is False.

- [ ] **Step 1: Write failing tests** in `test_transport_contract.py`

```python
def test_transport_spec_flags_are_opt_in():        # default spec lacks literal_values/reset_cookies; set -> True
def test_transport_request_sends_timeout_and_margin():  # spec["timeout_seconds"] == 30 and bridge timeout == 35.0
def test_transport_request_can_disable_retries():   # retry=False -> payload["retry_config"] == {"max_retries": 0}; default has no retry_config
```
Use a `FakeBridge` whose `request_sync(payload, timeout)` records both and returns `{"status": "success", "data": {}}`.

- [ ] **Step 2: Run to verify failure** — `cd frontend && python -m pytest tests/test_transport_contract.py -q -o addopts=''` → FAIL.

- [ ] **Step 3: Implement** the two signatures above in `transport.py`.

- [ ] **Step 4: Run** the same file plus `tests/test_viper_targets.py`; the existing `test_vipergirls_post_reply_uses_live_reply_form_fields` now fails on `fetch_timeout == 30` — update it to `fetch_timeout == 35` and `submit_timeout == 65`, and assert `fetch_spec["timeout_seconds"] == 30`, `spec["timeout_seconds"] == 60`.

- [ ] **Step 5: Commit** — `git commit -m "feat(transport): literal, cookie-reset, timeout and no-retry options"`

---

### Task 6: Upload manager batch identity, listener survival, cancel

**Files:**
- Modify: `frontend/modules/upload_manager.py` (`__init__`, `start_batch`, `_dispatch_jobs`, `_send_job`, `_process_events`)
- Create: `frontend/tests/test_upload_manager.py`

**Interfaces:**
- `UploadManager.current_batch_id: str | None`
- `UploadManager.start_batch(pending_by_group, cfg, creds) -> str` (returns the batch id)
- `UploadManager.cancel_batch() -> None` — sends `{"action": "cancel", "batch_id": <id>}` when a batch is active.
- `UploadManager._handle_event(data: dict) -> None` — the body of the listener loop, callable directly in tests.
- Job payloads carry `"id": f"{batch_id}:{n}"` and `"batch_id": batch_id`.

- [ ] **Step 1: Write failing tests** in `test_upload_manager.py` (monkeypatch `upload_manager.SidecarBridge.get` to a `FakeBridge` with `add_listener`, `remove_listener`, `send_cmd` recording payloads; construct `UploadManager(progress_q, result_q, threading.Event())`; register a job via `um._register_job("b1:0", ["/a.jpg", "/b.jpg"])`, which Step 3 adds)

```python
def test_events_from_other_batches_are_dropped()            # {"id": "zzz:0", "type": "result", "file": "/a.jpg"} -> result_q empty
def test_error_without_file_fails_every_active_file_of_job()  # error id b1:0 no file -> two ("status", fp, "error: Invalid job: ...") and two ("", "") results
def test_batch_complete_fails_stragglers()                   # result for /a.jpg then batch_complete -> /b.jpg gets "error: no result received from sidecar"
def test_cancelled_status_is_forwarded()                     # status Cancelled -> ("status", fp, "Cancelled")
def test_cancel_batch_sends_cancel_action()                  # um.current_batch_id = "b1"; um.cancel_batch() -> bridge.sent[-1] == {"action": "cancel", "batch_id": "b1"}
def test_listener_keeps_running_after_cancel_event()         # cancel_event.set(); um._stop_events not set -> _process_events loop condition still true (assert on the extracted predicate um._listener_should_run())
def test_dispatch_marks_undispatched_files_cancelled()       # cancel_event set before _dispatch_jobs -> every file gets ("status", fp, "Cancelled") and an empty result
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_upload_manager.py -q -o addopts=''` → FAIL.

- [ ] **Step 3: Implement**

Add `self._job_files: Dict[str, List[str]]`, `self.current_batch_id`, `_register_job(job_id, files)`, `_listener_should_run() -> bool` (`not self._stop_events.is_set()`). `start_batch` creates `uuid4().hex`, clears `_job_files`, returns it. `_send_job` takes a `job_id` (counter per batch) and adds `id`/`batch_id`. `_process_events` loops on `_listener_should_run()` and calls `_handle_event`. `_handle_event`: drop events with an `id` not in `_job_files`; `error` with id and no file fails active files of that job; `batch_complete` fails stragglers with `"error: no result received from sidecar"` and deletes the job entry. `_dispatch_jobs`: on cancel, emit `Cancelled` + empty result for every remaining file instead of `return`/`break`.

- [ ] **Step 4: Run** `tests/test_upload_manager.py tests/test_imx_flow.py tests/test_main_window_contract.py` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(upload): keep the sidecar listener alive, scope events to the batch, add cancel"`

---

### Task 7: Main window terminal states, Stop, and re-entrancy

**Files:**
- Modify: `frontend/modules/ui/Main_Window/runtime.py` (`_process_progress_queue:218-290`, `_reset_row_for_retry:486`, `_retry_file:498`, `_update_group_progress:584`, `finish_upload:630`, `_on_upload_complete:673`, `_build_completion_summary:695`, `stop_upload:802`, `retry_failed:1044`, `clear_list:1057`)
- Modify: `frontend/modules/ui/Main_Window/upload_checks.py:56` (`start_upload` guard), `frontend/modules/ui/Main_Window/layout.py:495` (`_refresh_queue_action_buttons`), `frontend/modules/ui/Main_Window/app.py:131` (`self._finalizing = False`)
- Test: `frontend/tests/test_main_window_contract.py`

**Interfaces:**
- `TERMINAL_ROW_STATES = frozenset({"success", "failed", "cancelled"})` in `runtime.py`.
- `RuntimeMixin._apply_terminal_status(fp: str, row: dict, status_text: str) -> None` — maps `Done`→`success`, `Cancelled`→`cancelled`, `Failed`/`error:*`→`failed`; increments `upload_count` only on a non-terminal→terminal transition; refreshes the reason text otherwise. Cancelled colour `#8E8E93`, status label `Cancelled`, reason `Upload cancelled.`
- `self._finalizing: bool`; `finish_upload` sets it and leaves `is_uploading` True; `_on_upload_complete` clears both.
- `_build_completion_summary()` adds `"cancelled_count"`; `status_text` is `"Upload complete: N uploaded, F failed, C cancelled."` when either count is non-zero (omit a zero part), else the existing wording.
- `stop_upload()` also calls `self.upload_manager.cancel_batch()`.

- [ ] **Step 1: Write failing tests** (reuse the setup of the existing test that feeds `("status", fp, "error: ...")` into `_process_progress_queue`; find it with `grep -n "error:" tests/test_main_window_contract.py`)

```python
def test_failed_then_error_status_counts_once()             # upload_count == 1 after both events; row reason is the error text
def test_cancelled_status_is_terminal_and_retryable()       # state "cancelled", counted, _retry_file accepts it
def test_stop_before_dispatch_marks_rows_cancelled()        # app.stop_upload() -> upload_manager.cancel_batch called; feed ("status", fp, "Cancelled") for each row -> finish_upload invoked via update_ui_loop predicate (upload_count >= upload_total)
def test_completion_summary_counts_cancelled()               # status_text == "Upload complete: 1 uploaded, 1 failed, 1 cancelled."
def test_start_upload_refuses_while_uploading_or_finalizing() # is_uploading True -> no start_batch call, activity message; same with _finalizing True
def test_retry_failed_refuses_while_uploading()
def test_finish_upload_keeps_is_uploading_until_complete()   # after finish_upload(): is_uploading True, _finalizing True; after _on_upload_complete(): both False
def test_retry_button_disabled_while_uploading()             # _refresh_queue_action_buttons(False) with is_uploading True -> btn_retry_failed state "disabled"
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_main_window_contract.py -q -o addopts='' -k "counts_once or cancelled or refuses or finalizing or retry_button"` → FAIL.

- [ ] **Step 3: Implement** per the Interfaces block; `_update_group_progress` counts `cancelled` as done and as failed for output purposes; `clear_list` resets `_finalizing`.

- [ ] **Step 4: Run** the whole frontend suite → PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(ui): count each row once, add Cancelled state, make Stop cancel, block re-entrant starts"`

---

### Task 8: Window close falls back to shutdown without a tray icon

**Files:**
- Modify: `frontend/modules/ui/system_tray.py`, `frontend/modules/ui/Main_Window/app.py:74-76`
- Test: `frontend/tests/test_main_window_contract.py`, `frontend/tests/test_build_contract.py:86` (existing tray test must keep passing)

**Interfaces:**
- `SystemTrayManager.is_available() -> bool` — icon built and the icon thread started and alive. `start()` stores the thread in `self._thread`.
- `UploaderApp._on_close_request() -> None` — `withdraw()` when `self.system_tray.is_available()`, else `graceful_shutdown()`; bound to `WM_DELETE_WINDOW` in `_init_window`.

- [ ] **Step 1: Write failing tests**: `test_close_hides_when_tray_available` and `test_close_shuts_down_without_tray` (app via `UploaderApp.__new__`, `system_tray = SimpleNamespace(is_available=lambda: ...)`, `withdraw`/`graceful_shutdown` replaced by recording lambdas); `test_system_tray_is_available_only_after_start` in `test_build_contract.py` (pystray stubbed with a fake `Icon` whose `run` blocks on an event).

- [ ] **Step 2: Run to verify failure.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run the suite → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "fix(ui): shut down on close when the tray icon is unavailable"`

---

### Task 9: AutoPoster session model

**Files:**
- Rewrite: `frontend/modules/auto_poster.py`
- Create: `frontend/tests/test_auto_poster.py`
- Test (keep passing): `frontend/tests/test_viper_targets.py::test_auto_poster_*`

**Interfaces:**
- `AutoPoster(credentials: Mapping[str, str] | Callable[[], Mapping[str, str]], saved_threads_data: dict)`
- `begin_session(expected_indexes: Sequence[int]) -> None` — stops and joins any live worker (3 s), clears queue, stores the order, snapshots credentials via the provider.
- `queue_post(batch_index: int, content: str, thread_name: str, batch_name: str = "") -> None` — ignores unregistered indexes and `"Do Not Post"` with a log line.
- `skip(batch_index: int, reason: str) -> None` — resolves a registered index without posting; logs the reason and writes no history entry.
- `start_processing(is_uploading_callback, cancel_event) -> None` — refuses only while the worker thread is alive.
- `stop() -> None` — sets the stop event, joins up to 3 s.
- `reset() -> None` — alias for `begin_session([])`.
- `is_running` property — worker thread alive.
- Worker: for each expected index in order, wait (polling `Event.wait(0.5)` on the stop event) until queued or skipped; once `is_uploading_callback()` is False, an index still unresolved after 2 s is recorded as failure `"no output generated"` and skipped.

- [ ] **Step 1: Write failing tests** in `test_auto_poster.py` (monkeypatch `viper_api.ViperGirlsAPI` with a fake whose `post_reply` appends to a list; `POST_COOLDOWN_SECONDS = 0.01`; `_record_history_item` stubbed)

```python
def test_do_not_post_group_ahead_does_not_block()        # begin_session([1]); queue 0 "Do Not Post", queue 1 -> posted ["123"]; worker exits
def test_second_session_posts_batch_zero_again()         # session 1 posts index 0; begin_session([0]) again; posts again; is_running False at the end
def test_skipped_index_lets_later_index_post()           # expected [0,1]; skip(0, "upload failed"); queue 1 -> posted
def test_unresolved_index_after_uploads_end_is_failed()  # expected [0]; is_uploading False, nothing queued -> history failure "no output generated" within 3 s
def test_stop_interrupts_waiting_worker()                # expected [0]; start; stop() returns in < 1 s and thread dead
def test_credentials_provider_is_read_at_session_start() # provider returns {} then creds; begin_session after change -> login called with new creds
def test_cancelled_group_skips_poster_index()            # (Review Focus 5) skip(idx, "cancelled") resolves the index
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Rewrite `auto_poster.py`** per the Interfaces block; keep `_resolve_thread_id`, `_target_url`, `_record_history_item`, `_record_all_pending_failures`, `_mark_target_used` as they are (tests in `test_viper_targets.py` use them).

- [ ] **Step 4: Run** `tests/test_auto_poster.py tests/test_viper_targets.py` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "fix(posting): session-based auto-poster that never waits on unregistered batches"`

---

### Task 10: Wire the poster session into the main window

**Files:**
- Modify: `frontend/modules/ui/Main_Window/upload_checks.py:149-177`, `frontend/modules/ui/Main_Window/runtime.py` (`generate_failed_group_output:956`, `_update_group_progress`), `frontend/modules/ui/Main_Window/app.py:186` (`AutoPoster(lambda: self.creds, ...)`, drop the stale RenameWorker comment)
- Test: `frontend/tests/test_main_window_contract.py`

**Interfaces:**
- `start_upload` computes `expected = [g.batch_index for g in sorted_groups if g in pending_by_group and g.selected_thread not in ("", None, "Do Not Post")]` and calls `self.auto_poster.begin_session(expected)` instead of `reset()`.
- `generate_failed_group_output` calls `self.auto_poster.skip(group.batch_index, "upload failed")` when the group has a posting target (also reached for cancelled rows).

- [ ] **Step 1: Write failing tests**: `test_start_upload_registers_only_posting_groups_in_order` (fake poster records `begin_session` arg `[1]` for groups [DoNotPost, Target]); `test_failed_group_output_skips_poster_index`; `test_cancelled_group_skips_poster_index` (all rows `cancelled` → `skip` called).

- [ ] **Step 2: Run to verify failure.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run the suite → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "fix(ui): register posting batches with the auto-poster per session"`

---

### Task 11: ViperGirls client: cookie reset, no-retry literal post, re-login

**Files:**
- Modify: `frontend/modules/viper_api.py` (`build_vipergirls_reply_spec:817`, `ViperGirlsAPI:1015-1085`), `frontend/modules/ui/Main_Window/posting.py:91-105`, `frontend/modules/ui/scheduled_posts_window.py:184-186`
- Test: `frontend/tests/test_viper_targets.py`

**Interfaces:**
- `build_vipergirls_reply_spec(...)` returns a spec with `"literal_values": True`.
- `_is_vipergirls_login_page(body: str) -> bool` — true when the body contains `vb_login_username` and not `logout.php`.
- `ViperGirlsAPI.login(username, login_value) -> bool` — seed request built with `reset_cookies=True`; stores `self._credentials = (username, login_value)` on success.
- `ViperGirlsAPI.post_reply(thread_id, message) -> bool` — fetch with `timeout=30`; submit with `timeout=60, retry=False`; if the fetched page or the submit response is a login page and credentials are stored, `login` once and retry the fetch-and-submit once.
- Removed: `ViperGirlsAPI.close`, `is_logged_in`; the `viper_client.bridge = SidecarBridge.get()` / `self.api.bridge = self.bridge` reassignments.

- [ ] **Step 1: Write failing tests**

```python
def test_login_seed_resets_cookies()                    # bridge.requests[0] spec["reset_cookies"] is True
def test_reply_spec_is_literal_and_unretried()          # spec["literal_values"] True; submit payload["retry_config"] == {"max_retries": 0}
def test_post_reply_relogs_in_once_on_login_page()      # responses: login-page html, seed, login ok, form html, "Thank you for posting" -> True, 5 requests
def test_post_reply_does_not_loop_on_repeated_login_page()  # login page twice -> False, no more than 5 requests
```

- [ ] **Step 2: Run to verify failure.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run `tests/test_viper_targets.py` → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "fix(posting): fresh-session login, literal unretried replies, one re-login on session loss"`

---

### Task 12: Shared-file locking and per-post scheduler updates

**Files:**
- Modify: `frontend/modules/viper_api.py` (`save_saved_threads:409`, `save_posting_history:606`, `append_posting_history`, `save_scheduled_posts:692`, `add_scheduled_post:707`, `cancel_scheduled_post:725`, `mark_thread_target_used:531`, `ViperGirlsPostScheduler:881-975`), `frontend/modules/gallery_cache.py` (`save:49`, every load-modify-save method), `frontend/modules/ui/Main_Window/app.py:196` (scheduler gets `lambda: self.creds`)
- Test: `frontend/tests/test_viper_targets.py`, `frontend/tests/test_gallery_service.py`

**Interfaces:**
- `viper_api._STORAGE_LOCK = threading.RLock()`; `viper_api._atomic_write_json(path: str, payload: Any) -> None` (unique temp file via `tempfile.NamedTemporaryFile(dir=dirname, prefix=basename + ".", suffix=".tmp", delete=False)`, then `os.replace`).
- `viper_api.set_scheduled_post_status(post_id: str, status: str, error: str = "") -> dict | None` — load, update one record, save, all under the lock.
- `ViperGirlsPostScheduler(creds: Mapping | Callable[[], Mapping], event_queue=None)`; `_credentials() -> dict`.
- `GalleryCache._LOCK = threading.RLock()` (class attribute) and the same unique-temp-file write.

- [ ] **Step 1: Write failing tests**

```python
def test_scheduler_does_not_clobber_posts_added_mid_run(tmp_path, monkeypatch)  # fake post_reply calls add_scheduled_post("post-2"); afterwards both post-1 (posted) and post-2 (pending) exist
def test_scheduler_reads_credentials_from_provider(tmp_path, monkeypatch)
def test_concurrent_saved_thread_updates_keep_both(tmp_path, monkeypatch)        # 20 threads calling mark_thread_target_used on distinct names; all last_used_at set
def test_gallery_cache_concurrent_upserts_keep_all_records(tmp_path)             # 50 threads upsert distinct ids; records_for_service returns 50
```

- [ ] **Step 2: Run to verify failure** (the clobber and concurrency tests fail intermittently today; run with `-p no:randomly` and repeat 3×).

- [ ] **Step 3: Implement.**  - [ ] **Step 4: Run the suite → PASS.**

- [ ] **Step 5: Commit** — `git commit -m "fix(storage): lock shared JSON files and update scheduled posts one at a time"`

---

### Task 13: Target URL host filter and open guards

**Files:**
- Modify: `frontend/modules/viper_api.py` (`_normalize_loaded_record:300-360`, `load_saved_threads`, import path near `:497`, `open_url:1549`, `open_target:2063`), `frontend/modules/ui/Main_Window/posting.py` (open target path)
- Test: `frontend/tests/test_viper_targets.py`

**Interfaces:**
- `viper_api.safe_target_url(url: str, thread_id: str) -> str` — returns `url` when `_is_supported_vipergirls_url(url)` and it has a scheme, else `_canonical_thread_url(thread_id)` when `thread_id`, else `""`.
- `viper_api.open_supported_url(url: str) -> bool` — opens with `webbrowser.open` only when `safe_target_url(url, "") == url` and non-empty; returns whether it opened.

- [ ] **Step 1: Write failing tests**: `test_loaded_records_blank_foreign_urls` (record `{"url": "https://attacker.example/x", "thread_id": "123"}` → url becomes `https://vipergirls.to/threads/123`), `test_file_url_is_rejected_on_import`, `test_open_supported_url_refuses_foreign_hosts` (monkeypatched `webbrowser.open` not called), `test_blanked_url_record_still_resolves_thread_id` (AutoPoster `_resolve_thread_id` works with blank url).

- [ ] **Step 2–4: fail, implement, pass.**

- [ ] **Step 5: Commit** — `git commit -m "fix(posting): never open non-ViperGirls URLs from saved or imported targets"`

---

### Task 14: Thread title fetch through the sidecar, off the Tk thread

**Files:**
- Modify: `frontend/modules/viper_api.py` (`fetch_thread_title:192`, `ViperToolsWindow.save_target:1568`, `refresh_target_names:1621`)
- Test: `frontend/tests/test_viper_targets.py::test_fetch_thread_title_uses_vipergirls_headers` (rewrite), new tests

**Interfaces:**
- `fetch_thread_title(url: str, timeout: int = THREAD_TITLE_TIMEOUT_SECONDS, bridge=None) -> str` — GET via `build_transport_spec` with the existing `User-Agent`/`Referer` headers and `execute_transport_request(service="vipergirls.to", rate_limits=VIPERGIRLS_RATE_LIMIT)`; returns `""` on failure. The `session` parameter is removed; `requests` import stays only if still used elsewhere (remove if not).
- `ViperToolsWindow._run_in_background(work: Callable[[], T], done: Callable[[T], None], buttons: Sequence) -> None` — disables `buttons`, runs `work` on a daemon thread, re-enables and calls `done` via `self.after(0, ...)`.
- `save_target` and `refresh_target_names` do their record building in `work` and all widget updates in `done`.

- [ ] **Step 1: Write failing tests**: rewrite `test_fetch_thread_title_uses_vipergirls_headers` around a `FakeBridge`; add `test_save_target_builds_record_off_thread` (monkeypatch `threading.Thread` with a synchronous fake and `after` to call immediately; assert the target is saved and the Save button re-enabled).

- [ ] **Step 2–4: fail, implement, pass.**

- [ ] **Step 5: Commit** — `git commit -m "fix(posting): fetch thread titles through the sidecar on a worker thread"`

---

### Task 15: Gallery Manager window guards and IMX session cleanup

**Files:**
- Modify: `frontend/modules/gallery_manager.py:278-286, 402-410, 721-729, 808-816`, `frontend/modules/gallery_service.py:1025-1210`
- Test: `frontend/tests/test_gallery_service.py`

**Interfaces:**
- `GalleryManagerWindow._window_alive() -> bool` (`winfo_exists()` guarded by try/except) used at the top of `_handle_sync_all_result`, `_handle_create_result`, `_handle_delete_result`, and inside the sync `_progress` lambda.
- `_list_imx_galleries`, `_sync_all_imx_galleries`, `_create_imx_gallery`, `_delete_imx_gallery` close the session in `finally`.

- [ ] **Step 1: Write failing tests**: `test_imx_list_closes_session_on_success` (monkeypatch `gallery_service.requests.Session` to a fake with `close` recorded and canned responses), same for create; `test_gallery_manager_callbacks_ignore_destroyed_window` (window via `__new__`, `winfo_exists` → False, `_handle_create_result` returns without touching `btn_create`).

- [ ] **Step 2–4: fail, implement, pass.**

- [ ] **Step 5: Commit** — `git commit -m "fix(gallery): close IMX sessions and ignore callbacks after the window closes"`

---

### Task 16: Sidecar bridge restart backoff outside the lock

**Files:**
- Modify: `frontend/modules/sidecar.py` (`_handle_crash:208-243`, `_dispatch_event:276`)
- Test: `frontend/tests/test_sidecar.py`

**Interfaces:**
- `_handle_crash` computes `delay` and increments `restart_count` under `restart_lock`, releases, sleeps, then re-acquires to `_start_process`.
- `_dispatch_event` terminal-event `put` timeout is `1.0`.

- [ ] **Step 1: Write failing test** `test_restart_backoff_sleeps_without_holding_restart_lock`: bridge via `__new__` with `proc = SimpleNamespace(poll=lambda: 1)`, `restart_count = 0`, `max_restarts = 5`, `restart_delay = 0.01`; monkeypatch `sidecar.time.sleep` with a function that asserts `bridge.restart_lock.acquire(blocking=False)` succeeds from a helper thread (and releases); `_start_process` stubbed to return True.

- [ ] **Step 2–4: fail, implement, pass.**

- [ ] **Step 5: Commit** — `git commit -m "fix(sidecar): do not hold the restart lock while backing off"`

---

### Task 17: Remove dead code and stale references

**Files:**
- Delete: `frontend/modules/controller.py`, `frontend/tests/test_controller.py`, `frontend/modules/validation.py`, `frontend/tests/test_validation.py`, `archive/legacy_plugins/`, `VGPost.txt`
- Modify: `docs/README.md:97-110` (tree), `docs/archive/README.md` (say the files were removed in v3.1.2 and live in git history), `docs/guides/USER_TUTORIAL.md:1239`, `docs/guides/REPOSITORY_LAYOUT.md` (if it lists them), `frontend/modules/ui/Main_Window/app.py:172-174` (if not already done in Task 10)
- Test: `frontend/tests/test_build_contract.py`

- [ ] **Step 1: Write failing test** `test_dead_modules_are_gone`: asserts none of the six paths exist and that `grep` of `frontend/modules` for `controller` / `modules.validation` imports finds nothing (`subprocess` not needed: walk files and search text).

- [ ] **Step 2–4: fail, delete, update docs, pass** (`git rm` the files; full suite green).

- [ ] **Step 5: Commit** — `git commit -m "chore: remove unused controller, validation module, legacy plugins and VGPost.txt"`

---

### Task 18: Documentation and version bump to 3.1.2

**Files:**
- Modify: `frontend/modules/config.py:11`, `Makefile:25`, `build.sh:16`, `build_uploader.bat:12`, the six `frontend/modules/plugins/*.py` metadata `"version"` fields, `README.md` (badges lines 3–4, line 15, new `### v3.1.2` section at line 95, download names 194–200, Go version lines 10/209/396, CI "1.26.x"), `docs/CONTRIBUTING.md:65`, `docs/guides/BUILD_TROUBLESHOOTING.md:17,306`, `docs/TRANSPORT_CONTRACT.md`, `docs/ARCHITECTURE.md`, `docs/guides/USER_TUTORIAL.md` (Stop and Cancelled rows), `docs/CHANGELOG.md`, `docs/releases/RELEASE_NOTES.md`, `docs/README.md:44,142,197`
- Create: `docs/releases/RELEASE_NOTES_v3.1.2.md` (mirror the v3.1.1 file's sections: Overview, Fixed, Changed, Removed, Verification, Download)
- Test: `frontend/tests/test_build_contract.py`

**Interfaces:**
- `TRANSPORT_CONTRACT.md` documents: `batch_id`, the `cancel` action, per-file validation, `Cancelled` status, the `Failed`+`error` pair, `literal_values`, `timeout_seconds`, `reset_cookies`.
- `ARCHITECTURE.md`: Current Status 3.1.2 / 2026-11-06; row states; Stop semantics; poster session model.

- [ ] **Step 1: Write failing test** `test_version_strings_agree`: reads `config.APP_VERSION`, `Makefile`, `build.sh`, `build_uploader.bat`, each plugin metadata via `PluginManager().get_all_plugins()`, and `README.md` badge, asserting all equal `3.1.2`; `test_transport_contract_documents_cancel_and_flags` asserts the eight terms above appear in `docs/TRANSPORT_CONTRACT.md`.

- [ ] **Step 2–4: fail, edit, pass.** Changelog entry `## [3.1.2] - 2026-11-06` with `### Fixed`, `### Changed`, `### Removed` listing the spec's items in user terms; README "Latest Changelog" gets the same summary; release index table gets a `v3.1.2` row and new "Latest Release" block.

- [ ] **Step 5: Commit** — `git commit -m "docs: release v3.1.2 Lifecycle Hardening"`

---

### Task 19: Final verification and push

- [ ] **Step 1:** From the repo root run the Global Constraints command set plus `cd backend && go test -race ./...` and `cd backend && go build -o /tmp/uploader .`.
- [ ] **Step 2:** Re-run the three reproductions from the review against the built sidecar and the new poster: a job with `photo..jpg` uploads the other file and emits `batch_complete`; `{"action":"http_request","generic_spec":{...,"form_fields":{"message":"Set {HD}"},"literal_values":true}}` reaches the server verbatim; `test_auto_poster.py` covers the poster cases.
- [ ] **Step 3:** `git log --oneline main..HEAD` shows one commit per task; `git push -u origin ccr-c7a6caec-wpl3wv` (retry with 2/4/8/16 s backoff on network errors).
- [ ] **Step 4:** Report: test counts, the commands run, and the branch URL. Do not create a tag or a pull request unless asked.
