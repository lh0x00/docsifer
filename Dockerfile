# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# Docsifer — multi-stage image (CPU-only, HF Spaces compatible).
#
#   Stage 1  builder   compiles wheels from requirements.txt into /install
#   Stage 2  runtime   slim image with jemalloc + healthcheck + non-root user
#
# Build:
#   docker build -t docsifer .
# Run:
#   docker run --rm -p 7860:7860 --env-file .env docsifer
# -----------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11

# ============================================================================
# Stage 1: builder
# ============================================================================
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Build tools required by source-only wheels (e.g. python-magic, tiktoken).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates libmagic1

WORKDIR /build
COPY requirements.txt ./

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --prefix=/install -r requirements.txt

# ============================================================================
# Stage 2: runtime
# ============================================================================
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="docsifer" \
      org.opencontainers.image.description="Document → Markdown service powered by MarkItDown" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/lh0x00/docsifer"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/home/user/.cache/huggingface \
    XDG_CACHE_HOME=/home/user/.cache \
    TMPDIR=/tmp \
    DOCSIFER_TMP_DIR=/tmp \
    DOCSIFER_LOG_JSON=true \
    DOCSIFER_ENVIRONMENT=production \
    PORT=7860

# jemalloc keeps RSS predictable for workloads with frequent (de)allocations
# (markitdown / ffmpeg / pillow chains all churn the heap).
# libmagic1 + ffmpeg are required at runtime by python-magic and audio
# transcription respectively. curl is used by HEALTHCHECK.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        libjemalloc2 libmagic1 ffmpeg ca-certificates curl

ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2

# Non-root. Hugging Face Spaces requires uid 1000 with write access to /home/user.
RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/app

# Pull the prebuilt site-packages from stage 1.
COPY --from=builder /install /usr/local

# Application source.
COPY --chown=user . .

# Ensure HF cache dirs exist (Spaces / restricted FS).
RUN mkdir -p "$HF_HOME" "$XDG_CACHE_HOME"

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/v1/healthz" >/dev/null || exit 1

CMD ["uvicorn", "docsifer.main:app", \
     "--host", "0.0.0.0", \
     "--port", "7860", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
