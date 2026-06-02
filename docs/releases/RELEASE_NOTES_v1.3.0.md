# Release Notes - v1.3.0 "Protocol Hardening & Release Reliability"

**Release Date**: June 2, 2026
**Previous Version**: v1.2.4
**Git Tag**: `v1.3.0`
**Release Type**: Minor

---

## Overview

v1.3.0 is a reliability and hardening release for the Python GUI, Go sidecar, upload protocol, dependency posture, and release workflows. The biggest change is a more capable generic HTTP runner that lets Python plugins describe multi-step upload flows while keeping the Go sidecar focused on safe, concurrent HTTP execution.

## Highlights

- Expanded the Go generic HTTP runner with chained prerequests, shared cookie sessions, relative endpoint resolution, and template substitution across headers, form fields, request bodies, and response templates.
- Added richer response extraction for JSON arrays, nested paths, HTML selectors, regex selectors, attributes, URL templates, and service-specific response shaping.
- Added sidecar request IDs so Python only accepts upload output events that match the active request.
- Added Imgur request-building support for the shared sidecar workflow with credential validation.
- Normalized per-service worker counts before upload jobs are sent to the sidecar.
- Tightened security workflows and pinned the Python audit tools used by CI.

## Added

### Generic HTTP Runner Protocol

The Go sidecar now supports more complex service flows without requiring hardcoded service logic. Python plugins can describe chained prerequests, share cookies across a session, extract values from earlier responses, and substitute those values into later requests.

This enables services with login pages, CSRF tokens, JavaScript-derived endpoints, nested response values, and service-specific output formats to stay inside the plugin-defined request contract.

### Sidecar Response Correlation

Upload jobs now carry request IDs through the Python-to-Go bridge. Python waits for the matching output event instead of accepting the first completed output event from the sidecar.

This prevents stale or unrelated events from being treated as the response for an active upload when multiple operations are in flight.

### Imgur Sidecar Request Builder

Imgur now has a `build_http_request` path that validates either `imgur_client_id` or `imgur_access_token` before constructing the sidecar request.

## Changed

- Build scripts now use `go mod download` instead of `go mod tidy`, keeping local module files stable during ordinary builds.
- Python coverage configuration moved to `.coveragerc`.
- Upload manager settings now clamp per-service thread counts consistently.
- Release metadata, build banners, latest-release links, and artifact names now point at `v1.3.0`.

## Security

- Updated Go security-sensitive dependencies:
  - `golang.org/x/image`
  - `golang.org/x/net`
  - `golang.org/x/sys`
- Added pinned `pip-audit==2.10.0` and `bandit[sarif]==1.9.4` dependencies.
- Tightened GitHub Actions security checks so reachable Go vulnerabilities, gosec findings, Python dependency vulnerabilities, and medium-or-higher Bandit findings fail the workflow.
- Documented the ViperGirls legacy MD5 hash as a protocol-required compatibility value, not a security credential.

## Fixed

- Prevented sidecar output-event mixups during concurrent uploads.
- Ensured HTTP response bodies are closed explicitly in service code.
- Preserved compatibility helpers while keeping strict Go linting clean.

## Verification

The release prep was verified locally with:

- Go tests
- Go vet
- `golangci-lint`
- Go sidecar build
- Go module verification
- `govulncheck`
- gosec
- Python pytest suite
- Python flake8
- `pip-audit`
- Bandit medium-or-higher security scan

## Download

**[Download v1.3.0](https://github.com/conniecombs/ConniesUploader/releases/tag/v1.3.0)**

Expected release artifacts:
- `ConniesUploader-v1.3.0-windows-x64.zip`
- `ConniesUploader-v1.3.0-linux-x64.tar.gz`
- `ConniesUploader-v1.3.0-macos-x64.zip`

Each artifact includes a SHA256 checksum for verification.

## Upgrading from v1.2.4

No settings or credential migrations are required. This is a drop-in update.

Recommended steps:
1. Back up any local settings if desired.
2. Download the `v1.3.0` artifact for your platform.
3. Replace the old executable or extracted app folder.
4. Run the app and confirm your configured services still upload successfully.

## Tag Commands

Use the annotated release tag when you are ready to publish:

```bash
git tag -a v1.3.0 -m "Release v1.3.0"
git push origin v1.3.0
```

**Full Changelog**: [v1.2.4...v1.3.0](https://github.com/conniecombs/ConniesUploader/compare/v1.2.4...v1.3.0)
