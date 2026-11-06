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
(missing, not a regular file, over 100 MiB, or a `..` path component) gets its
own `status: "Failed"` and `error` events and the rest of the job proceeds. A
`..` inside a file name (`photo..jpg`) is accepted.

Terminal events per file are exactly one of: `result` (then `status: "Done"`),
`status: "Failed"` followed by `error` with the reason, or
`status: "Cancelled"` followed by `error`. Python counts a file once and treats
the trailing `error` as the reason for the preceding status. An `error` event
that carries a job `id` but no file applies to every file of that job that has
not finished. After `batch_complete`, any file of that job without a terminal
event is failed by Python.

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
