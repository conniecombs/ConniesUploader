# v3.2.0 Python-Owned Upload Sessions and Result Parsing: Design

Status: **M1–M4 implemented in v3.2.0: every host parses its uploads in
Python. M5, removing the legacy Go hooks, stays deferred until a release has
shipped with no parsing regressions (§3.7). The live checklist (§5) must be run
before `v3.2.0` is tagged.** Section 7 records the decisions taken for the implementation; where it
differs from sections 3–4, section 7 wins.

Created: 2026-11-18
Updated: 2026-11-20 (implementation decisions informed by the v3.2.0 bug hunt; M1–M4 as built)
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
| Vipr | POST login, GET home → `sess_id`, upload `endpoint`; no `sess_id` fails the group with Vipr's login message | POST the `fn/st/op/per_row` textareas back to `/` (one attempt), then regex `[URL=…][IMG]…[/IMG]`; an empty `fn` with a non-OK `st` fails with that reason; no gallery URL (as before) |
| Turbo | optional POST login.tu? (an error status, or the login form shown again, fails the group with the host's message), GET home → endpoint resolved against /upload_html5.tu; one upload_id per job (the group's gallery id) | JSON success == true, newUrl (else /p/{id}/{filename}.html); poll that page (500 ms … 5 s, 7 looks) with result_matcher("filename") for [url=…/p/<id>/<name>.html][img]…[/img][/url]; input#imgCodeGG → gallery URL |
| ImageBam | optional login (GET /auth/login `_token`, POST; logged in when the answer has `form[action*='logout']`, else fail with the host's alert), GET / → `meta[name='csrf-token']`, POST /upload/session with the gallery fields (not retried when it creates a gallery) → `data` token | JSON `success` must be an http(s) link to the result page, else fail with the host's message; poll it (1/2/4 s) for `[URL=…/view/…][IMG]…` with `result_matcher("upload_order")` on a `sequential` job; `a#gallery-name` → gallery URL |

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

Host notes from the M4 migrations (what the fixtures could not prove):

- **Vipr:** 1 n/a (login required). 2 one Done with a vipr.im/<code> link and an i*.vipr.im/th thumbnail. 3 five files at Thread Limit 3 → one login, distinct links. 4 pick a folder in the dropdown (or auto-gallery) → files in that folder. 5 wrong password → every row "upload session setup failed: Vipr.im login failed: <Vipr's message>…"; if it says "no upload session after login", record the login page's error markup. 6 Stop. Also upload an unsupported type: the row quotes Vipr's reason. Repeat 2 with legacy_upload_parsing and compare. Unverified assumptions: login error markup selectors (XFileSharing-based), refusal reason in st, absolute endpoint, follow-up needs no Referer.
- **TurboImageHost:** (1) home page still has endpoint: '…', newUrl absolute and its page lists BBCode. (2) after a correct login uploads succeed; a false "refused the login" (post-login page still showing a password field) would fail every logged-in upload, so check this first. (3) include names with spaces and #. (4) auto gallery with covers: two jobs share one upload_id; both land in one gallery and imgCodeGG opens. (5) wrong password: note Turbo's exact message. Unverified assumptions: wrong-password marker unknown; newUrl assumed absolute.
- **ImageBam:** 1 anonymous upload: only GET / and POST /upload/session before the upload. 2 log in and upload one file. 3 five files upload one at a time by design; open each link, own image. 4 auto-gallery with a cover: exactly one new gallery, cover first, gallery URL captured, {…} title kept. 5 wrong password: note ImageBam's message. 6 Stop mid-batch. 7 try an existing Gallery Token, and one batch with legacy_upload_parsing=true to compare. Unverified assumptions: refused-login markup; success absolute; result page lists stored-but-failed uploads in order.

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

### 7.11 As built (M1–M3)

M1–M3 are implemented; IMX, Pixhost and Imgur are on the Python path. Where
the implementation differs from the text above:

- `build_raw_upload_request(file_path, config, session_values, creds)` also
  takes `creds` (IMX and Imgur authenticate with a header built from them),
  and `parse_upload_response(file_path, response, transport, session_values,
  session_state)` takes the per-job `session_state` of §7.6.
- A failed raw upload whose whole body reached the host carries
  `data.body_sent` on its `Failed` event, so upload-order matching knows the
  host may list it.
- `ResultPageMatcher` ports resolve.go as fixed on fix/v3.2.0 (f13d097), see
  8.4: upload_order takes the newest entry after the last one the job holds,
  counting the uploads that reached the host since and failing a file whose
  entry is ambiguous; held-back entries are only those of files that finished
  uploading and are still resolving; names are compared in NFC.
- For a `sequential` host the upload manager sends one file per raw job, each
  after the previous file was parsed (one session for all of them), so the
  result page changes by one upload between two resolutions. Go's own
  `sequential` flag (§7.3) is also set.
- Session open and the plugin's login run on the dispatch thread, one job
  after another; uploads of earlier jobs proceed meanwhile. `session_open`
  carries a 30 s `timeout_seconds` that Go counts from when it queued the
  open; Python waits a little longer, and a session whose open reply arrives
  after Python stopped waiting is closed by the sidecar bridge at once.
- A raw upload is re-sent only after a 429 or 503 refusal (statuses that
  mean the host did not take the file), honouring Retry-After (capped at
  60 s) and the host's rate limit, within the legacy attempt count. A 408,
  500, 502, 504 or 52x answer that the legacy path would retry now fails the
  file with the host's message, since the host may have stored it. Refused
  attempts are not counted as uploads that reached the host for upload-order
  matching, and neither is the last refusal once the attempts run out (it
  arrives as the raw result, with status 429 or 503); a host that listed one
  anyway makes the file fail as ambiguous, never take another image.
- A batch's session jobs follow its own cancel token (fix/v3.2.0's per-batch
  tokens): once Clear List and a new Start supersede the batch, they send,
  parse and report nothing more. The non-terminal `Uploaded` status may be
  dropped by the sidecar bridge under load; the raw `result` is the terminal
  event it always delivers.
- Requests on a session (logins, parser follow-ups, result-page polls) and
  `session_open`/`session_close` run on their own sidecar pool of 8 workers,
  sized for the 4 parser threads plus the dispatch thread, so they never
  wait behind forum posts, gallery calls or thumbnails; on the shared pool a
  follow-up's deadline could pass in the queue and fail an upload the host
  had stored.
- A session lives in one sidecar process. Its uploads, its requests
  (`UploadTransport` knows the session's process) and its close are written
  only to that process; after a crash a parser still running gets
  `Uploader process restarted; upload interrupted` for its follow-ups, and a
  sequential job's next file ends with it, even before the manager has
  handled the crash report.
- "30 minutes idle" counts from the end of a session's last use. A session
  is in use from the moment Go reads an upload job that names it until the
  job ends, so a group whose job waits behind other uploads for longer still
  finds its session.

## 8. How to migrate a host

This is the checklist for moving a host from its legacy Go specs to the
Python path (M4: Vipr, Turbo, ImageBam). IMX (`plugins/imx.py`), Pixhost and
Imgur are worked examples of the simple case; read `plugins/base.py` for the
interface and `tests/test_python_upload_path.py` for the manager's behaviour.

### 8.1 The interface

```python
class MyPlugin(ImageHostPlugin):
    def upload_job_options(self, config) -> dict:            # optional
        return {"sequential": True}                          # one file at a time

    def open_upload_session(self, transport, config, creds) -> dict:   # optional
        # Login and token steps, once per upload job, on a worker thread.
        page = transport.get("https://host/")
        if not page.ok:
            raise RuntimeError(request_failure("could not open the host", page))
        return {"sess_id": html_field(page.body, "input[name='sess_id']")}

    def build_raw_upload_request(self, file_path, config, session_values, creds) -> dict:
        values = helpers.per_file_upload_values(file_path)  # filename, file_size, upload_id
        return {
            "url": f"https://host/upload?upload_id={values['upload_id']}",
            "method": "POST",
            "headers": {"Referer": "https://host/"},
            "multipart_fields": {
                "file_0": {"type": "file", "value": file_path},
                "sess_id": {"type": "text", "value": session_values["sess_id"]},
            },
        }

    def parse_upload_response(self, file_path, response, transport,
                              session_values, session_state) -> UploadResult:
        ...
```

Defining `parse_upload_response` moves the plugin to the new path. Keep
`build_http_request` unchanged: it is the `legacy_upload_parsing` fallback
until M5.

### 8.2 Translating the legacy spec

| Legacy spec | Python path |
| --- | --- |
| `pre_request` chain (+ `follow_up_request`) | `open_upload_session`: one `transport.get`/`transport.post` per step, in order; cookies stay in the job's session |
| `extract_fields` CSS selector / `regex:` | `upload_results.html_field(body, selector)` (same attribute order: value, content, action, href, src, data-url, then text) or `json_value(data, path)` |
| `dynamic` multipart field, `{token}` | the value from `session_values`, put into the request in `build_raw_upload_request` |
| `{upload_id}`, `{file_size}`, `{filename}` | `helpers.per_file_upload_values(file_path)` |
| `endpoint` value rewriting the upload URL | build the URL from the extracted endpoint yourself |
| `response_parser` (JSON) | `parse_json_upload(response, **json_parser_options(PARSER), file_path=…, secrets=session_state.secrets)` |
| `response_parser` (HTML) | `html_field` on `response.body`; fail with `upload_failure(reason, response.status_code, response.body, session_state.secrets)` |
| `response_parser.follow_up_request` | a `transport.post(...)` inside `parse_upload_response` |
| `resolve_spec` | `resolve_from_result_page(transport, url, file_path, session_state.result_matcher(mode), link_extractor=…, poll_delays_ms=…, gallery_extractor=…, secrets=session_state.secrets)` |
| `file_match_mode: upload_order` | `upload_job_options -> {"sequential": True}` and `result_matcher("upload_order")` |

Values are literal on the Python path: nothing substitutes `{name}` for you.
Python `re` replaces RE2; avoid backtracking-only constructs. BeautifulSoup's
`html.parser` replaces goquery's HTML5 parser; test selectors on recorded pages.

### 8.3 Rules the framework enforces, and what is left to the plugin

- A result with no viewer URL fails the file ("Host returned no link");
  return `UploadResult.failed(reason)` with a better reason when you have one.
  `UploadResult` fields are always text (`None` becomes ""), so
  `UploadResult(url=data.get("url"))` is safe.
- Every file ends. A parser that raises or returns something other than an
  `UploadResult`, and a result the manager cannot report (for example a
  thumbnail link it cannot split), fail the file with "could not read the
  host's answer: …".
- Every failure reason is redacted with `session_state.secrets` (the
  plugin's declared credentials and every `session_values` value of 4+
  characters): the parser's, and the transport errors the sidecar reports
  for the job's uploads, which can quote the upload URL. Add tokens a parser
  extracts with `session_state.add_secrets`.
  Build reasons with `upload_failure` / `request_failure`, which quote the
  host's JSON message or 200 characters of visible text, never a whole page.
- A follow-up request that is not 2xx comes back with `ok == False` and
  `message` "HTTP <code>: <body>"; pass it to `request_failure`.
- After Stop, `transport` answers `status == "cancelled"` without sending,
  `transport.pause()` returns False, and a failure is reported as
  `Cancelled`. Just return early.
- `parse_upload_response` runs for several files of one job at once: keep
  shared state in `session_state` (use `session_state.lock` or
  `get_or_create` for read-modify-write). Hold `session_state.lock` only
  for such a step, never across a request or `transport.pause()`: the job's
  other parsers wait for it. The framework's own bookkeeping (uploaded and
  finished files, the result matchers, `secrets`) uses a separate internal
  lock, so a plugin that holds `session_state.lock` too long slows only its
  own job's parsers, never the event listener.
- Raise from `open_upload_session` to fail the whole group (for example a
  refused login: "Wrong password" must name the host's message, not a parse
  error). Raise from `build_raw_upload_request` to fail one file.

### 8.4 Result pages

`session_state.result_matcher(mode)` returns the job's shared matcher; the
upload manager tells it which files were uploaded (raw result, or a failure
with `body_sent`) and which are finished. Modes: `filename` (Turbo: exact
name, then the name without punctuation, then whole-word containment on the
last poll), `contains`, `first`/`single`, `upload_order` (ImageBam: the
newest entry after the last one the job holds, once the page lists as many
new entries as uploads reached the host since; more than that fails the file
with "cannot tell which result-page entry is this upload's"; needs
`sequential`, and give it poll delays long enough for the page to catch up).
`resolve_from_result_page` polls with your delays, extracts entries with your
regex (named groups `image_url`, `thumb_url`, optional `filename`), matches,
and returns `UploadResult(url, thumb, gallery_url)` or the reason it gave up.

### 8.5 Tests a migration needs

1. Parity: add the host's recorded answers (success, auth failure, a markup
   variant, the v3.2.0 bug-fix cases) to `backend/core/testdata/upload_parity.json`
   when the legacy Go path can produce them, so `upload_parity_test.go`
   pins the legacy result and `tests/test_upload_parity.py` checks the new
   parser against it; otherwise test the parser directly with those bodies.
2. The request: `build_raw_upload_request` gives the same fields, per file,
   as the legacy spec did after substitution.
3. The session step with a fake transport: login success, wrong password
   (the host's message), a missing token.
4. Result pages (Turbo, ImageBam): files with similar names, a lagging page,
   a failed upload in the middle of an upload-order session.
5. `uses_python_upload_parsing(plugin)` is true and `legacy_upload_parsing`
   routes the host to its legacy spec (see `tests/test_migrated_hosts.py`).
6. Then the live checklist in §5.
