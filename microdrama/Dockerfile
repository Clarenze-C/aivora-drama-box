# T046 private staging image: the composed owner app + worker lanes.
# Base digests pinned 2026-11-01 (docker pull verified on the staging host).
FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb

# ffmpeg/ffprobe serve the editing/QA lanes; ca-certificates for any future
# TLS egress. Apt versions float within the pinned base — acceptable for the
# OFFLINE_MOCK staging composition; revisit when live providers land (T045).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock

COPY src/ ./src/
COPY migrations/ ./migrations/

ENV PYTHONPATH=/app/src \
    MICRODRAMA_EXECUTION_MODE=OFFLINE_MOCK \
    MICRODRAMA_OBJECT_STORE_ROOT=/data/objects \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --system --uid 10001 --home /app microdrama \
    && mkdir -p /data/objects && chown -R microdrama:microdrama /data /app
USER microdrama

# The app serves on 127.0.0.1 INSIDE the container only when left default;
# compose publishes it bound to the host loopback. Workers override the cmd.
CMD ["python", "-m", "microdrama.api.serve"]
