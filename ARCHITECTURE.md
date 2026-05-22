# Architecture

This document explains how the Docsifer codebase is structured and why.

## Goals

1. **Correctness** — eliminate the bugs identified in the audit (SSRF,
   path-traversal, broken cookies, race conditions, deprecated FastAPI APIs).
2. **Production-grade safety** — never crash a free-tier container under load.
3. **Operability** — config driven, observable, well-tested.
4. **Performance** — minimize redundant I/O, reuse expensive clients.

## Module map

```
docsifer/
├── api/              # HTTP layer
│   ├── deps.py
│   ├── error_handlers.py
│   ├── middleware.py        # request-id, body limit, security headers
│   ├── schemas.py           # Pydantic request/response models
│   └── v1/
│       ├── convert.py       # POST /v1/convert
│       ├── stats.py         # GET  /v1/stats
│       └── health.py        # GET  /v1/healthz, /v1/readyz
├── core/             # Pure business logic
│   ├── service.py           # DocsiferService
│   ├── llm_registry.py      # TTL-cached MarkItDown(LLM) instances
│   ├── html_cleaner.py      # selectolax-based HTML scrub
│   ├── tokenizer.py         # tiktoken wrapper with fallbacks
│   ├── mime.py              # safe MIME detection
│   └── url_guard.py         # SSRF protection
├── analytics/        # Lifespan-managed analytics
│   ├── service.py
│   ├── periods.py           # ISO 8601 week numbering
│   └── store.py             # AnalyticsStore protocol + Upstash & in-memory
├── safety/           # Anti-crash primitives (Section N of the audit)
│   ├── conversion_gate.py
│   ├── per_ip_limiter.py
│   ├── resource_guard.py
│   ├── circuit_breaker.py
│   ├── memory_watchdog.py
│   └── disk_cleanup.py
├── ui/               # Gradio UI (optional)
│   └── gradio_app.py
├── config.py         # pydantic-settings
├── exceptions.py
├── logging_config.py
└── main.py           # FastAPI app factory + lifespan
```

## Request flow (POST /v1/convert)

```
Client
  │  multipart/form-data
  ▼
[ middleware ]
  ├─ request_id          → X-Request-ID header + ContextVar
  ├─ body_limit          → 413 if Content-Length > MAX
  └─ security_headers    → X-Content-Type-Options, X-Frame-Options, …
  │
  ▼
[ route handler convert.py ]
  ├─ parse JSON forms via Pydantic (422 on errors)
  ├─ acquire PerIPLimiter slot (429 on overflow)
  ├─ acquire ConversionGate slot (503 when full)
  ├─ stream upload to disk in worker thread
  ├─ ResourceGuard checks RAM/disk
  ├─ asyncio.wait_for() guards against runaway conversions
  └─ DocsiferService.convert_file(...)
       │
       ▼
[ DocsiferService (core) ]
  ├─ choose converter:
  │     ├─ no api_key → cached `MarkItDown()`
  │     └─ otherwise  → LLMRegistry.get(LLMConfig)
  ├─ HTML path  → clean in-memory → MarkItDown.convert_stream()
  └─ everything else → normalize_extension() → MarkItDown.convert(path)
```

The route returns an `ORJSONResponse`; large markdown payloads are gzipped by
the `GZipMiddleware`.

## Lifespan

`docsifer.main._lifespan` owns the lifecycle of every singleton:

- `DocsiferService`            — built once, has a bounded `ThreadPoolExecutor`.
- `AnalyticsService`           — loads totals from Upstash, kicks off the
  background sync loop, **flushes pending counters on shutdown**.
- `ConversionGate`, `PerIPLimiter`, `ResourceGuard` — no I/O, just config.
- `disk_cleanup_loop`          — periodic temp-file sweeper.
- `memory_watchdog_loop`       — optional, sends SIGTERM on RSS overrun.

All background tasks share an `asyncio.Event` so shutdown is deterministic.

## Concurrency model

- One global `asyncio.Semaphore` (in `ConversionGate`) bounds in-flight
  conversions. Anything beyond `max_concurrent + max_queue` is rejected with
  `503 + Retry-After`.
- `PerIPLimiter` enforces fairness so a single IP cannot monopolize the gate.
- `ResourceGuard` runs ahead of every conversion to short-circuit OOM.
- All synchronous work happens in a dedicated `ThreadPoolExecutor` to keep
  the event loop responsive.

## Analytics

- Increments are stored in an in-process `pending` counter and applied to a
  `totals` counter atomically. The lock-free `_snapshot` dict is what
  `/v1/stats` returns — readers are never blocked by writers.
- The background sync loop pipelines `HINCRBY` operations into Upstash so a
  full flush is a single HTTP round-trip when the server supports pipelines.
- Failures keep `pending` intact for the next attempt; on shutdown the
  service performs one final flush.

## Security posture

- **SSRF** — every URL goes through `validate_url()` which resolves the host
  and rejects private/loopback/link-local/multicast addresses by default.
- **Path traversal** — `Path(filename).name` strips any directory component.
- **Body limit** — enforced by middleware before the body is consumed.
- **Extension allowlist** — server-side allowlist independent of the UI.
- **CORS** — `allow_credentials` is automatically disabled when origins
  contain `*` (which would otherwise be invalid per the spec).
- **Error responses** — never echo internal exception messages; only the
  `public_message` of the typed exception is returned.

## Free-tier defaults

The defaults in `config.py` target a 2 vCPU / 16 GB RAM container (Hugging
Face Spaces basic):

- `max_upload_bytes = 10 MB`
- `max_concurrent_conversions = 2`
- `max_queue_depth = 10`
- `max_per_ip_concurrent = 1`
- `request_timeout_sec = 55` (just under HF's 60 s gateway)
- `analytics_sync_interval_sec = 1800`
