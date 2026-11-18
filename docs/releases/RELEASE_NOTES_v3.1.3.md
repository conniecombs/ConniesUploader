# Release Notes - v3.1.3 "Posting Sessions & Shared Limits"

**Release Date**: November 18, 2026
**Git Tag**: `v3.1.3`
**Previous Version**: `v3.1.2`

## Overview

v3.1.3 ships the fixes from the v3.1.2 code review that merged after the `v3.1.2` tag was cut, aligns the per-file size limit between the app and the sidecar at 100 MB, stops sending unrelated credentials to the sidecar, and splits the 2,288-line ViperGirls module into storage, client, and UI parts.

## Fixed

- Starting another upload while earlier batches are still queued for posting records those posts as "superseded by a new upload" instead of dropping them, and the previous posting worker finishes its in-flight post and exits instead of competing with the new session.
- A forum reply that waited in the sidecar queue past its deadline is reported as failed instead of being sent after the app gave up on it, so a retry cannot double-post.
- The scheduler can no longer log in between the auto-poster's reply-form fetch and submit (shared cookie jar); login and posting are serialized.
- An auto-post that waited for the scheduler's turn on the forum session is re-checked first, so it is not sent after Stop or after a new upload superseded it.
- A late non-terminal status no longer relabels a finished row.
- The sidecar forgets cancelled batch ids after an hour.
- Main-window contract tests pass under real tkinter again.

## Changed

- Per-file size cap: 100 MB (104,857,600 bytes) in both Python and Go, documented in `docs/TRANSPORT_CONTRACT.md` and enforced equal by a contract test. Host-specific lower limits are unchanged.
- Upload jobs carry only the credentials their plugin declares.
- `viper_api.py` split into `viper_storage.py`, `viper_client.py`, and `viper_ui.py`; `viper_api.py` is a guarded compatibility facade for the names those modules define (imported names such as `logger` are no longer re-exported).
- One runtime-state initializer shared by the main window and its tests (`tests/app_factory.make_app()`).
- Bumped app, build-script, and active plugin metadata to `3.1.3`.

## Not in this release

- Retiring the legacy Go upload-response parser (`response_parser`, `pre_request`, `follow_up_request`, `http_batch_resolve`). Turbo, Vipr, and ImageBam depend on it for login chains, follow-up requests, and result-page polling on a per-job cookie session, so moving it to Python needs a session-handle protocol and live-host testing.

## Verification

```bash
cd frontend
python -m pytest tests -q
black --check .
flake8 main.py modules/ --max-line-length=120 --ignore=E203,E501,W503 --exclude=__pycache__
cd ../backend
go vet ./...
go test -race ./...
```

## Download

**[Download v3.1.3](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.1.3)**

Expected artifacts:

- `ConniesUploader-v3.1.3-windows-x64.zip`
- `ConniesUploader-v3.1.3-linux-x64.tar.gz`
- `ConniesUploader-v3.1.3-macos-arm64.zip`

Each artifact includes a SHA256 checksum.
