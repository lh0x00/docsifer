"""Storage backends for analytics counters.

The :class:`AnalyticsStore` protocol abstracts the persistence layer so the
:class:`docsifer.analytics.service.AnalyticsService` can switch between
Upstash Redis (production) and an :class:`InMemoryStore` (tests / local dev /
graceful-degraded mode when Redis is unavailable).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from functools import partial
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Top-level metric → period → label → count
NestedCounter = dict[str, dict[str, dict[str, int]]]


def _empty_counter() -> NestedCounter:
    return {
        "access": defaultdict(lambda: defaultdict(int)),
        "tokens": defaultdict(lambda: defaultdict(int)),
    }


@runtime_checkable
class AnalyticsStore(Protocol):
    async def load_all(self) -> NestedCounter: ...

    async def apply_increments(self, increments: NestedCounter) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory store (fallback / tests)
# ---------------------------------------------------------------------------
class InMemoryStore:
    def __init__(self) -> None:
        self._data: NestedCounter = _empty_counter()

    async def load_all(self) -> NestedCounter:
        return _empty_counter()

    async def apply_increments(self, increments: NestedCounter) -> None:
        for metric, periods in increments.items():
            for period, models in periods.items():
                for label, count in models.items():
                    if count:
                        self._data[metric][period][label] += count

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:  # pragma: no cover - nothing to do
        return None


# ---------------------------------------------------------------------------
# Upstash Redis (HTTP) store
# ---------------------------------------------------------------------------
class UpstashStore:
    """Upstash Redis-backed store using batched pipeline writes (Section N.9)."""

    KEY_PREFIX = "analytics"

    def __init__(self, url: str, token: str | None) -> None:
        from upstash_redis import Redis as UpstashRedis  # lazy import

        self._UpstashRedis = UpstashRedis
        self._url = url
        self._token = token
        self._client = self._make_client()

    def _make_client(self):  # type: ignore[no-untyped-def]
        return self._UpstashRedis(url=self._url, token=self._token)

    async def load_all(self) -> NestedCounter:
        loop = asyncio.get_running_loop()
        result: NestedCounter = _empty_counter()
        for metric in ("access", "tokens"):
            cursor = 0
            pattern = f"{self.KEY_PREFIX}:{metric}:*"
            while True:
                scan = await loop.run_in_executor(
                    None,
                    partial(self._client.scan, cursor=cursor, match=pattern, count=1000),
                )
                cursor = scan[0]
                keys = scan[1] or []
                for key in keys:
                    period = key.split(":", 2)[-1]
                    data = await loop.run_in_executor(None, partial(self._client.hgetall, key))
                    for label, count in (data or {}).items():
                        try:
                            result[metric][period][label] = int(count)
                        except (TypeError, ValueError):
                            continue
                if int(cursor) == 0:
                    break
        return result

    async def apply_increments(self, increments: NestedCounter) -> None:
        loop = asyncio.get_running_loop()
        ops: list = []
        for metric, periods in increments.items():
            for period, models in periods.items():
                key = f"{self.KEY_PREFIX}:{metric}:{period}"
                for label, count in models.items():
                    if count:
                        ops.append((key, label, int(count)))
        if not ops:
            return

        # Prefer pipeline when available (single HTTP round trip)
        pipeline = getattr(self._client, "pipeline", None)
        if callable(pipeline):

            def _run() -> None:
                pipe = pipeline()
                for key, label, count in ops:
                    pipe.hincrby(key, label, count)
                pipe.exec()

            await loop.run_in_executor(None, _run)
            return

        # Fallback: parallel single-op calls
        await asyncio.gather(
            *(
                loop.run_in_executor(None, partial(self._client.hincrby, key, label, count))
                for key, label, count in ops
            )
        )

    async def ping(self) -> bool:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._client.ping)
            return True
        except Exception as exc:
            logger.warning("Upstash ping failed: %s", exc)
            return False

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        with logger_suppress("Upstash close failed"):
            await loop.run_in_executor(None, self._client.close)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
class logger_suppress:  # noqa: N801 - tiny utility, lower-case name for context-manager idiom
    """Context manager that logs (rather than raises) any exception."""

    def __init__(self, message: str) -> None:
        self._message = message

    def __enter__(self) -> logger_suppress:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        if exc_type is not None:
            logger.warning("%s: %s", self._message, exc)
        return True

    async def __aenter__(self) -> logger_suppress:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        if exc_type is not None:
            logger.warning("%s: %s", self._message, exc)
        return True
