from datetime import datetime, timezone

from docsifer.analytics.periods import period_keys


def test_iso_week_format() -> None:
    # 2025-01-01 is a Wednesday — ISO week 01 of 2025
    day, week, month, year, total = period_keys(datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert day == "2025-01-01"
    assert week == "2025-W01"
    assert month == "2025-01"
    assert year == "2025"
    assert total == "total"


def test_iso_week_year_boundary() -> None:
    # 2024-12-30 (Mon) belongs to ISO week 01 of 2025
    day, week, *_ = period_keys(datetime(2024, 12, 30, tzinfo=timezone.utc))
    assert week == "2025-W01"
    assert day == "2024-12-30"


def test_naive_datetime_assumed_utc() -> None:
    day, *_ = period_keys(datetime(2025, 6, 15))
    assert day == "2025-06-15"
