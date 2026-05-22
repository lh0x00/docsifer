"""Background disk cleanup loop (Section N.11).

Removes stale files matching ``docsifer-*`` in the configured tmp directory so
long-running containers don't accumulate gigabytes of leftovers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def disk_cleanup_loop(
    *,
    tmp_dir: Path,
    ttl_sec: int = 3600,
    interval_sec: int = 600,
    pattern: str = "docsifer-*",
    stop_event: asyncio.Event | None = None,
) -> None:
    """Sweep ``tmp_dir`` every ``interval_sec`` and unlink stale temp files."""
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
            return
        except asyncio.TimeoutError:
            pass

        try:
            removed = await asyncio.to_thread(_sweep_once, tmp_dir, pattern, ttl_sec)
            if removed:
                logger.info("Disk cleanup removed %d stale file(s)", removed)
        except Exception as exc:
            logger.warning("Disk cleanup failed: %s", exc)


def _sweep_once(tmp_dir: Path, pattern: str, ttl_sec: int) -> int:
    """Synchronous sweep — meant to be run via ``asyncio.to_thread``."""
    now = time.time()
    removed = 0
    for entry in tmp_dir.glob(pattern):
        try:
            if now - entry.stat().st_mtime > ttl_sec and entry.is_file():
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:
            logger.debug("Could not remove %s: %s", entry, exc)
    return removed
