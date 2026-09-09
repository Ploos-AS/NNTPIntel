from __future__ import annotations

import dataclasses
import datetime

_ALLOWED_RESOLUTIONS = {"hour", "day"}


@dataclasses.dataclass(frozen=True)
class RollupResult:
    resolution: str
    start: datetime.datetime
    end: datetime.datetime
    rows_written: int


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("rollup bounds must be timezone-aware")
    return value.astimezone(datetime.UTC)


def _bucket_floor(value: datetime.datetime, resolution: str) -> datetime.datetime:
    if resolution == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_delete_bounds(
    start: datetime.datetime,
    end: datetime.datetime,
    resolution: str,
) -> tuple[datetime.datetime, datetime.datetime]:
    bucket_start = _bucket_floor(start, resolution)
    last_included = end - datetime.timedelta(microseconds=1)
    last_bucket = _bucket_floor(last_included, resolution)
    step = datetime.timedelta(hours=1) if resolution == "hour" else datetime.timedelta(days=1)
    return bucket_start, last_bucket + step


def rebuild_server_observation_rollups(
    conn,
    *,
    resolution: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> RollupResult:
    """Rebuild server availability/latency rollups for a bounded UTC window.

    The operation is idempotent: every aggregate bucket touched by the requested
    raw-observation window is replaced before regeneration. Buckets are attributed
    by observation timestamp and server identity through endpoints.
    """

    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour' or 'day'")

    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("rollup end must be after start")

    delete_start, delete_end = _bucket_delete_bounds(start_utc, end_utc, resolution)
    conn.execute(
        """
        DELETE FROM server_observation_rollups
        WHERE resolution = %s
          AND bucket_start >= %s
          AND bucket_start < %s
        """,
        (resolution, delete_start, delete_end),
    )

    result = conn.execute(
        """
        WITH scoped AS (
            SELECT
                e.server_id,
                date_trunc(%s, o.observed_at) AS bucket_start,
                o.success,
                o.connect_ms
            FROM observations o
            JOIN endpoints e ON e.id = o.endpoint_id
            WHERE o.observed_at >= %s
              AND o.observed_at < %s
        )
        INSERT INTO server_observation_rollups(
            server_id,
            resolution,
            bucket_start,
            observation_count,
            success_count,
            failure_count,
            availability_ratio,
            connect_ms_count,
            connect_ms_avg,
            connect_ms_min,
            connect_ms_max,
            generated_at
        )
        SELECT
            server_id,
            %s AS resolution,
            bucket_start,
            COUNT(*) AS observation_count,
            COUNT(*) FILTER (WHERE success) AS success_count,
            COUNT(*) FILTER (WHERE NOT success) AS failure_count,
            AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END)::double precision
                AS availability_ratio,
            COUNT(connect_ms) AS connect_ms_count,
            AVG(connect_ms)::double precision AS connect_ms_avg,
            MIN(connect_ms)::double precision AS connect_ms_min,
            MAX(connect_ms)::double precision AS connect_ms_max,
            CURRENT_TIMESTAMP
        FROM scoped
        GROUP BY server_id, bucket_start
        ORDER BY server_id, bucket_start
        """,
        (resolution, start_utc, end_utc, resolution),
    )
    rows_written = int(result.rowcount or 0)
    conn.commit()
    return RollupResult(resolution, start_utc, end_utc, rows_written)


def rebuild_server_observation_rollup_chain(
    conn,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[RollupResult, RollupResult]:
    """Rebuild hourly and daily server observation rollups for one bounded window."""

    hourly = rebuild_server_observation_rollups(
        conn,
        resolution="hour",
        start=start,
        end=end,
    )
    daily = rebuild_server_observation_rollups(
        conn,
        resolution="day",
        start=start,
        end=end,
    )
    return hourly, daily
