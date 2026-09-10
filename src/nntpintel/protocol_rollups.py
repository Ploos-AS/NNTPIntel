from __future__ import annotations

import dataclasses
import datetime

from nntpintel.rollups import _bucket_delete_bounds, _utc

_ALLOWED_RESOLUTIONS = {"hour", "day", "month"}


@dataclasses.dataclass(frozen=True)
class ProtocolRollupResult:
    resolution: str
    start: datetime.datetime
    end: datetime.datetime
    summary_rows_written: int
    value_rows_written: int


def rebuild_server_protocol_rollups(
    conn,
    *,
    resolution: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> ProtocolRollupResult:
    """Rebuild normalized TLS/capability rollups for a bounded observation window."""

    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour', 'day' or 'month'")
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("rollup end must be after start")

    delete_start, delete_end = _bucket_delete_bounds(start_utc, end_utc, resolution)
    for table in ("server_protocol_value_rollups", "server_protocol_rollups"):
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE resolution = %s
              AND bucket_start >= %s
              AND bucket_start < %s
            """,
            (resolution, delete_start, delete_end),
        )

    summary = conn.execute(
        """
        WITH scoped AS (
            SELECT
                e.server_id,
                date_trunc(%s, o.observed_at) AS bucket_start,
                CASE WHEN jsonb_typeof(o.tls_json) = 'object'
                     THEN COALESCE((o.tls_json ->> 'enabled')::boolean, false)
                     ELSE false END AS tls_enabled,
                CASE WHEN jsonb_typeof(o.capabilities_json) = 'array'
                     THEN jsonb_array_length(o.capabilities_json)
                     ELSE 0 END AS capability_count
            FROM observations o
            JOIN endpoints e ON e.id = o.endpoint_id
            WHERE o.observed_at >= %s AND o.observed_at < %s
        )
        INSERT INTO server_protocol_rollups(
            server_id, resolution, bucket_start, observation_count,
            tls_enabled_count, tls_ratio, capabilities_observed_count,
            capability_entry_count, generated_at
        )
        SELECT
            server_id, %s, bucket_start, COUNT(*),
            COUNT(*) FILTER (WHERE tls_enabled),
            AVG(CASE WHEN tls_enabled THEN 1.0 ELSE 0.0 END)::double precision,
            COUNT(*) FILTER (WHERE capability_count > 0),
            SUM(capability_count), CURRENT_TIMESTAMP
        FROM scoped
        GROUP BY server_id, bucket_start
        ORDER BY server_id, bucket_start
        """,
        (resolution, start_utc, end_utc, resolution),
    )

    values = conn.execute(
        """
        WITH scoped AS (
            SELECT e.server_id, date_trunc(%s, o.observed_at) AS bucket_start,
                   o.tls_json, o.capabilities_json
            FROM observations o
            JOIN endpoints e ON e.id = o.endpoint_id
            WHERE o.observed_at >= %s AND o.observed_at < %s
        ), values AS (
            SELECT server_id, bucket_start, 'tls_protocol'::text AS kind,
                   tls_json ->> 'protocol' AS value
            FROM scoped
            WHERE jsonb_typeof(tls_json) = 'object'
              AND COALESCE(tls_json ->> 'protocol', '') <> ''
            UNION ALL
            SELECT server_id, bucket_start, 'tls_cipher'::text,
                   tls_json ->> 'cipher'
            FROM scoped
            WHERE jsonb_typeof(tls_json) = 'object'
              AND COALESCE(tls_json ->> 'cipher', '') <> ''
            UNION ALL
            SELECT s.server_id, s.bucket_start, 'capability'::text,
                   upper(split_part(trim(cap.value), ' ', 1))
            FROM scoped s
            CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(s.capabilities_json) = 'array'
                     THEN s.capabilities_json ELSE '[]'::jsonb END
            ) AS cap(value)
            WHERE trim(cap.value) <> ''
        )
        INSERT INTO server_protocol_value_rollups(
            server_id, resolution, bucket_start, kind, value,
            occurrence_count, generated_at
        )
        SELECT server_id, %s, bucket_start, kind, value, COUNT(*), CURRENT_TIMESTAMP
        FROM values
        GROUP BY server_id, bucket_start, kind, value
        ORDER BY server_id, bucket_start, kind, value
        """,
        (resolution, start_utc, end_utc, resolution),
    )
    conn.commit()
    return ProtocolRollupResult(
        resolution=resolution,
        start=start_utc,
        end=end_utc,
        summary_rows_written=int(summary.rowcount or 0),
        value_rows_written=int(values.rowcount or 0),
    )


def rebuild_server_protocol_rollup_chain(
    conn,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[ProtocolRollupResult, ProtocolRollupResult, ProtocolRollupResult]:
    return tuple(
        rebuild_server_protocol_rollups(
            conn,
            resolution=resolution,
            start=start,
            end=end,
        )
        for resolution in ("hour", "day", "month")
    )
