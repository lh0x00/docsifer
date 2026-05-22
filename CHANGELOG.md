# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0]

### Added
- Layered architecture: `api/`, `core/`, `analytics/`, `safety/`, `ui/`.
- Settings module (`pydantic-settings`) — single source of truth for env vars.
- App factory `create_app()` with FastAPI `lifespan` for clean startup/shutdown.
- LLM registry with TTL cache + hash key — reuses `MarkItDown(LLM)` clients
  per `(api_key, base_url, model)` triple, with a connection-pooled
  `httpx.Client` per OpenAI client.
- Streaming uploads to disk in a worker thread; no double-write to tmp.
- HTML cleanup powered by `selectolax` (strips `<style>`, `<script>`,
  hidden / `aria-hidden` / `display:none` nodes before MarkItDown sees them).
- SSRF guard: every URL is resolved and rejected if the host is private,
  loopback, link-local, multicast or unspecified.
- Anti-crash safety: `ConversionGate` (bounded concurrency + queue),
  `PerIPLimiter` (per-IP fairness), `ResourceGuard` (RAM/disk preflight),
  `CircuitBreaker`, `MemoryWatchdog`, `DiskCleanup`.
- Endpoints: `GET /v1/healthz`, `GET /v1/readyz`, `GET /v1/stats`.
- Request-ID middleware with `ContextVar` propagation into JSON logs.
- Security headers middleware (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`).
- Body-size limit middleware enforcing `DOCSIFER_MAX_UPLOAD_BYTES`.
- ORJSON default response class + GZip middleware (`>1KB`).
- Refined Gradio UI: Soft theme, two-column layout, status pill,
  metric summary (chars / KB / tokens), auto-loaded stats tab.
- Multi-stage slim `Dockerfile` (Python 3.11) with `HEALTHCHECK`,
  BuildKit cache mounts, gunicorn + uvicorn workers with request
  recycling, HF Spaces-compatible non-root user.
- GitHub Actions CI workflow: ruff + pytest + Docker build smoke
  (only on push to `main`).
- Hugging Face Space auto-sync workflow gated on CI success
  (`workflow_run` trigger).
- `pre-commit` config (ruff, mypy, basic hygiene hooks).
- `Makefile` shortcuts for install / lint / format / type / test / cov / run.
- Comprehensive test suite: unit tests for `html_cleaner`, `url_guard`,
  `tokenizer`, `llm_registry`, `periods`, `safety`, `analytics_service`;
  integration tests for `/v1/healthz`, `/v1/readyz`, `/v1/convert`,
  `/v1/stats`, SSRF rejection.
- Comprehensive `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`.

### Changed
- `requirements.txt` and `pyproject.toml` synchronised; dependencies pinned.
- Analytics persistence is opt-in: `DOCSIFER_REDIS_URL` empty by default
  → in-memory store (HF Spaces works out of the box).
- Analytics period keys use ISO calendar (`%G-W%V`) and survive
  year boundaries; flush is snapshot-then-swap and pipelined to Upstash.
- Default response class is `ORJSONResponse` (3–10× faster JSON encoding).
- Logging routed through `dictConfig` with optional JSON output.
- `datetime.utcnow()` replaced by `datetime.now(timezone.utc)` everywhere.
- CORS: `allow_credentials` is automatically disabled when origins
  contain `*` (otherwise non-compliant per the CORS spec).

### Fixed
- **A1**: Gradio UI was always forwarding OpenAI config even when no API
  key was provided — now only forwarded when a key is present.
- **A2**: HTTP cookies were dropped because `MarkItDown` was instantiated
  without a `requests.Session`; cookies now reach the upstream request.
- **A3**: Path-traversal via crafted upload filenames — sanitized with
  `Path(name).name`.
- **A4**: SSRF via URL conversion — see new `core/url_guard.py`.
- **A5/A6**: Analytics race condition on concurrent flushes; pending
  counters are now restored on flush failure.
- **A7**: Deprecated FastAPI `on_event` replaced with `lifespan`.
- **A8**: Wrong ISO week formatting at year boundaries.
- **A9**: Invalid CORS combination `allow_credentials=True` with `*`.
- **A10**: Gradio UI was looping back through HTTP to itself — now calls
  the in-process service directly.
- **A11/A13/A14**: HTML conversion no longer double-writes the body to
  disk; cleaned HTML is streamed via `BytesIO`.
- **F4**: 500 errors echoed `str(exception)` to clients — now generic
  with `request_id` in the response.
- **F5**: Server-side extension allowlist (not just UI-side).
- **F6**: Internal exception messages no longer leak.
- **C6**: Body streaming is now async-safe (handled in a worker thread).
- LLM client cache no longer leaks: TTL eviction + bounded size.

### Removed
- Legacy flat modules `docsifer/router.py`, `docsifer/service.py`,
  `docsifer/analytics.py`.
- Eager / module-level side effects on import — replaced by `lifespan`.

## [1.0.0]
- Initial public version.
