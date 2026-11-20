# Python/Go Transport Contract

This contract keeps the Go sidecar boring, fast, and host-agnostic.

## Ownership Boundary

Python owns website behavior:

- Login sequences and session refresh decisions
- Request ordering
- HTML/form parsing
- JSON response interpretation
- Token extraction
- Success/failure decisions
- Gallery/forum/scheduler workflows
- Host-specific rate-limit choices

Go owns transport mechanics:

- Worker pool execution
- HTTP request execution
- Multipart upload streaming
- Cookie jar mechanics
- Connection reuse
- Transport retries and timeouts
- Progress events
- Thumbnail generation

Production Go must not contain service host names, forum names, scheduler
verbs, or site-specific workflow decisions.

## Preferred `http_request` Shape

Python should send one resolved request at a time:

```json
{
  "action": "http_request",
  "service": "example.host",
  "generic_spec": {
    "url": "https://example.host/path",
    "method": "POST",
    "headers": {"Referer": "https://example.host/"},
    "form_fields": {"field": "literal value"},
    "use_cookies": true,
    "include_response_body": true,
    "include_transport_metadata": true
  },
  "rate_limits": {
    "requests_per_second": 2.0,
    "burst_size": 5
  }
}
```

Go returns transport facts when requested:

- `response_body`
- `status_code`
- `final_url`

Python then parses the body and decides what the result means.

Optional request flags (all off by default):

- `literal_values`: send `url`, `headers`, and `form_fields` exactly as given.
  Without it Go substitutes `{token}` placeholders from job values and fails
  when any remain, which is wrong for final text such as a forum post.
- `timeout_seconds`: the deadline for this request. Values above the client
  ceiling (180 s) clamp to it. Python waits this long plus a small margin so
  Go always gives up first.
- `reset_cookies`: discard the shared cookie jar before the request, so a
  login attempt cannot ride an older session.

Python disables transport retries for a request that must not be repeated
(for example a forum reply) by sending `"retry_config": {"max_retries": 0}`.

## Batches, Cancellation, and Per-File Validation

Every `http_upload` job of one Start carries the same `batch_id` and its own
`id`. Python ignores events whose `id` is not part of the current batch.

```json
{"action": "cancel", "batch_id": "<batch id>"}
```

`cancel` is handled as soon as it is read from stdin, even while every worker
is busy. In-flight uploads of that batch are aborted and report
`status: "Cancelled"` plus an `error` event; jobs still queued for that batch
emit `Cancelled` for each file instead of uploading; every job still ends with
`batch_complete`.

Upload files are validated per-file as a worker reaches them. A bad path
(missing, not a regular file, over the size limit below, or a `..` path
component) gets its own `status: "Failed"` and `error` events and the rest of
the job proceeds. A `..` inside a file name (`photo..jpg`) is accepted.

## File Size Limit

The app-wide per-file cap is **100 MB = 100 × 1024 × 1024 = 104,857,600 bytes**.
Python and Go each hold the number in exactly one place:

| Side | Constant |
| --- | --- |
| Python | `config.MAX_FILE_SIZE` in `frontend/modules/config.py` |
| Go | `core.MaxUploadFileSize` in `backend/core/validate.go` |

Python rejects larger files at import and in the pre-upload checks, so the Go
check is a backstop for files that grew after they were queued. A host plugin
may declare a lower `limits["max_file_size"]` (Pixhost, Imgur, and others do);
the pre-upload checks apply the plugin's limit when one is set. A plugin limit
above the app-wide cap has no effect, because both sides still enforce the cap.

To change the cap, change both constants and this section together;
`frontend/tests/test_build_contract.py` fails if they disagree.

Terminal events per file are exactly one of: `result` (then `status: "Done"`),
`status: "Failed"` followed by `error` with the reason, or
`status: "Cancelled"` followed by `error`. Python counts a file once and treats
the trailing `error` as the reason for the preceding status. An `error` event
that carries a job `id` but no file applies to every file of that job that has
not finished. After `batch_complete`, any file of that job without a terminal
event is failed by Python.

An upload is `Done` only when it produced a viewer link. A non-2xx upload
response, a failed `status_path` check, a body the parser cannot read, or a
response (after any resolution) without a link ends as `Failed`. The error
names the HTTP status and the host's own message (a JSON `error`, `message`,
`msg`, or similar field) or else a short plain-text snippet of the response,
with job credentials redacted. Go does not re-send such an upload: the host
already answered.

## Deprecated Compatibility Hooks

These Go-side fields remain only for existing upload compatibility:

- `pre_request`
- `extract_fields`
- `success_check`
- `response_parser`
- `follow_up_request`
- `http_batch_resolve` extractors

Do not add new non-upload workflows that depend on these hooks. Prefer Python
sequencing plus raw transport responses.

The current compatibility exception is upload plugin result handling. Several
existing upload plugins still emit parser specs so Go can turn upload responses
into the result events expected by the current upload manager. Those specs are
host-defined in Python and Go remains host-name agnostic, but the execution of
those parser specs is a legacy bridge to be retired when upload result parsing
moves into Python.

## Result Resolution (`resolve_spec`)

When an upload job carries a `resolve_spec` and the upload response has a link
but no thumbnail, Go fetches `result_url` (with `{url}` set to the parsed link)
and matches the page's entries (`link_extractor` with named groups
`image_url`, `thumb_url`, and optionally `filename`) to the file. Each file is
resolved right after its own upload, but the files of one job share a claim
set: an entry given to one file of the job is never given to another, even
when their lookups run at the same time.

`file_match_mode` decides which entry a file takes:

- `filename` (default): the entry whose name (the `filename` group, else the
  last segment of `image_url`) equals the file's base name, ignoring case.
  Next, the same name once punctuation is ignored (a host that turned
  `Scan #1.jpg` into `Scan__1.jpg`). Only on the last poll, when neither is
  listed, a host name that contains the file's name as whole words
  (`4411_beach.jpg` for `beach.jpg`). An entry that another file of the job
  matches more closely is left for that file. Local file names are never
  parsed as URLs; a page value is reduced to its last path segment only when
  it is a link, and its percent-escapes are decoded. Files of the job with
  the same name take the page's entries in the order their uploads finished.
- `contains`: as `filename`, but the whole-word containment rule applies on
  every poll.
- `first` / `single`: the first entry no other file of the job holds.
- `upload_order`: for hosts whose result page lists every image of the
  job's shared upload session, in upload order, with links that carry no
  file names. The n-th upload of the job to finish takes the n-th entry; a
  page with exactly one entry belongs to that one upload (a session per
  file). Order is only defined when the session's uploads do not overlap, so
  Go runs such a job's files one at a time whatever `threads` says. The cost
  is the job's upload parallelism: its files upload, and are resolved, one
  after another.

## Guardrails

- Production Go files are tested to reject host-name strings.
- Python tests cover that raw transport requests include response body and
  metadata flags.
- Backend tests cover that raw public `http_request` responses expose
  `response_body`, `status_code`, and `final_url` without leaking internal keys.
- Backend tests cover per-file validation, `cancel`, `literal_values`,
  `timeout_seconds` clamping, and `reset_cookies`; Python tests cover event
  scoping by batch, stragglers after `batch_complete`, and the single-count
  rule for terminal events.
