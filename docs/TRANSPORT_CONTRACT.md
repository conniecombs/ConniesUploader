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
  Without it Go replaces each `{name}` whose name is a job value (creds,
  config, values extracted by earlier steps) with that value, in one pass, so
  inserted text is never scanned again. Brace text that names no job value is
  sent unchanged, so a password or title such as `Holiday {2024}` is safe
  either way; set the flag for final text such as a forum post so that a
  `{name}` matching a job value is not replaced. Upload specs follow the same
  substitution rule.
- `timeout_seconds`: the deadline for this request. Values above the client
  ceiling (180 s) clamp to it. Python waits this long plus a small margin so
  Go always gives up first.
- `reset_cookies`: discard the cookies of the request URL's site (its
  registrable domain, e.g. every `*.example.com` host for
  `https://www.example.com/login`) before the request, so a login attempt
  cannot ride an older session. Cookies of every other site are kept, so a
  forum login does not end an image host's session.

Python disables transport retries for a request that must not be repeated
(for example a forum reply) by sending `"retry_config": {"max_retries": 0}`.

## Retries and Upload Time Limits

Go retries an attempt only when no response arrived and the failure is a
network error (timeout, refused or reset connection, early close, DNS), or
when the response status is in `retry_config.retryable_http_codes`. It never
reads response text to decide. A failure after a response arrived (parsing, a
follow-up request) is not retried.

An upload is not sent again once its body was fully written: if the host's
answer is then lost, the file fails with "no response from host after upload;
check the host before retrying", because the host may already have stored it.

Upload transfers have no wall-clock limit. An attempt fails when no body bytes
move for 120 s (`upload stalled`), or when the host has not finished answering
5 minutes after the whole body was handed to the network. That wait is long
because on a slow uplink the end of the body can still be queued in OS and
modem buffers at that point; a host that drops the connection is detected at
once. Non-upload requests keep their own deadlines.

## Batches, Cancellation, and Per-File Validation

Every `http_upload` job of one Start carries the same `batch_id` and its own
`id`. Python ignores events whose `id` is not part of the current batch.

```json
{"action": "cancel", "batch_id": "<batch id>"}
```

`http_upload` jobs run on the `--workers` pool. Every other action
(`http_request` and the rest) runs on a separate small pool, so a login,
forum post or gallery call never waits behind queued uploads. Go reads stdin
without blocking on busy workers, however many jobs are queued.

`cancel` is handled as soon as it is read from stdin, even while every worker
is busy. In-flight uploads of that batch, and a multi-file job's shared
`pre_request` login still running, are aborted at once and report
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
not finished. After `batch_complete`, Python ends every file of that job that
has not finished: a file whose `result` arrived without its `status: "Done"`
is completed as Done, and any other file is failed ("no result received from
sidecar"). Python's sidecar bridge never drops a terminal event (`result`,
`error`, `status` `Done`/`Failed`/`Cancelled`, `batch_complete`): when a
listener's queue is full it waits for room. Only progress events and other
statuses are dropped under load.

An upload is `Done` only when it produced a viewer link. A non-2xx upload
response, a non-2xx answer to the response parser's `follow_up_request`, a
failed `status_path` check, a body the parser cannot read, or a response
(after any resolution) without a link ends as `Failed`. The error
names the HTTP status and the host's own message (a JSON `error`, `message`,
`msg`, or similar field) or else a short plain-text snippet of the response,
with job credentials and every value the `pre_request` login step extracted
redacted (whether it ran once for the job or for the file alone). Go does not
re-send such an upload: the host already answered.

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

## Per-File Upload Tokens

Python builds one `http_spec` for a whole upload job, from its first file, so
a value that differs between files must not be baked into it. Go fills these
tokens separately for each file, in the upload URL, headers, and multipart
`text`/`dynamic` field values:

| Token | Value |
| --- | --- |
| `{filename}` | the file's base name |
| `{file_size}` | the file's size in bytes |
| `{upload_id}` | a random 12-character token unique to this file's upload |

Job credentials, config, context data, and shared session values are also
available as `{key}`.

A `response_parser`'s `url_template` and `thumb_template` take `{filename}`,
`{basename}`, `{ext}`, `{dot_ext}` (all from the local file) and JSON response
values by key or dotted path. A `thumb_template` can also build on the parsed
link: `{url_no_ext}` is the link up to the extension of its path, without query
or fragment and with the link's own escaping kept (`%2F` stays `%2F`, `(`
stays `(`), and `{url_dot_ext}` is that extension (`.jpg`), so
`{url_no_ext}m{url_dot_ext}` turns `https://h/AbC.jpg` into `https://h/AbCm.jpg`.

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
  Both names are compared in Unicode NFC, so a decomposed macOS name
  (`e` + U+0301) matches the composed `é` a host lists.
  Next, the same name once punctuation is ignored (a host that turned
  `Scan #1.jpg` into `Scan__1.jpg`). Only on the last poll, when neither is
  listed, a host name that contains the file's name as whole words
  (`4411_beach.jpg` for `beach.jpg`). An entry that another file of the job
  matches more closely is left for that file, if that file's upload has
  finished and it holds no entry yet; a file still queued, or whose upload
  failed, holds nothing back. Local file names are never
  parsed as URLs; a page value is reduced to its last path segment only when
  it is a link, and its percent-escapes are decoded. Files of the job with
  the same name take the page's entries in the order their uploads finished.
- `contains`: as `filename`, but the whole-word containment rule applies on
  every poll.
- `first` / `single`: the first entry no other file of the job holds.
- `upload_order`: for hosts whose result page lists every image of the
  job's shared upload session, in upload order, with links that carry no
  file names. Order is only defined when the session's uploads do not
  overlap, so Go runs such a job's files one at a time whatever `threads`
  says, and each file takes the newest entry after the last one a file of
  the job holds: its own last upload attempt. The page also lists the images
  of attempts that failed after the host stored them (a lost answer, a 5xx
  that was retried, a 2xx without a link), so the n-th successful upload is
  not the n-th entry; a file never takes an earlier attempt's entry. Go
  counts the attempts that reached the host since the last resolved file and
  waits until the page lists that many new entries, since it may not list
  the upload yet; on the last poll, fewer new entries mean failed attempts
  the host did not keep, and the newest is taken. If the page lists more new
  entries than attempts reached the host, the file fails with "cannot tell
  which result-page entry is this upload's" and later files start after
  those entries. A page with exactly one entry (a session per file) belongs
  to that one upload. For `http_batch_resolve`, the files are taken to have
  uploaded in the order given and the n-th takes the n-th entry. The cost is
  the job's upload parallelism: its files upload, and are resolved, one
  after another.

## Guardrails

- Production Go files are tested to reject host-name strings.
- Python tests cover that raw transport requests include response body and
  metadata flags.
- Backend tests cover that raw public `http_request` responses expose
  `response_body`, `status_code`, and `final_url` without leaking internal keys.
- Backend tests cover per-file validation, `cancel`, `literal_values`, braces
  in user values, `timeout_seconds` clamping, site-scoped `reset_cookies`,
  retry classification, lost upload responses, upload stall and response
  limits, per-job Thread Limits, and the separate request pool; Python tests
  cover event scoping by batch, stragglers after `batch_complete`, and the
  single-count rule for terminal events.
