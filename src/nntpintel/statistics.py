from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

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


def _json_value(value: object) -> object:
    if isinstance(value, datetime.datetime):
        normalized = _utc(value).isoformat()
        return normalized.replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_rows(rows: list[object]) -> list[dict]:
    return [
        {key: _json_value(value) for key, value in dict(row).items()}
        for row in rows
    ]


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


def _statistics_filter(
    window: StatisticsRange,
    server_id: int | None,
) -> tuple[list[str], list[object]]:
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
    return where, params


def _statistics_range_payload(window: StatisticsRange) -> dict:
    return {
        "start": _json_value(window.start),
        "end": _json_value(window.end),
        "all_time": window.start is None,
    }


def server_statistics(
    storage: StorageBackend,
    *,
    resolution: str,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    server_id: int | None = None,
) -> dict:
    """Return public server availability/latency statistics from production rollups only."""

    if getattr(storage, "backend_name", "sqlite") != "postgresql":
        raise RuntimeError("multi-year statistics require the PostgreSQL production backend")
    window = validate_statistics_range(resolution=resolution, start=start, end=end)
    where, params = _statistics_filter(window, server_id)

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
        rows = _json_rows(conn.execute(query, tuple(params)).fetchall())

    return {
        "api_version": "v1",
        "metric_family": "server_availability_latency",
        "source": "server_observation_rollups",
        "resolution": window.resolution,
        "range": _statistics_range_payload(window),
        "server_id": server_id,
        "rows": rows,
    }


def group_statistics(
    storage: StorageBackend,
    *,
    resolution: str,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    server_id: int | None = None,
) -> dict:
    """Return public group/hierarchy inventory and change statistics from rollups only."""

    if getattr(storage, "backend_name", "sqlite") != "postgresql":
        raise RuntimeError("multi-year statistics require the PostgreSQL production backend")
    window = validate_statistics_range(resolution=resolution, start=start, end=end)
    where, params = _statistics_filter(window, server_id)

    summary_query = f"""
        SELECT
            r.server_id,
            s.host,
            r.bucket_start,
            r.inventory_count,
            r.snapshot_count,
            r.observed_group_count,
            r.observed_hierarchy_count,
            r.event_count,
            r.generated_at
        FROM server_group_rollups r
        JOIN servers s ON s.id = r.server_id
        WHERE {' AND '.join(where)}
        ORDER BY r.bucket_start ASC, r.server_id ASC
    """
    value_query = f"""
        SELECT
            r.server_id,
            s.host,
            r.bucket_start,
            r.kind,
            r.value,
            r.occurrence_count,
            r.generated_at
        FROM server_group_value_rollups r
        JOIN servers s ON s.id = r.server_id
        WHERE {' AND '.join(where)}
        ORDER BY r.bucket_start ASC, r.server_id ASC, r.kind ASC, r.value ASC
    """
    with storage.connect() as conn:
        rows = _json_rows(conn.execute(summary_query, tuple(params)).fetchall())
        values = _json_rows(conn.execute(value_query, tuple(params)).fetchall())

    return {
        "api_version": "v1",
        "metric_family": "group_hierarchy_inventory_changes",
        "source": ["server_group_rollups", "server_group_value_rollups"],
        "resolution": window.resolution,
        "range": _statistics_range_payload(window),
        "server_id": server_id,
        "rows": rows,
        "values": values,
    }
