# Web Docker Quickstart

Connie's Uploader now has a first-pass FastAPI web runtime for Docker and browser-based use. The desktop CustomTkinter app remains the primary native desktop runtime; the web runtime is an additional container-friendly path.

## Run With Compose

From the repository root:

```bash
export CONNIESUPLOADER_WEB_PASSWORD=change-this-password
docker compose up --build
```

Open `http://localhost:8080/`.

Compose binds the web port to `127.0.0.1` by default and requires
`CONNIESUPLOADER_WEB_PASSWORD`. Use username `admin` unless you also set
`CONNIESUPLOADER_WEB_USERNAME`.

The included `docker-compose.yml` mounts:

| Host path or volume | Container path | Purpose |
| --- | --- | --- |
| `conniesuploader-data` | `/data` | Settings, JSON credentials, templates, staged uploads, history, logs |
| `./Input` | `/input` | Mounted source files shown in the web file picker |
| `./Output` | `/output` | Generated output text files |

Create `Input/` in the repository root if you want the mounted-file picker to show local files through Compose. Browser-staged uploads do not require `Input/`; they are saved under `/data/uploads`.

## Run Without Compose

```bash
docker build -t conniesuploader-web:local .
docker run --rm -p 127.0.0.1:8080:8080 ^
  -e CONNIESUPLOADER_WEB_AUTH_REQUIRED=true ^
  -e CONNIESUPLOADER_WEB_PASSWORD=change-this-password ^
  -v conniesuploader-data:/data ^
  -v "%cd%\\Input:/input:ro" ^
  -v "%cd%\\Output:/output" ^
  conniesuploader-web:local
```

For PowerShell on Windows, the line-continuation character is backtick instead of `^`.

## Runtime Settings

The Dockerfile sets these defaults:

| Variable | Default |
| --- | --- |
| `CONNIESUPLOADER_MODE` | `web` |
| `CONNIESUPLOADER_DATA_DIR` | `/data` |
| `CONNIESUPLOADER_INPUT_DIR` | `/input` |
| `CONNIESUPLOADER_OUTPUT_DIR` | `/output` |
| `CONNIESUPLOADER_HOST` | `0.0.0.0` |
| `CONNIESUPLOADER_PORT` | `8080` |
| `CONNIESUPLOADER_WEB_AUTH_REQUIRED` | `true` in Compose |
| `CONNIESUPLOADER_WEB_USERNAME` | `admin` |
| `CONNIESUPLOADER_WEB_PASSWORD` | required in Compose |
| `CONNIESUPLOADER_WEB_DOCS_ENABLED` | `false` in web mode |

Bind `8080` to localhost when exposing the app only on the current machine:

```yaml
ports:
  - "127.0.0.1:8080:8080"
```

## WebGUI Scope

The current webGUI supports:

- Health/runtime status
- Service selection and schema-driven host options
- JSON-backed credential entry/status
- Mounted `/input` file browsing
- Browser upload staging
- One-batch upload queue with optional cover selection
- Start/cancel controls
- Server-sent upload progress
- Raw upload links
- Generated output text, output downloads, and history listing

Gallery management, ViperGirls posting, scheduled posts, and multi-user auth are outside the first Docker web slice.

## Security Notes

The web runtime fails closed when `CONNIESUPLOADER_WEB_AUTH_REQUIRED=true` and no password or bearer token is configured. Keep the default localhost binding unless you put the app behind HTTPS, a VPN, or a trusted reverse proxy. The API stores web credentials in `/data/credentials.json`, returns only credential presence status to the browser, and blocks path traversal outside configured input/output roots.
