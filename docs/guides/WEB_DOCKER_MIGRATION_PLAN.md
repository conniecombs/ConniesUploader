# Web Docker Migration Plan

This document defines the approved first-pass shape for turning Connie's Uploader into a Docker-friendly web edition while preserving the existing desktop app.

## Status

- Decision date: 2026-07-10
- Chosen approach: FastAPI plus a lightweight webGUI
- Implementation model: five gated steps, with user input before each step starts
- Desktop app status: preserved; the web edition is an additional runtime path
- Current implementation state: all five approved steps complete

## Approved Step 1 Decisions

### File Input

The web edition will support both:

- Browser uploads into an app-managed staging area.
- Mounted container folders, starting with `/input`, for NAS/server workflows and large local libraries.

The UI should let users choose between uploaded browser files and discovered mounted files without hiding where the files came from.

### Credential Storage

The first container implementation will use sensitive JSON storage under `/data`.

Desktop builds should keep using OS keyring storage. The web edition should use a credential-storage abstraction so Docker secrets or environment-backed credentials can be added later without rewriting upload logic.

### First WebGUI Scope

The first webGUI slice includes:

- Upload queue
- Host selection and settings
- Credential entry/update
- Upload checks/preflight feedback
- Start/cancel upload controls
- Progress stream
- Results and generated output
- Output/history access

Gallery management and ViperGirls posting/scheduled posts are not in the first UI slice, but the API and service boundaries should avoid blocking those features later.

## Runtime Contract

The container runtime should expose a browser UI and store all persistent state in mounted volumes.

| Purpose | Container path | Notes |
| --- | --- | --- |
| Web app data | `/data` | Settings, credentials, templates, gallery cache, posting data, activity log, history |
| Mounted source files | `/input` | Optional read-only or read-write mount for files discovered from the server side |
| Generated output | `/output` | Upload output text files and downloadable result artifacts |
| Browser upload staging | `/data/uploads` | Temporary/staged files uploaded through the web UI |

Planned environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONNIESUPLOADER_MODE` | `desktop` | Selects `desktop` or `web` runtime behavior where code paths differ |
| `CONNIESUPLOADER_DATA_DIR` | `~/.conniesuploader` | Overrides persistent user data location; Docker should set `/data` |
| `CONNIESUPLOADER_INPUT_DIR` | `/input` | Mounted-file discovery root for the web runtime |
| `CONNIESUPLOADER_OUTPUT_DIR` | `Output` | Overrides generated output location; Docker should set `/output` |
| `CONNIESUPLOADER_HOST` | `0.0.0.0` | Web server bind host |
| `CONNIESUPLOADER_PORT` | `8080` | Web server port |
| `CONNIESUPLOADER_WEB_AUTH_REQUIRED` | `true` in Docker | Requires Basic or bearer auth before serving the UI/API |
| `CONNIESUPLOADER_WEB_USERNAME` | `admin` | Basic-auth username |
| `CONNIESUPLOADER_WEB_PASSWORD(_FILE)` | unset | Basic-auth password or Docker secret file path |
| `CONNIESUPLOADER_WEB_TOKEN(_FILE)` | unset | Optional bearer token or Docker secret file path |
| `CONNIESUPLOADER_WEB_DOCS_ENABLED` | `false` in web mode | Enables FastAPI OpenAPI docs when explicitly requested |
| `CONNIESUPLOADER_WEB_SESSION_RETENTION_SECONDS` | `86400` | Retains completed in-memory upload sessions |
| `CONNIESUPLOADER_WEB_UPLOAD_RETENTION_SECONDS` | `259200` | Retains browser-staged upload files |
| `CONNIESUPLOADER_WEB_UPLOAD_MAX_FILES` | `500` | Caps staged upload count |
| `CONNIESUPLOADER_WEB_UPLOAD_MAX_BYTES` | `2147483648` | Caps staged upload bytes |

The Docker image should be Linux-based and multi-arch capable for at least:

- `linux/amd64`
- `linux/arm64`

Windows, macOS, and Linux desktop users should access the container through a browser. Native desktop release artifacts remain separate from Docker images.

## Architecture Direction

The current app is a Python CustomTkinter UI plus a Go sidecar. The web edition should keep the Python/Go boundary intact:

- Python owns plugins, settings, credentials, templates, galleries, posting workflows, request sequencing, parsing, and result/output generation.
- Go remains the host-agnostic transport sidecar used through JSON over stdin/stdout.

The web runtime should avoid importing Tk UI modules. Shared code should move behind UI-neutral services before FastAPI depends on it.

Planned source layout:

```text
frontend/
├── web/
│   ├── app.py
│   ├── api/
│   ├── static/
│   └── templates/
└── modules/
    ├── web_upload_service.py
    ├── credential_store.py
    └── existing plugin/settings/sidecar modules
```

The exact file names can change during implementation if a better local pattern emerges, but the ownership boundary should stay the same: Tk code drives the desktop UI, FastAPI drives the browser UI, and shared upload behavior lives in UI-neutral modules.

## First API Surface

The initial FastAPI surface should cover the first webGUI slice:

- `GET /api/health`
- `GET /api/services`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/credentials/status`
- `PUT /api/credentials`
- `GET /api/files/input`
- `POST /api/files/upload`
- `POST /api/uploads`
- `POST /api/uploads/{upload_id}/cancel`
- `GET /api/uploads/{upload_id}`
- `GET /api/uploads/{upload_id}/events`
- `GET /api/history`
- `GET /api/output/{name}`

Server-sent events are the preferred first progress transport because they are simple, browser-native, and sufficient for one-running-upload status updates. WebSockets can be added later if bidirectional live controls become useful.

## Step Plan

### Step 1: Scope and Runtime Contract

Output:

- This migration contract.
- Documentation index links.

Verification:

- The plan names the approved file input, credential, feature-scope, path, and runtime boundaries.

### Step 2: Docker and Web Foundation

Expected work:

- Add environment overrides for data, input, and output paths.
- Add web dependencies.
- Add a minimal FastAPI app with health/static serving.
- Add multi-stage Dockerfile and compose example.
- Build the Go sidecar inside the container image.

Expected verification:

- Local web app health endpoint runs.
- Container build succeeds for the local architecture.
- Mounted `/data`, `/input`, and `/output` paths are documented and reachable.

### Step 3: UI-Neutral Upload Service Layer

Expected work:

- Extract or wrap upload workflow pieces so FastAPI can start uploads without Tk widgets.
- Preserve existing plugin discovery, settings validation, sidecar startup, and output generation.
- Keep desktop behavior compatible.

Expected verification:

- Existing frontend tests still pass.
- New focused service tests cover queue creation, settings merge, sidecar job dispatch boundaries, and output generation without importing Tk UI modules.

### Step 4: FastAPI Endpoints and Progress Streaming

Expected work:

- Implement the API surface for services, settings, credentials, files, uploads, events, history, and output.
- Add JSON-backed credential storage for web mode.
- Add cancel/status/result handling for web uploads.

Expected verification:

- API tests cover the first webGUI slice.
- Progress events can be consumed by a browser or test client.
- Sensitive credential values are not returned by status endpoints or logs.

### Step 5: Lightweight WebGUI and Final Verification

Expected work:

- Build the first browser UI for queue, settings, credentials, upload checks, progress, and results.
- Add Docker usage docs.
- Run local and container verification.

Expected verification:

- Web UI loads and can call health/settings/service APIs.
- Docker container starts with mounted volumes.
- A local smoke path proves the queue/progress/result flow using a safe test path or mocked upload path.
- Existing desktop-oriented tests remain green or have documented, intentional adjustments.

## Non-Goals for the First Slice

- Replacing the desktop CustomTkinter app.
- Reimplementing the Go sidecar as an HTTP server.
- Shipping noVNC or browser-remote-desktop wrappers.
- Building the full Gallery Manager in the first web UI.
- Building ViperGirls posting or scheduled-post screens in the first web UI.
- Adding multi-user accounts or public internet authentication.

## Security Notes

- Web mode should assume the app is for trusted local networks unless authentication is explicitly added later.
- Credentials in `/data` must never be committed, printed in logs, or returned by status APIs.
- Docker documentation should recommend binding to localhost or running behind a trusted reverse proxy for remote access.
- `/input` path traversal protections are required before mounted-file uploads are accepted by API endpoints.
