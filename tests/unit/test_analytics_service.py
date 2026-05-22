import pytest

from docsifer.analytics import AnalyticsService, InMemoryStore


@pytest.mark.asyncio
async def test_access_updates_snapshot() -> None:
    svc = AnalyticsService(store=InMemoryStore(), sync_interval_sec=3600)
    await svc.start()
    try:
        await svc.access(10)
        await svc.access(5)
        snap = await svc.stats()
        access = snap["access"]["total"]
        tokens = snap["tokens"]["total"]
        assert access["docsifer"] == 2
        assert tokens["docsifer"] == 15
    finally:
        await svc.stop()


@pytest.mark.asyncio
async def test_failed_sync_keeps_pending() -> None:
    class _Broken(InMemoryStore):
        async def apply_increments(self, increments) -> None:  # type: ignore[override]
            raise RuntimeError("redis down")

    svc = AnalyticsService(store=_Broken(), sync_interval_sec=3600)
    await svc.start()
    try:
        await svc.access(7)
        # Manually trigger a flush via the private API (unit test)
        with pytest.raises(RuntimeError):
            await svc._flush_once()  # noqa: SLF001
        # Pending was restored, totals untouched
        snap = await svc.stats()
        assert snap["tokens"]["total"]["docsifer"] == 7
        assert svc._pending["tokens"]["total"]["docsifer"] == 7  # noqa: SLF001
    finally:
        await svc.stop()
