from __future__ import annotations

import datetime

_MAX_BUCKETS = {
    "hour": 24 * 31,
    "day": 366 * 2,
    "month": 12 * 25,
}


def _estimated_buckets(
    resolution: str, start: datetime.datetime, end: datetime.datetime
) -> int:
    span = end - start
    if resolution == "hour":
        return max(1, (int(span.total_seconds()) + 3599) // 3600)
    if resolution == "day":
        return max(1, (int(span.total_seconds()) + 86399) // 86400)
    if resolution == "month":
        return max(1, (end.year - start.year) * 12 + end.month - start.month + 1)
    raise ValueError("resolution must be 'hour', 'day' or 'month'")


def enforce_public_query_cost(
    *,
    resolution: str,
    start: datetime.datetime | None,
    end: datetime.datetime | None,
) -> None:
    """Reject public rollup queries whose requested bucket count is too expensive."""
    if start is None or end is None:
        if resolution != "month":
            raise ValueError("all-time statistics require month resolution")
        return

    buckets = _estimated_buckets(resolution, start, end)
    maximum = _MAX_BUCKETS[resolution]
    if buckets > maximum:
        raise ValueError(
            f"statistics range is too large for {resolution} resolution "
            f"({buckets} buckets requested; maximum is {maximum}); use a coarser resolution"
        )
