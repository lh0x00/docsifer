---
title: Docsifer
emoji: 📚
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Convert documents into clean, LLM-ready Markdown.
---

<div align="center">

# 📚 Docsifer

**Convert documents into clean, LLM-ready Markdown.**

PDF · Word · PowerPoint · Excel · HTML · Audio · Image · CSV · JSON · ZIP

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](#)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

## Features

- **Multi-format** — PDF, Office, audio (Whisper), images (vision), HTML, CSV, JSON, ZIP, and more — powered by [MarkItDown](https://github.com/microsoft/markitdown).
- **Optional LLM** — bring your own OpenAI-compatible key for OCR, transcription and structured layout extraction.
- **Production-grade** — bounded concurrency, per-IP fairness, memory watchdog, disk cleanup, circuit breaker.
- **Hardened** — SSRF guard, path-traversal sanitation, body-size limits, security headers.
- **Observable** — JSON logs with request id, `/v1/healthz`, `/v1/readyz`, `/v1/stats`.
- **Privacy-first** — files are processed in-memory and discarded immediately.

## Quickstart

```bash
# Local
make install
cp .env.example .env
make run

# Docker
docker build -t docsifer .
docker run --rm -p 7860:7860 --env-file .env docsifer
```

Open <http://localhost:7860> for the UI or <http://localhost:7860/docs> for the API.

## API

| Method | Path           | Description                       |
| ------ | -------------- | --------------------------------- |
| POST   | `/v1/convert`  | Convert a file or URL to Markdown |
| GET    | `/v1/stats`    | Usage analytics snapshot          |
| GET    | `/v1/healthz`  | Liveness probe                    |
| GET    | `/v1/readyz`   | Readiness probe                   |

### Examples

Basic conversion:

```bash
curl -X POST http://localhost:7860/v1/convert \
     -F "file=@document.pdf"
```

With LLM enhancement:

```bash
curl -X POST http://localhost:7860/v1/convert \
     -F "file=@page.html" \
     -F 'openai={"api_key":"sk-...","model":"gpt-4o-mini"}'
```

Convert a URL:

```bash
curl -X POST http://localhost:7860/v1/convert \
     -F "url=https://example.com/article"
```

## Configuration

All settings are environment-driven (prefix `DOCSIFER_`). See [`.env.example`](.env.example) for the full list. Common knobs:

| Variable                              | Default | Purpose                              |
| ------------------------------------- | ------- | ------------------------------------ |
| `DOCSIFER_MAX_UPLOAD_BYTES`           | `10MB`  | Hard upload limit                    |
| `DOCSIFER_MAX_CONCURRENT_CONVERSIONS` | `2`     | Global parallelism                   |
| `DOCSIFER_MAX_QUEUE_DEPTH`            | `10`    | Reject 503 when exceeded             |
| `DOCSIFER_MAX_PER_IP_CONCURRENT`      | `1`     | Per-IP fairness                      |
| `DOCSIFER_REQUEST_TIMEOUT_SEC`        | `55`    | Conversion timeout                   |
| `DOCSIFER_REDIS_URL` / `_TOKEN`       | local   | Upstash Redis for analytics          |
| `DOCSIFER_URL_ALLOW_PRIVATE_NETWORKS` | `false` | Disable to block SSRF                |
| `WEB_CONCURRENCY` *(Docker)*          | `2`     | Number of Gunicorn workers           |

## Architecture

```
docsifer/
├── api/         FastAPI layer — routes, schemas, middleware
├── core/        Pure logic — converter, MIME, tokenizer, LLM cache
├── analytics/   Lifespan-managed analytics (Upstash + in-memory)
├── safety/      Anti-crash primitives (gate, limiter, watchdog, breaker)
├── ui/          Optional Gradio playground
├── config.py    Pydantic settings
├── exceptions.py
├── logging_config.py
└── main.py      App factory + lifespan
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design notes.

## Development

```bash
make install   # runtime + dev deps
make lint      # ruff
make format    # ruff format
make type      # mypy
make test      # pytest
make cov       # pytest with coverage
```

## License

[MIT](LICENSE) © Lam Hieu — built on top of the wonderful
[MarkItDown](https://github.com/microsoft/markitdown).
