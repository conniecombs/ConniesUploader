# v3.2.0 Python-Owned Upload Sessions and Result Parsing: Design

Status: **Being implemented for v3.2.0 (M1–M4). M5, removing the legacy Go
hooks, stays deferred until a release has shipped with no parsing regressions
(§3.7).** Section 7 records the decisions taken for the implementation; where it
differs from sections 3–4, section 7 wins.

Created: 2026-11-18
Updated: 2026-11-20 (implementation decisions, informed by the v3.2.0 bug hunt)
Baseline: v3.1.3 (branch `ccr-c7a6caec-wpl3wv` at the v3.1.3 release commit)

## 1. Why

`docs/TRANSPORT_CONTRACT.md` says Python owns website behaviour and Go is a
host-agnostic transport. Uploads still break that rule. Plugins hand Go a
declarative program, and Go executes it:

| Go-side hook | What it does today | Used by |
| --- | --- | --- |
| `pre_request` (+ nested `follow_up_request`) | Login chain, token and endpoint extraction, once per job, on an isolated per-job cookie jar | Turbo, Vipr, ImageBam |
| `extract_fields` | CSS selectors (goquery) and `regex:` patterns over HTML or JSON paths | Turbo, Vipr, ImageBam |
| `response_parser` | Turns the upload response into `url` / `thumb` (JSON path, HTML selector, regex, URL templates) | all six |
| `response_parser.follow_up_request` | A second POST after the upload, on the same session, before parsing | Vipr |
| `resolve_spec` / `http_batch_resolve` | Polls a result page and matches links to file names | Turbo, ImageBam |
| `dynamic` multipart fields, `{token}` substitution | Inject extracted session values into each upload | Vipr, ImageBam, Turbo |

These hooks are roughly half of `backend/core/http.go` (about 1,500 lines).
They are the reason Go still parses host HTML, why a host markup change needs a
Go rebuild, and why the parsing is only testable through Go.

The move was deferred from v3.1.3 because Turbo, Vipr, and ImageBam need the
same isolated cookie session across login, every concurrent file upload, and
the post-upload follow-up or result polling. Python's generic `http_request`
uses the shared jar, so moving the steps naively would break those hosts, and
the change cannot be validated without uploading to the live hosts.

## 2. Goals and non-goals

Goals:

1. Every host-specific request sequence and every response interpretation runs
   in Python plugins.
2. Go keeps only transport: requests, multipart streaming, cookie jars,
   retries, rate limits, progress, cancellation, thumbnails.
3. Each migrated host produces the same `(url, thumb, gallery_url)` results as
   today for the same responses (parity, proven by fixtures).
4. Hosts migrate one at a time behind a dual path; no flag day.

Non-goals: new hosts, changing what the user sees, changing upload concurrency,
the RAM-first archive plan (it builds on this, not the other way round).

## 3. Design

### 3.1 Transport sessions (Go)

A **transport session** is a named, isolated cookie jar plus an `*http.Client`
that shares the global transport (connection reuse, TLS, timeouts).

New actions:

```json
{"action": "session_open", "id": "<request id>", "batch_id": "<batch id>"}
→ {"id": "...", "type": "result", "status": "success", "data": {"session_id": "s-…"}}

{"action": "session_close", "session_id": "s-…"}
```

New optional field on `generic_spec` and on `http_upload` jobs:
`"session_id": "s-…"`. When present, the request uses that session's jar
instead of the shared jar. Unknown or closed ids fail the request with
`unknown transport session`.

Lifetime: closed explicitly by Python after the batch; closed automatically
when its `batch_id` is cancelled; reaped after 30 minutes idle. Sessions are
safe for concurrent use (`http.Client` and `cookiejar.Jar` are).

### 3.2 Raw upload responses (Go)

`http_upload` jobs gain `"raw_response": true`. With it, Go skips
`response_parser`, `resolve_spec`, and `pre_request` entirely and emits, per
file:

```json
{"type": "result", "file": "...", "data": {"response_body": "...", "status_code": "200", "final_url": "..."}}
```

followed by `status: "Uploaded"` (new, non-terminal). Transport failures still
emit `Failed` + `error`, cancellation still emits `Cancelled` + `error`. The
response body is capped at 2 MiB (an upload response larger than that is a
host error page, not a result).

### 3.3 Plugin interface (Python)

New optional methods on `ImageHostPlugin`:

```python
def open_upload_session(self, transport: UploadTransport, config, creds) -> Dict[str, str]:
    """Run login/token steps on transport.session_id; return values for uploads."""

def build_raw_upload_request(self, file_path, config, session_values) -> Dict[str, Any]:
    """Resolved multipart spec (literal values) for one file; no parser hooks."""

def parse_upload_response(self, file_path, response: TransportResponse,
                          transport: UploadTransport, session_values) -> UploadResult:
    """Interpret one upload response; may make follow-up requests on the session."""
```

`UploadTransport` wraps `execute_transport_request` with the session id, the
plugin's rate limits, and `literal_values=True`, so plugin code reads like the
ViperGirls client: one resolved request, then parse in Python.

`UploadResult` is `(url, thumb, gallery_url, error)`. A plugin that defines
`parse_upload_response` uses the new path; one that does not keeps the legacy
Go hooks until it is migrated.

### 3.4 Upload manager flow (Python)

Per group, for a plugin on the new path:

1. `session_open` (bounded by the batch's cancel).
2. `open_upload_session` on a worker thread (not the event listener).
3. One `http_upload` job with `raw_response`, `session_id`, and the per-file
   specs from `build_raw_upload_request`.
4. Each raw `result` event goes to a small post-processing pool
   (`ThreadPoolExecutor`, 4 workers) that calls `parse_upload_response` and
   then emits the existing `("status", fp, "Done")` / result tuples, or a
   `Failed` status with the parser's error.
5. After the job's `batch_complete` and all post-processing finish,
   `session_close`.

The event listener never blocks on `request_sync`; follow-up requests happen
in the pool. Stop cancels the batch, which closes its sessions, so in-flight
follow-ups fail fast with `Cancelled`.

Per-file unique values that Go substitutes today (`{upload_id}`, `{filename}`)
are produced in Python by `build_raw_upload_request`.

### 3.5 Host mapping

| Host | `open_upload_session` | `parse_upload_response` |
| --- | --- | --- |
| IMX | none | JSON: `status == "success"`, `data.image_url`, `data.thumbnail_url` (canonicalize thumb as today) |
| Pixhost | none | JSON: `show_url`, `th_url`; an empty `show_url` is a failure (no status field) |
| Imgur | none | JSON: `success == true`; `data.link` for both viewer and thumbnail (as today) |
| Vipr | POST login, GET home → `sess_id`, upload `endpoint` | POST the `fn/st/op/per_row` textareas back to `/`, then regex `[URL=…][IMG]…[/IMG]` |
| Turbo | optional POST login, GET home → `endpoint` | JSON `newUrl`; then poll the result page (500 ms … 5 s) and match `[url=…/p/<id>/<filename>.html][img]…` by file name; `input#imgCodeGG` → gallery URL |
| ImageBam | optional login (GET `_token`, POST), GET home → CSRF, POST `/upload/session` → `data` token | JSON `success` → result page; poll (1/2/4 s) for `[URL=…/view/…][IMG]…`; `a#gallery-name` → gallery URL |

### 3.6 Parity

Before a host switches, its new parser must reproduce today's Go output on a
fixture set:

- Reuse every response body already in the Go tests
  (`backend/uploader_*_test.go`, `backend/core/http_test.go`) and add one
  recorded response per host for success, auth failure, and a markup variant.
- A Python test feeds each fixture to `parse_upload_response` and compares with
  the expected `(url, thumb, gallery_url)` that the Go tests assert today.
- Known flavour differences to cover in fixtures: goquery vs BeautifulSoup
  attribute selection (`selectionValue` picks `value`, `content`, `action`,
  `href`, `src`, `data-url`, then text), RE2 vs Python `re` (both support
  `(?is)` and `(?P<name>…)`; Python must not rely on backtracking-only
  constructs), and Go's file-name matching rules in `batchFileMatches`.

### 3.7 Removal

Once all six hosts are on the new path and one release has shipped with no
regressions, delete from Go: `PreRequestSpec`, `extract_fields`,
`success_check`, `ResponseParserSpec` and its follow-up, `BatchResolveSpec`,
`http_batch_resolve`, `dynamic` multipart fields, and upload-time `{token}`
substitution. Keep `substituteValues` only if a non-upload caller still needs
it. Update `TRANSPORT_CONTRACT.md` to drop the "Deprecated Compatibility
Hooks" section.

## 4. Milestones

| # | Deliverable | Verified by |
| --- | --- | --- |
| M1 | Go sessions (`session_open`/`session_close`, `session_id`), `raw_response` uploads, idle reaping, cancel closes sessions | Go unit tests with httptest servers asserting cookie isolation between sessions and from the shared jar |
| M2 | `UploadTransport`, plugin interface, upload-manager dual path and post-processing pool | Python unit tests with a fake bridge; legacy hosts unchanged |
| M3 | Migrate IMX, Pixhost, Imgur | Parity fixtures; one live upload each |
| M4 | Migrate Vipr, Turbo, ImageBam | Parity fixtures; live checklist below |
| M5 | Remove legacy hooks from Go and the contract doc | Go and Python suites; host-agnostic Go test still passes |

Ship M1–M3 as v3.2.0 if M4 needs more live testing; M4 and M5 can follow as
v3.2.x.

## 5. Live verification checklist (per host, M3 and M4)

1. Upload one file without login (where the host allows it).
2. Log in and upload one file.
3. Upload five files concurrently with Thread Limit 3; all five rows end
   `Uploaded` with distinct, opening viewer links and thumbnails.
4. Create a gallery during upload (where supported); the gallery URL opens and
   contains the files.
5. Wrong password: the batch fails with the host's message, not a parse error.
6. Press Stop mid-batch: remaining rows end `Cancelled`, the session closes,
   and no later result arrives.

## 6. Risks

- **Markup drift during the migration.** Mitigated by moving one host at a
  time and keeping the legacy path until parity and the checklist pass.
- **Session leaks** if Python crashes between open and close. Mitigated by
  idle reaping and batch-cancel closure.
- **Latency** from extra JSON round trips for follow-ups. Small next to
  upload time; post-processing runs in parallel.
- **Two parsers during the transition.** Accepted for at most two releases;
  M5 removes the Go side.

## 7. Implementation decisions for v3.2.0

The v3.2.0 bug hunt found several legacy-parser bugs (an empty link reported
as success, Turbo links matched to the wrong file, every ImageBam file getting
the first image's link, Turbo sending the first file's size and id for every
file). v3.2.0 fixes them in the legacy Go path, and the Python parsers must
reproduce the *fixed* behaviour, not the old one.

1. **Per-file upload requests.** An `http_upload` job with `raw_response: true`
   carries `file_requests`: a map from each file path to a fully resolved
   request (`url`, `method`, `headers`, `multipart_fields`, optional
   `form_fields`). Exactly one multipart field has `type: "file"`, and its value is
   that path. Values are literal: Go performs no `{token}` substitution in raw
   mode. A file without an entry fails with `missing upload request`.
2. **Raw results.** Per file, Go emits
   `{"type":"result","file":…,"data":{"response_body":…,"status_code":…,"final_url":…}}`
   and then `status: "Uploaded"`, which is non-terminal. Python decides
   success or failure for every HTTP status. Transport failures still emit
   `Failed` with an `error`, and cancellation still emits `Cancelled`. A response
   body over 2 MiB fails the file with `upload response too large`. Go never
   retries a raw upload because of its HTTP status; transport retries follow
   the general rule (no retry once the body has been fully sent).
3. **Sequential jobs.** `sequential: true` uploads a job's files one at a time
   in list order. A host whose results are matched by upload order (ImageBam)
   needs it.
4. **Transport sessions.** These follow §3.1 as written: `session_open` /
   `session_close`, `session_id` on `generic_spec` requests and on
   `http_upload` jobs. Cancelling a `batch_id` closes its sessions, and
   sessions are reaped after 30 minutes idle. A session never touches the
   shared cookie jar.
5. **Python transport.** `UploadTransport` wraps `execute_transport_request`
   with the session id, the plugin's rate limits, `literal_values=True`, and
   the batch's cancel event. `request(spec)` returns a `TransportResponse`
   (`status_code`, `body`, `final_url`).
6. **Plugin interface.** The methods in §3.3, plus:
   - a per-job `session_state` dict passed to `parse_upload_response`. Result-page
     matching uses it: claim-once, exact file name first for Turbo; upload
     order for ImageBam, falling back to the only entry when the page lists
     exactly one.
   - `upload_job_options(config)` returning e.g. `{"sequential": True}`.
   - a result with no viewer URL and no error is a failure ("Host returned no
     link").
7. **Per-file values** that Go used to substitute (`{upload_id}`, `{file_size}`)
   are produced by `build_raw_upload_request`, so Turbo's `qquuid` and
   `qqtotalfilesize` are per file.
8. **Escape hatch.** The setting `legacy_upload_parsing` (default `false`, not
   shown in the main window) makes every host use its legacy Go specs. It is a
   temporary fallback in case a live host differs from the fixtures, and it
   goes away with M5.
9. **Parity tests.** These run per host and cover the fixtures in §3.6 and the
   v3.2.0 bug-fix cases above.
10. **Live checklist.** §5 cannot run in CI. A person must run it per host
    before `v3.2.0` is tagged, and if any host fails it, that host's plugin
    stays on the legacy path for the release.
