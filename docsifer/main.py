"""Application factory + ASGI entry point.

This module owns the FastAPI ``app`` instance, the lifespan-managed
singletons (``DocsiferService``, ``AnalyticsService``, safety primitives)
and the optional Gradio UI mount.

Run with::

    uvicorn docsifer.main:app --host 0.0.0.0 --port 7860

or in production with::

    gunicorn -k uvicorn.workers.UvicornWorker -w 4 docsifer.main:app
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse

from .analytics import AnalyticsService, InMemoryStore, UpstashStore
from .analytics.store import AnalyticsStore
from .api.error_handlers import register_exception_handlers
from .api.middleware import register_middleware
from .api.v1 import router as v1_router
from .config import Settings, get_settings
from .core.service import DocsiferService
from .logging_config import configure_logging
from .safety import (
    ConversionGate,
    PerIPLimiter,
    ResourceGuard,
    disk_cleanup_loop,
    memory_watchdog_loop,
)

logger = logging.getLogger(__name__)


def _build_analytics_store(settings: Settings) -> AnalyticsStore:
    if not settings.analytics_persistent:
        logger.info("Analytics: in-memory (no DOCSIFER_REDIS_URL configured)")
        return InMemoryStore()
    try:
        store = UpstashStore(url=settings.redis_url, token=settings.redis_token)
        logger.info("Analytics: Upstash store configured")
        return store
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Could not initialize Upstash store (%s); falling back to in-memory", exc
        )
        return InMemoryStore()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    logger.info(
        "Starting %s v%s (env=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )

    # ---- core converter -------------------------------------------------
    converter = DocsiferService(
        token_model=settings.token_model,
        default_openai_base_url=settings.default_openai_base_url,
        default_openai_model=settings.default_openai_model,
        worker_pool_size=settings.worker_pool_size,
        llm_cache_max_size=settings.llm_cache_max_size,
        llm_cache_ttl=settings.llm_cache_ttl_sec,
        openai_request_timeout=settings.openai_request_timeout_sec,
        openai_connect_timeout=settings.openai_connect_timeout_sec,
        openai_max_retries=settings.openai_max_retries,
        known_extensions=set(settings.allowed_extensions),
    )
    app.state.converter = converter

    # ---- analytics ------------------------------------------------------
    store = _build_analytics_store(settings)
    analytics = AnalyticsService(
        store=store,
        sync_interval_sec=settings.analytics_sync_interval_sec,
        max_retries=settings.analytics_max_retries,
        label=settings.analytics_label,
    )
    await analytics.start()
    app.state.analytics = analytics

    # ---- safety primitives ---------------------------------------------
    app.state.conversion_gate = ConversionGate(
        max_concurrent=settings.max_concurrent_conversions,
        max_queue=settings.max_queue_depth,
    )
    app.state.per_ip_limiter = PerIPLimiter(
        max_per_ip=settings.max_per_ip_concurrent,
    )
    app.state.resource_guard = ResourceGuard(
        min_free_memory_mb=settings.min_free_memory_mb,
        min_free_disk_mb=settings.min_free_disk_mb,
        tmp_dir=settings.tmp_dir,
    )

    # ---- background loops ----------------------------------------------
    stop_event = asyncio.Event()
    background_tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            disk_cleanup_loop(
                tmp_dir=settings.tmp_dir,
                ttl_sec=settings.disk_cleanup_ttl_sec,
                interval_sec=settings.disk_cleanup_interval_sec,
                stop_event=stop_event,
            ),
            name="docsifer-disk-cleanup",
        )
    ]
    if settings.enable_memory_watchdog:
        background_tasks.append(
            asyncio.create_task(
                memory_watchdog_loop(
                    threshold_pct=settings.memory_watchdog_pct,
                    interval_sec=settings.memory_watchdog_interval_sec,
                    stop_event=stop_event,
                ),
                name="docsifer-memory-watchdog",
            )
        )
    app.state.stop_event = stop_event

    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.app_name)
        stop_event.set()
        for task in background_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        with contextlib.suppress(Exception):
            await analytics.stop()
        with contextlib.suppress(Exception):
            await converter.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI application."""
    settings = settings or get_settings()

    app = FastAPI(
        title=f"{settings.app_name} Service API",
        description=(
            "Convert PDF, PowerPoint, Word, Excel, images, audio, HTML, JSON, "
            "CSV, XML, ZIP, and more into Markdown — optionally enhanced by an LLM."
        ),
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        default_response_class=ORJSONResponse,
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # CORS — fixes Bug A9 (allow_credentials with origins='*')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials_safe,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    # GZip large responses (Section B.4)
    app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_min_size)

    register_middleware(app, settings)
    register_exception_handlers(app)

    # ---- routes ---------------------------------------------------------
    app.include_router(v1_router, prefix="/v1")

    # ---- optional Gradio UI --------------------------------------------
    _maybe_mount_gradio(app, settings)

    return app


def _maybe_mount_gradio(app: FastAPI, settings: Settings) -> None:
    try:
        import gradio as gr  # type: ignore

        mount_fn = getattr(gr, "mount_gradio_app", None)
        if mount_fn is None:
            from gradio.routes import mount_gradio_app as mount_fn  # type: ignore
        from .ui.gradio_app import build_interface
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("Gradio UI disabled (%s)", exc)
        return

    try:
        interface = build_interface(settings, app)
        mount_fn(app, interface, path="/")
        logger.info("Gradio UI mounted at /")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not mount Gradio UI (%s)", exc)


# Public ASGI app instance ----------------------------------------------------
app: FastAPI = create_app()
