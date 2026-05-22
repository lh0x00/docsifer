"""Circuit breaker for upstream dependencies (Section N.8)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ..exceptions import CircuitOpenError

T = TypeVar("T")


class CircuitBreaker:
    """Three-state circuit breaker (closed → open → half-open)."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout_sec: float = 60.0,
    ) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._reset_timeout = max(1.0, reset_timeout_sec)
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._half_open:
            return "half-open"
        return "open"

    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        async with self._lock:
            if self._opened_at is not None and not self._half_open:
                if time.monotonic() - self._opened_at >= self._reset_timeout:
                    self._half_open = True
                else:
                    raise CircuitOpenError("Upstream is unavailable")

        try:
            result = await fn(*args, **kwargs)
        except Exception:
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result

    async def _on_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open = False

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                self._half_open = False
