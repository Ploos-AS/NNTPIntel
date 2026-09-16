from __future__ import annotations

import datetime

import pytest

from nntpintel.statistics import validate_statistics_range


def _utc(year: int, month: int, day: int) -> datetime.datetime:
    return datetime.datetime(year, month, day, tzinfo=datetime.UTC)


def test_hour_resolution_accepts_bounded_month():
    window = validate_statistics_range(
        resolution="hour", start=_utc(2026, 1, 1), end=_utc(2026, 2, 1)
    )
    assert window.resolution == "hour"


def test_hour_resolution_rejects_multi_year_range():
    with pytest.raises(ValueError, match="use a coarser resolution"):
        validate_statistics_range(
            resolution="hour", start=_utc(2024, 1, 1), end=_utc(2026, 1, 1)
        )


def test_day_resolution_accepts_two_year_boundary():
    validate_statistics_range(
        resolution="day", start=_utc(2024, 1, 1), end=_utc(2026, 1, 1)
    )


def test_day_resolution_rejects_long_multi_year_range():
    with pytest.raises(ValueError, match="maximum is 732"):
        validate_statistics_range(
            resolution="day", start=_utc(2020, 1, 1), end=_utc(2026, 1, 1)
        )


def test_all_time_requires_month_resolution():
    with pytest.raises(ValueError, match="all-time statistics require month resolution"):
        validate_statistics_range(resolution="day")
    validate_statistics_range(resolution="month")


def test_month_resolution_is_bounded_to_twenty_five_years():
    with pytest.raises(ValueError, match="maximum is 300"):
        validate_statistics_range(
            resolution="month", start=_utc(1990, 1, 1), end=_utc(2026, 1, 1)
        )
