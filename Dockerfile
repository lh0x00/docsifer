# syntax=docker/dockerfile:1.6
# =============================================================================
# Docsifer — production image (multi-stage, slim, HF Spaces compatible)
# Build:   docker build -t docsifer .
# Run:     docker run --rm -p 7860:7860 --env-file .env docsifer
# =============================================================================

ARG PYTHON_VERSION=3.11

# -----------------------------------------------------------------------------
# Stage 1 — builder: compile wheels into /install
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libmagic1 \
        ca-certificates

WORKDIR /build
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --upgrade pip wheel \
    && pip install --prefix=/install -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — runtime: minimal final image
# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="Docsifer" \
      org.opencontainers.image.description="Document → Markdown service powered by MarkItDown" \
      org.opencontainers.image.source="https://github.com/lh0x00/docsifer" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/app/.cache/huggingface \
    XDG_CACHE_HOME=/home/app/.cache \
    TMPDIR=/tmp \
    DOCSIFER_TMP_DIR=/tmp \
    DOCSIFER_LOG_JSON=true \
    DOCSIFER_ENVIRONMENT=production \
    PORT=7860 \
    WEB_CONCURRENCY=2

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libmagic1 \
        ffmpeg \
        curl

# Hugging Face Spaces requires uid 1000 with write access to /home/user.
# We honor that convention so the image is portable.
RUN useradd --create-home --uid 1000 --shell /bin/bash app

# Bring in the pre-built site-packages from the builder
COPY --from=builder /install /usr/local

WORKDIR /home/app/app
COPY --chown=app:app . .

# Pre-create the cache dirs so HF Spaces / users with restricted FS still work
RUN mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" \
    && chown -R app:app /home/app

USER app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/v1/healthz" || exit 1

# Gunicorn + Uvicorn workers with deliberate request recycling so any slow
# library-level memory leak is bounded.  ``WEB_CONCURRENCY`` and ``PORT`` can
# be tuned via environment variables.
CMD ["sh", "-c", "exec gunicorn docsifer.main:app \
      --bind 0.0.0.0:${PORT} \
      --worker-class uvicorn.workers.UvicornWorker \
      --workers ${WEB_CONCURRENCY} \
      --timeout 120 \
      --graceful-timeout 30 \
      --max-requests 500 \
      --max-requests-jitter 50 \
      --access-logfile - \
      --error-logfile -"]
