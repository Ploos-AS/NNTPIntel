from __future__ import annotations

import dataclasses
import datetime

from nntpintel.rollups import _bucket_delete_bounds, _utc

_ALLOWED_RESOLUTIONS = {"hour", "day", "month"}


@dataclasses.dataclass(frozen=True)
class PropagationRollupResult:
    resolution: str
    start: datetime.datetime
    end: datetime.datetime
    server_rows_written: int
    value_rows_written: int
    campaign_rows_written: int


def rebuild_propagation_rollups(
    conn,
    *,
    resolution: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> PropagationRollupResult:
    """Rebuild propagation, incident, and campaign rollups for a bounded UTC window.

    Presence semantics are conservative: response 223 with no error is present,
    response 430 with no error is absent, and every other outcome is unknown.
    First-seen delay is relative to NNTPIntel article registration, not authoritative
    NNTP feed transit time.
    """

    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour', 'day' or 'month'")
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("rollup end must be after start")

    delete_start, delete_end = _bucket_delete_bounds(start_utc, end_utc, resolution)
    for table in (
        "server_propagation_value_rollups",
        "server_propagation_rollups",
        "propagation_campaign_rollups",
    ):
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE resolution = %s
              AND bucket_start >= %s
              AND bucket_start < %s
            """,
            (resolution, delete_start, delete_end),
        )

    server_result = conn.execute(
        """
        WITH scoped AS (
            SELECT
                e.server_id,
                date_trunc(%s, po.observed_at) AS bucket_start,
                po.article_id,
                po.observed_at,
                po.response_code,
                po.error
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            WHERE po.observed_at >= %s AND po.observed_at < %s
        ), classified AS (
            SELECT *,
                CASE
                    WHEN response_code = 223 AND error IS NULL THEN 'present'
                    WHEN response_code = 430 AND error IS NULL THEN 'absent'
                    ELSE 'unknown'
                END AS presence_state
            FROM scoped
        ), first_present_all AS (
            SELECT e.server_id, po.article_id, MIN(po.observed_at) AS first_seen_at,
                   MIN(pa.first_registered_at) AS first_registered_at
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN propagation_articles pa ON pa.id = po.article_id
            WHERE po.response_code = 223 AND po.error IS NULL
            GROUP BY e.server_id, po.article_id
        ), first_present AS (
            SELECT * FROM first_present_all
            WHERE first_seen_at >= %s AND first_seen_at < %s
        ), probe_summary AS (
            SELECT server_id, bucket_start,
                   COUNT(*) AS probe_count,
                   COUNT(*) FILTER (WHERE presence_state = 'present') AS present_count,
                   COUNT(*) FILTER (WHERE presence_state = 'absent') AS absent_count,
                   COUNT(*) FILTER (WHERE presence_state = 'unknown') AS unknown_count,
                   COUNT(DISTINCT article_id) AS article_count
            FROM classified
            GROUP BY server_id, bucket_start
        ), delay_scoped AS (
            SELECT server_id, date_trunc(%s, first_seen_at) AS bucket_start,
                   EXTRACT(EPOCH FROM (first_seen_at - first_registered_at))::double precision AS delay_seconds
            FROM first_present
        ), delay_summary AS (
            SELECT server_id, bucket_start,
                   COUNT(*) AS delay_count,
                   AVG(delay_seconds)::double precision AS delay_avg,
                   MIN(delay_seconds)::double precision AS delay_min,
                   MAX(delay_seconds)::double precision AS delay_max
            FROM delay_scoped
            GROUP BY server_id, bucket_start
        ), incident_scoped AS (
            SELECT server_id, date_trunc(%s, started_at) AS bucket_start
            FROM propagation_incidents
            WHERE started_at >= %s AND started_at < %s
        ), incident_summary AS (
            SELECT server_id, bucket_start, COUNT(*) AS incident_count
            FROM incident_scoped
            GROUP BY server_id, bucket_start
        ), buckets AS (
            SELECT server_id, bucket_start FROM probe_summary
            UNION SELECT server_id, bucket_start FROM delay_summary
            UNION SELECT server_id, bucket_start FROM incident_summary
        )
        INSERT INTO server_propagation_rollups(
            server_id, resolution, bucket_start,
            probe_count, present_count, absent_count, unknown_count, presence_ratio,
            article_count, first_seen_delay_count, first_seen_delay_avg_seconds,
            first_seen_delay_min_seconds, first_seen_delay_max_seconds,
            incident_started_count, generated_at
        )
        SELECT
            b.server_id, %s, b.bucket_start,
            COALESCE(p.probe_count, 0), COALESCE(p.present_count, 0),
            COALESCE(p.absent_count, 0), COALESCE(p.unknown_count, 0),
            CASE WHEN COALESCE(p.present_count, 0) + COALESCE(p.absent_count, 0) > 0
                 THEN p.present_count::double precision /
                      (p.present_count + p.absent_count)::double precision
                 ELSE NULL END,
            COALESCE(p.article_count, 0), COALESCE(d.delay_count, 0),
            d.delay_avg, d.delay_min, d.delay_max,
            COALESCE(i.incident_count, 0), CURRENT_TIMESTAMP
        FROM buckets b
        LEFT JOIN probe_summary p USING (server_id, bucket_start)
        LEFT JOIN delay_summary d USING (server_id, bucket_start)
        LEFT JOIN incident_summary i USING (server_id, bucket_start)
        ORDER BY b.server_id, b.bucket_start
        """,
        (
            resolution,
            start_utc,
            end_utc,
            start_utc,
            end_utc,
            resolution,
            resolution,
            start_utc,
            end_utc,
            resolution,
        ),
    )

    values_result = conn.execute(
        """
        WITH values AS (
            SELECT server_id, date_trunc(%s, started_at) AS bucket_start,
                   'incident_kind'::text AS kind, lower(trim(kind)) AS value
            FROM propagation_incidents
            WHERE started_at >= %s AND started_at < %s AND trim(kind) <> ''
            UNION ALL
            SELECT server_id, date_trunc(%s, started_at) AS bucket_start,
                   'incident_severity'::text, lower(trim(severity))
            FROM propagation_incidents
            WHERE started_at >= %s AND started_at < %s AND trim(severity) <> ''
        )
        INSERT INTO server_propagation_value_rollups(
            server_id, resolution, bucket_start, kind, value,
            occurrence_count, generated_at
        )
        SELECT server_id, %s, bucket_start, kind, value, COUNT(*), CURRENT_TIMESTAMP
        FROM values
        GROUP BY server_id, bucket_start, kind, value
        ORDER BY server_id, bucket_start, kind, value
        """,
        (resolution, start_utc, end_utc, resolution, start_utc, end_utc, resolution),
    )

    campaign_result = conn.execute(
        """
        WITH created AS (
            SELECT bucket_start, COUNT(*) AS count
            FROM (
                SELECT date_trunc(%s, created_at) AS bucket_start
                FROM propagation_campaigns
                WHERE created_at >= %s AND created_at < %s
            ) x GROUP BY bucket_start
        ), completed AS (
            SELECT bucket_start, COUNT(*) AS count
            FROM (
                SELECT date_trunc(%s, completed_at) AS bucket_start
                FROM propagation_campaigns
                WHERE completed_at >= %s AND completed_at < %s
            ) x GROUP BY bucket_start
        ), closed AS (
            SELECT bucket_start, COUNT(*) AS count
            FROM (
                SELECT date_trunc(%s, COALESCE(completed_at, expires_at)) AS bucket_start
                FROM propagation_campaigns
                WHERE status <> 'active'
                  AND COALESCE(completed_at, expires_at) >= %s
                  AND COALESCE(completed_at, expires_at) < %s
            ) x GROUP BY bucket_start
        ), buckets AS (
            SELECT bucket_start FROM created
            UNION SELECT bucket_start FROM completed
            UNION SELECT bucket_start FROM closed
        )
        INSERT INTO propagation_campaign_rollups(
            resolution, bucket_start, created_count, completed_count,
            expired_or_closed_count, generated_at
        )
        SELECT %s, b.bucket_start,
               COALESCE(c.count, 0), COALESCE(d.count, 0), COALESCE(x.count, 0),
               CURRENT_TIMESTAMP
        FROM buckets b
        LEFT JOIN created c USING (bucket_start)
        LEFT JOIN completed d USING (bucket_start)
        LEFT JOIN closed x USING (bucket_start)
        ORDER BY b.bucket_start
        """,
        (
            resolution, start_utc, end_utc,
            resolution, start_utc, end_utc,
            resolution, start_utc, end_utc,
            resolution,
        ),
    )

    conn.commit()
    return PropagationRollupResult(
        resolution=resolution,
        start=start_utc,
        end=end_utc,
        server_rows_written=int(server_result.rowcount or 0),
        value_rows_written=int(values_result.rowcount or 0),
        campaign_rows_written=int(campaign_result.rowcount or 0),
    )


def rebuild_propagation_rollup_chain(
    conn,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[PropagationRollupResult, PropagationRollupResult, PropagationRollupResult]:
    return tuple(
        rebuild_propagation_rollups(conn, resolution=resolution, start=start, end=end)
        for resolution in ("hour", "day", "month")
    )
