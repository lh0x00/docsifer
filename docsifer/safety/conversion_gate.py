"""Bounded global concurrency / queue (Section N.5)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator

from ..exceptions import QueueFullError


class ConversionGate:
    """Cap concurrent conversions and queue depth, fail fast otherwise."""

    def __init__(self, *, max_concurrent: int, max_queue: int) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._max_queue = max(0, max_queue)
        self._waiting = 0
        self._inflight = 0
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "max_concurrent": self._max_concurrent,
            "max_queue": self._max_queue,
            "waiting": self._waiting,
            "inflight": self._inflight,
        }

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        async with self._lock:
            in_use = self._inflight + self._waiting
            # Queue is engaged only after capacity is fully used.
            queued = max(0, in_use - self._max_concurrent)
            if queued >= self._max_queue and in_use >= self._max_concurrent:
                raise QueueFullError(
                    "Conversion queue full",
                    details={"max_queue": self._max_queue},
                )
            self._waiting += 1

        try:
            await self._semaphore.acquire()
        except BaseException:
            async with self._lock:
                self._waiting -= 1
            raise

        async with self._lock:
            self._waiting -= 1
            self._inflight += 1
        try:
            yield
        finally:
            async with self._lock:
                self._inflight -= 1
            self._semaphore.release()
