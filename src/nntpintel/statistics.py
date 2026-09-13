from __future__ import annotations

import datetime
from dataclasses import dataclass

from nntpintel.storage_backend import StorageBackend

_ALLOWED_RESOLUTIONS = {"hour", "day", "month"}


@dataclass(frozen=True)
class StatisticsRange:
    resolution: str
    start: datetime.datetime | None = None
    end: datetime.datetime | None = None


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("statistics timestamps must include a timezone")
    return value.astimezone(datetime.UTC)


def parse_statistics_time(value: str) -> datetime.datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("statistics timestamps must be ISO 8601") from exc
    return _utc(parsed)


def validate_statistics_range(
    *,
    resolution: str,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
) -> StatisticsRange:
    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour', 'day' or 'month'")
    if (start is None) != (end is None):
        raise ValueError("start and end must be supplied together")
    if start is None:
        return StatisticsRange(resolution=resolution)
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("end must be after start")
    return StatisticsRange(resolution=resolution, start=start_utc, end=end_utc)


def server_statistics(
    storage: StorageBackend,
    *,
    resolution: str,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    server_id: int | None = None,
) -> dict:
    """Return public server availability/latency statistics from production rollups only."""

    if storage.backend_name != "postgresql":
        raise RuntimeError("multi-year statistics require the PostgreSQL production backend")
    window = validate_statistics_range(resolution=resolution, start=start, end=end)
    if server_id is not None and server_id <= 0:
        raise ValueError("server_id must be a positive integer")

    where = ["r.resolution = %s"]
    params: list[object] = [window.resolution]
    if window.start is not None:
        where.extend(["r.bucket_start >= %s", "r.bucket_start < %s"])
        params.extend([window.start, window.end])
    if server_id is not None:
        where.append("r.server_id = %s")
        params.append(server_id)

    query = f"""
        SELECT
            r.server_id,
            s.host,
            r.bucket_start,
            r.observation_count,
            r.success_count,
            r.failure_count,
            r.availability_ratio,
            r.connect_ms_count,
            r.connect_ms_avg,
            r.connect_ms_min,
            r.connect_ms_max,
            r.generated_at
        FROM server_observation_rollups r
        JOIN servers s ON s.id = r.server_id
        WHERE {' AND '.join(where)}
        ORDER BY r.bucket_start ASC, r.server_id ASC
    """
    with storage.connect() as conn:
        rows = [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]

    return {
        "api_version": "v1",
        "metric_family": "server_availability_latency",
        "source": "server_observation_rollups",
        "resolution": window.resolution,
        "range": {
            "start": window.start,
            "end": window.end,
            "all_time": window.start is None,
        },
        "server_id": server_id,
        "rows": rows,
    }
