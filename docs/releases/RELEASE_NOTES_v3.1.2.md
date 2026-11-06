# Release Notes - v3.1.2 "Lifecycle Hardening"

**Release Date**: November 6, 2026
**Git Tag**: `v3.1.2`
**Previous Version**: `v3.1.1`

## Overview

v3.1.2 is a maintenance release that fixes the upload, stop, retry, and auto-posting lifecycle after a full review of the repository. Three defects were reproduced and are now covered by regression tests: a filename containing `..` wedged the whole batch, the auto-poster stalled whenever a non-posting batch sat ahead of a posting one, and any forum post containing `{...}` was rejected by the transport layer. The release also makes `Stop Upload` a real cancel, counts each file once, blocks re-entrant starts, locks the shared JSON files, and removes dead code.

## Fixed

- Per-file validation in the sidecar: one bad path fails only itself and the batch still completes.
- Failed uploads are counted once, so batches no longer finish early.
- `Stop Upload` cancels queued and in-flight uploads; rows end as `Cancelled` and can be retried.
- `Start` and `Retry Failed` are blocked while an upload runs or finalizes.
- Auto-posting registers the posting batches per session and skips failed, cancelled, and "Do Not Post" batches.
- Auto-posting and the scheduler read current credentials.
- Forum replies containing `{...}` post verbatim; replies are never retried by the transport; one re-login after a lost session.
- Login tests start from an empty cookie jar.
- Shared JSON files (targets, history, scheduled posts, gallery cache) are locked and written through unique temp files.
- Imported targets pointing outside ViperGirls never open in the browser.
- Thread titles are fetched through the sidecar off the UI thread.
- Window close shuts down when the tray icon is unavailable.
- Gallery Manager ignores late results after it closes; IMX sessions are closed.
- Sidecar restart backoff no longer blocks commands; thumbnails above 50 MP are refused.

## Changed

- Sidecar protocol additions: `batch_id`, `cancel`, `literal_values`, `timeout_seconds`, `reset_cookies` (documented in `docs/TRANSPORT_CONTRACT.md`).
- CI enforces `black` and pins golangci-lint v2.15.0, gosec v2.30.0, and Bandit 1.9.4; the Makefile packages through `scripts/maintenance/package_app.py`.
- Go 1.26 or newer is required for local builds.
- Bumped app, build-script, and active plugin metadata to `3.1.2`.

## Removed

- `frontend/modules/controller.py`, `frontend/modules/validation.py`, their tests, `archive/legacy_plugins/`, and `VGPost.txt`.

## Verification

- Run Python tests from `frontend/`:

```bash
python -m pytest tests -q
black --check .
flake8 main.py modules/ --max-line-length=120 --ignore=E203,E501,W503 --exclude=__pycache__
```

- Run Go sidecar tests from `backend/`:

```bash
go vet ./...
go test -race ./...
```

## Download

**[Download v3.1.2](https://github.com/conniecombs/ConniesUploader/releases/tag/v3.1.2)**

Expected artifacts:

- `ConniesUploader-v3.1.2-windows-x64.zip`
- `ConniesUploader-v3.1.2-linux-x64.tar.gz`
- `ConniesUploader-v3.1.2-macos-arm64.zip`

Each artifact includes a SHA256 checksum.
