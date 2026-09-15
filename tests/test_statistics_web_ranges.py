from __future__ import annotations

import datetime

import pytest

from nntpintel.statistics_web import resolve_web_range


def test_custom_range_is_parsed_and_normalized_to_utc() -> None:
    start, end, label = resolve_web_range(
        resolution="hour",
        preset="7d",
        start_text="2026-09-01T02:00:00+02:00",
        end_text="2026-09-02T02:00:00+02:00",
    )
    assert start == datetime.datetime(2026, 9, 1, 0, 0, tzinfo=datetime.UTC)
    assert end == datetime.datetime(2026, 9, 2, 0, 0, tzinfo=datetime.UTC)
    assert label == "custom"


def test_custom_range_requires_both_bounds() -> None:
    with pytest.raises(ValueError, match="start and end must be supplied together"):
        resolve_web_range(
            resolution="day",
            preset="30d",
            start_text="2026-09-01T00:00:00Z",
        )


def test_custom_range_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timestamps must include a timezone"):
        resolve_web_range(
            resolution="day",
            preset="30d",
            start_text="2026-09-01T00:00:00",
            end_text="2026-09-02T00:00:00",
        )


def test_custom_range_requires_end_after_start() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        resolve_web_range(
            resolution="day",
            preset="30d",
            start_text="2026-09-02T00:00:00Z",
            end_text="2026-09-01T00:00:00Z",
        )
