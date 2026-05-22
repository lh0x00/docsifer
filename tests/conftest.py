"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from docsifer.analytics import AnalyticsService, InMemoryStore
from docsifer.config import Settings, get_settings
from docsifer.main import create_app


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    monkeypatch.setenv("DOCSIFER_ENVIRONMENT", "development")
    monkeypatch.setenv("DOCSIFER_LOG_JSON", "false")
    monkeypatch.setenv("DOCSIFER_ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("DOCSIFER_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024))
    monkeypatch.setenv("DOCSIFER_MAX_CONCURRENT_CONVERSIONS", "2")
    monkeypatch.setenv("DOCSIFER_MAX_QUEUE_DEPTH", "4")
    monkeypatch.setenv("DOCSIFER_MAX_PER_IP_CONCURRENT", "5")
    monkeypatch.setenv("DOCSIFER_TMP_DIR", str(tmp_path))
    get_settings.cache_clear()
    return get_settings()


@pytest_asyncio.fixture
async def app(settings: Settings):
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def in_memory_analytics() -> AsyncIterator[AnalyticsService]:
    svc = AnalyticsService(store=InMemoryStore(), sync_interval_sec=1)
    await svc.start()
    try:
        yield svc
    finally:
        await svc.stop()
