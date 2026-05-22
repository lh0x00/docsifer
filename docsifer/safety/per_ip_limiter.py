"""Per-IP fairness — limit how many conversions a single IP can run at once
(Section N.6).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import AsyncIterator

from ..exceptions import TooManyRequestsError


class _Slot:
    __slots__ = ("active", "last_seen")

    def __init__(self) -> None:
        self.active = 0
        self.last_seen = time.monotonic()


class PerIPLimiter:
    """Bound the number of concurrent in-flight requests per IP."""

    def __init__(self, *, max_per_ip: int, idle_evict_sec: int = 600) -> None:
        self._max_per_ip = max(1, max_per_ip)
        self._slots: dict[str, _Slot] = {}
        self._lock = asyncio.Lock()
        self._idle_evict_sec = idle_evict_sec

    @contextlib.asynccontextmanager
    async def acquire(self, ip: str) -> AsyncIterator[None]:
        await self._enter(ip)
        try:
            yield
        finally:
            await self._leave(ip)

    async def _enter(self, ip: str) -> None:
        async with self._lock:
            self._evict_idle()
            slot = self._slots.setdefault(ip, _Slot())
            if slot.active >= self._max_per_ip:
                raise TooManyRequestsError(
                    "Too many concurrent requests for this client",
                    details={"max_per_ip": self._max_per_ip},
                )
            slot.active += 1
            slot.last_seen = time.monotonic()

    async def _leave(self, ip: str) -> None:
        async with self._lock:
            slot = self._slots.get(ip)
            if slot is None:
                return
            slot.active = max(0, slot.active - 1)
            slot.last_seen = time.monotonic()

    def _evict_idle(self) -> None:
        now = time.monotonic()
        cutoff = now - self._idle_evict_sec
        stale = [ip for ip, s in self._slots.items() if s.active == 0 and s.last_seen < cutoff]
        for ip in stale:
            self._slots.pop(ip, None)
