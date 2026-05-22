"""Memory watchdog — graceful self-restart before the kernel OOM-kills us
(Section N.13).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

logger = logging.getLogger(__name__)

try:  # pragma: no cover - environment dependent
    import psutil

    _HAS_PSUTIL = True
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


async def memory_watchdog_loop(
    *,
    threshold_pct: float = 90.0,
    interval_sec: int = 30,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Periodically inspect process RSS and request graceful restart on overrun."""
    if not _HAS_PSUTIL:
        logger.info("psutil unavailable; memory watchdog disabled")
        return

    proc = psutil.Process()
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            pass

        try:
            usage = proc.memory_percent()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("memory_percent failed: %s", exc)
            continue

        if usage > threshold_pct:
            logger.warning(
                "Memory pressure %.1f%% > %.1f%% — sending SIGTERM",
                usage,
                threshold_pct,
            )
            os.kill(os.getpid(), signal.SIGTERM)
            return
