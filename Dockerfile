# syntax=docker/dockerfile:1

FROM golang:1.26-bookworm AS sidecar-builder

WORKDIR /src/backend
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/uploader .

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

RUN mkdir -p /data/uploads /input /output \
    && chmod +x /app/uploader

WORKDIR /app/frontend
EXPOSE 8080

CMD ["sh", "-c", "python -m uvicorn web.app:app --host ${CONNIESUPLOADER_HOST:-0.0.0.0} --port ${CONNIESUPLOADER_PORT:-8080}"]
