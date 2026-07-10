# syntax=docker/dockerfile:1

FROM golang:1.26-bookworm AS sidecar-builder

ARG TARGETOS=linux
ARG TARGETARCH=amd64

WORKDIR /src/backend
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -ldflags="-s -w" -o /out/uploader .

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONNIESUPLOADER_MODE=web \
    CONNIESUPLOADER_DATA_DIR=/data \
    CONNIESUPLOADER_INPUT_DIR=/input \
    CONNIESUPLOADER_OUTPUT_DIR=/output \
    CONNIESUPLOADER_HOST=0.0.0.0 \
    CONNIESUPLOADER_PORT=8080

WORKDIR /app

COPY frontend/requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends tk \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY frontend/ ./frontend/
COPY --from=sidecar-builder /out/uploader ./uploader

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /data/uploads /input /output \
    && chmod +x /app/uploader \
    && chown -R app:app /app /data /input /output

WORKDIR /app/frontend
EXPOSE 8080
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('CONNIESUPLOADER_PORT', '8080'), timeout=3).read()" || exit 1

CMD ["sh", "-c", "python -m uvicorn web.app:app --host ${CONNIESUPLOADER_HOST:-0.0.0.0} --port ${CONNIESUPLOADER_PORT:-8080}"]
