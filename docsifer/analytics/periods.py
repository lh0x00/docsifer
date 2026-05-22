"""Period-key helpers for analytics buckets.

Uses ISO 8601 week numbering (``%G-W%V``) so values at year boundaries are
consistent across years (fixes the legacy ``%U`` bug).
"""

from __future__ import annotations

from datetime import datetime, timezone


def period_keys(now: datetime | None = None) -> tuple[str, str, str, str, str]:
    """Return ``(day, week, month, year, "total")`` for ``now`` (UTC by default)."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    day_key = now.strftime("%Y-%m-%d")
    week_key = now.strftime("%G-W%V")  # ISO week
    month_key = now.strftime("%Y-%m")
    year_key = now.strftime("%Y")
    return day_key, week_key, month_key, year_key, "total"
