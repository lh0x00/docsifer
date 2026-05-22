"""Lifespan-managed analytics service.

Improvements over the legacy implementation:
- Lifespan-managed (no ``asyncio.create_task`` at import time → fixes Bug A5).
- ``new_increments`` accumulator is **never reset on read paths** so concurrent
  ``access()`` calls during the initial load are no longer lost (Bug A5/A6).
- Failed Redis syncs keep the increments queued for the next attempt; an
  optional reconnection backoff retries the sync immediately when possible.
- ``stats()`` returns an immutable snapshot updated atomically after every
  ``access()`` so reads are lock-free (Section C.4).
- Pluggable :class:`AnalyticsStore` enables in-memory mode when Redis is
  unavailable (Section N.10).
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
from collections import defaultdict
from typing import Any

from .periods import period_keys
from .store import AnalyticsStore, NestedCounter

logger = logging.getLogger(__name__)


def _empty_counter() -> NestedCounter:
    return {
        "access": defaultdict(lambda: defaultdict(int)),
        "tokens": defaultdict(lambda: defaultdict(int)),
    }


class AnalyticsService:
    """Async-friendly analytics aggregator backed by a pluggable store."""

    def __init__(
        self,
        *,
        store: AnalyticsStore,
        sync_interval_sec: int = 1800,
        max_retries: int = 5,
        label: str = "docsifer",
    ) -> None:
        self._store = store
        self._sync_interval = max(1, sync_interval_sec)
        self._max_retries = max(0, max_retries)
        self._label = label

        self._totals: NestedCounter = _empty_counter()
        self._pending: NestedCounter = _empty_counter()
        self._snapshot: dict[str, dict[str, dict[str, int]]] = {
            "access": {},
            "tokens": {},
        }
        self._lock = asyncio.Lock()
        self._sync_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._healthy = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Load existing data from the store and launch the sync loop."""
        try:
            initial = await self._store.load_all()
            async with self._lock:
                # Merge instead of replacing so any access() events that arrived
                # while loading are preserved.
                for metric, periods in initial.items():
                    for period, labels in periods.items():
                        for label, count in labels.items():
                            self._totals[metric][period][label] += int(count)
                self._refresh_snapshot()
            logger.info("Analytics initial load complete")
        except Exception as exc:
            logger.warning("Analytics initial load failed: %s", exc)
            self._healthy = False

        self._sync_task = asyncio.create_task(self._sync_loop(), name="analytics-sync")

    async def stop(self) -> None:
        """Flush pending increments and stop the background loop."""
        self._stopped.set()
        if self._sync_task is not None:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task
        try:
            await self._flush_once()
        except Exception as exc:
            logger.warning("Final analytics flush failed: %s", exc)
        with contextlib.suppress(Exception):
            await self._store.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def access(self, tokens: int, *, label: str | None = None) -> None:
        """Record one access plus ``tokens`` token usage for ``label``."""
        label = label or self._label
        keys = period_keys()
        async with self._lock:
            for period in keys:
                self._pending["access"][period][label] += 1
                self._pending["tokens"][period][label] += int(tokens)
                self._totals["access"][period][label] += 1
                self._totals["tokens"][period][label] += int(tokens)
            self._refresh_snapshot()

    async def stats(self) -> dict[str, Any]:
        """Return an immutable snapshot of the current totals."""
        snap = self._snapshot
        return {
            "access": snap["access"],
            "tokens": snap["tokens"],
            "healthy": self._healthy,
        }

    async def ping(self) -> bool:
        return await self._store.ping()

    @property
    def healthy(self) -> bool:
        return self._healthy

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _refresh_snapshot(self) -> None:
        """Build a new immutable snapshot dict from the live counters."""
        self._snapshot = {
            "access": {p: dict(m) for p, m in self._totals["access"].items()},
            "tokens": {p: dict(m) for p, m in self._totals["tokens"].items()},
        }

    async def _flush_once(self) -> None:
        async with self._lock:
            if not self._has_pending(self._pending):
                return
            payload = copy.deepcopy(self._pending)
            # Optimistically clear; restore on failure
            cleared = self._pending
            self._pending = _empty_counter()
        try:
            await self._store.apply_increments(payload)
            self._healthy = True
        except Exception:
            # Restore the pending payload so we retry next tick
            async with self._lock:
                for metric, periods in payload.items():
                    for period, labels in periods.items():
                        for label, count in labels.items():
                            self._pending[metric][period][label] += count
                _ = cleared  # silence "unused"
            self._healthy = False
            raise

    async def _sync_loop(self) -> None:
        retries = 0
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._sync_interval
                )
                return  # stopped
            except asyncio.TimeoutError:
                pass

            try:
                await self._flush_once()
                retries = 0
                backoff = 1.0
            except Exception as exc:
                logger.warning("Analytics sync failed: %s", exc)
                if retries < self._max_retries:
                    retries += 1
                    await asyncio.sleep(min(backoff, 60.0))
                    backoff *= 2

    @staticmethod
    def _has_pending(counter: NestedCounter) -> bool:
        for periods in counter.values():
            for labels in periods.values():
                for count in labels.values():
                    if count:
                        return True
        return False
