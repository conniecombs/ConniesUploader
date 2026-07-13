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
