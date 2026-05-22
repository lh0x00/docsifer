"""Memory / disk admission control to prevent OOM (Section N.4)."""

from __future__ import annotations

import logging
from pathlib import Path

from ..exceptions import ResourceExhaustedError

logger = logging.getLogger(__name__)

try:  # pragma: no cover - environment dependent
    import psutil

    _HAS_PSUTIL = True
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


class ResourceGuard:
    """Reject new conversions when the host is approaching exhaustion."""

    def __init__(
        self,
        *,
        min_free_memory_mb: int,
        min_free_disk_mb: int,
        tmp_dir: Path,
        memory_overhead_factor: int = 3,
        memory_overhead_floor_mb: int = 256,
    ) -> None:
        self._min_free_memory_mb = min_free_memory_mb
        self._min_free_disk_mb = min_free_disk_mb
        self._tmp_dir = tmp_dir
        self._overhead_factor = memory_overhead_factor
        self._overhead_floor_mb = memory_overhead_floor_mb

    def check(self, expected_size_bytes: int = 0) -> None:
        """Raise :class:`ResourceExhaustedError` when limits are exceeded."""
        if not _HAS_PSUTIL:
            return  # cannot enforce without psutil; fail-open

        # Memory
        avail_mb = psutil.virtual_memory().available // (1024 * 1024)
        size_mb = expected_size_bytes // (1024 * 1024)
        needed_mb = max(
            self._min_free_memory_mb,
            size_mb * self._overhead_factor + self._overhead_floor_mb,
        )
        if avail_mb < needed_mb:
            raise ResourceExhaustedError(
                f"Insufficient memory: need {needed_mb} MB, have {avail_mb} MB",
                details={"available_mb": avail_mb, "needed_mb": needed_mb},
            )

        # Disk
        try:
            disk_free_mb = psutil.disk_usage(str(self._tmp_dir)).free // (1024 * 1024)
        except Exception as exc:
            logger.debug("disk_usage check failed: %s", exc)
            return
        if disk_free_mb < self._min_free_disk_mb:
            raise ResourceExhaustedError(
                f"Insufficient disk space: {disk_free_mb} MB free",
                details={"disk_free_mb": disk_free_mb},
            )
