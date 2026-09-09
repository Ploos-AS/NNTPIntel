from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


_ALLOWED_RESOLUTIONS = {"hour", "day"}


@dataclass(frozen=True)
class RollupResult:
    resolution: str
    start: datetime
    end: datetime
    rows_written: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("rollup bounds must be timezone-aware")
    return value.astimezone(timezone.utc)


def rebuild_server_observation_rollups(
    conn,
    *,
    resolution: str,
    start: datetime,
    end: datetime,
) -> RollupResult:
    """Rebuild server availability/latency rollups for a bounded UTC window.

    The operation is idempotent: rows for the requested resolution/window are
    replaced from raw observations in one transaction. Buckets are attributed by
    observation timestamp and server identity through endpoints.
    """

    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour' or 'day'")

    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("rollup end must be after start")

    conn.execute(
        """
        DELETE FROM server_observation_rollups
        WHERE resolution = %s
          AND bucket_start >= %s
          AND bucket_start < %s
        """,
        (resolution, start_utc, end_utc),
    )

    result = conn.execute(
        """
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
            e.server_id,
            %s AS resolution,
            date_trunc(%s, o.observed_at) AS bucket_start,
            COUNT(*) AS observation_count,
            COUNT(*) FILTER (WHERE o.success) AS success_count,
            COUNT(*) FILTER (WHERE NOT o.success) AS failure_count,
            AVG(CASE WHEN o.success THEN 1.0 ELSE 0.0 END)::double precision
                AS availability_ratio,
            COUNT(o.connect_ms) AS connect_ms_count,
            AVG(o.connect_ms)::double precision AS connect_ms_avg,
            MIN(o.connect_ms)::double precision AS connect_ms_min,
            MAX(o.connect_ms)::double precision AS connect_ms_max,
            CURRENT_TIMESTAMP
        FROM observations o
        JOIN endpoints e ON e.id = o.endpoint_id
        WHERE o.observed_at >= %s
          AND o.observed_at < %s
        GROUP BY e.server_id, date_trunc(%s, o.observed_at)
        ORDER BY e.server_id, bucket_start
        """,
        (resolution, resolution, start_utc, end_utc, resolution),
    )
    rows_written = int(result.rowcount or 0)
    conn.commit()
    return RollupResult(resolution, start_utc, end_utc, rows_written)


def rebuild_server_observation_rollup_chain(
    conn,
    *,
    start: datetime,
    end: datetime,
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
