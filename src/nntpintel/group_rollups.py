from __future__ import annotations

import dataclasses
import datetime

from nntpintel.rollups import _bucket_delete_bounds, _utc

_ALLOWED_RESOLUTIONS = {"hour", "day", "month"}


@dataclasses.dataclass(frozen=True)
class GroupRollupResult:
    resolution: str
    start: datetime.datetime
    end: datetime.datetime
    summary_rows_written: int
    value_rows_written: int


def rebuild_server_group_rollups(
    conn,
    *,
    resolution: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> GroupRollupResult:
    """Rebuild group, hierarchy, posting-status and event rollups for a UTC window."""

    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour', 'day' or 'month'")
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("rollup end must be after start")

    delete_start, delete_end = _bucket_delete_bounds(start_utc, end_utc, resolution)
    for table in ("server_group_value_rollups", "server_group_rollups"):
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
        WITH snapshot_scoped AS (
            SELECT
                e.server_id,
                gs.endpoint_id,
                gs.observed_at,
                date_trunc(%s, gs.observed_at) AS bucket_start,
                gs.newsgroup_id,
                n.hierarchy_id
            FROM group_snapshots gs
            JOIN endpoints e ON e.id = gs.endpoint_id
            JOIN newsgroups n ON n.id = gs.newsgroup_id
            WHERE gs.observed_at >= %s AND gs.observed_at < %s
        ), snapshot_summary AS (
            SELECT
                server_id,
                bucket_start,
                COUNT(DISTINCT (endpoint_id, observed_at)) AS inventory_count,
                COUNT(*) AS snapshot_count,
                COUNT(DISTINCT newsgroup_id) AS observed_group_count,
                COUNT(DISTINCT hierarchy_id) AS observed_hierarchy_count
            FROM snapshot_scoped
            GROUP BY server_id, bucket_start
        ), event_summary AS (
            SELECT
                e.server_id,
                date_trunc(%s, ge.observed_at) AS bucket_start,
                COUNT(*) AS event_count
            FROM group_events ge
            JOIN endpoints e ON e.id = ge.endpoint_id
            WHERE ge.observed_at >= %s AND ge.observed_at < %s
            GROUP BY e.server_id, date_trunc(%s, ge.observed_at)
        ), buckets AS (
            SELECT server_id, bucket_start FROM snapshot_summary
            UNION
            SELECT server_id, bucket_start FROM event_summary
        )
        INSERT INTO server_group_rollups(
            server_id, resolution, bucket_start, inventory_count, snapshot_count,
            observed_group_count, observed_hierarchy_count, event_count, generated_at
        )
        SELECT
            b.server_id,
            %s,
            b.bucket_start,
            COALESCE(s.inventory_count, 0),
            COALESCE(s.snapshot_count, 0),
            COALESCE(s.observed_group_count, 0),
            COALESCE(s.observed_hierarchy_count, 0),
            COALESCE(ev.event_count, 0),
            CURRENT_TIMESTAMP
        FROM buckets b
        LEFT JOIN snapshot_summary s
          ON s.server_id = b.server_id AND s.bucket_start = b.bucket_start
        LEFT JOIN event_summary ev
          ON ev.server_id = b.server_id AND ev.bucket_start = b.bucket_start
        ORDER BY b.server_id, b.bucket_start
        """,
        (
            resolution,
            start_utc,
            end_utc,
            resolution,
            start_utc,
            end_utc,
            resolution,
            resolution,
        ),
    )

    values = conn.execute(
        """
        WITH values AS (
            SELECT
                e.server_id,
                date_trunc(%s, gs.observed_at) AS bucket_start,
                'posting_status'::text AS kind,
                lower(trim(gs.posting_status)) AS value
            FROM group_snapshots gs
            JOIN endpoints e ON e.id = gs.endpoint_id
            WHERE gs.observed_at >= %s AND gs.observed_at < %s
              AND COALESCE(trim(gs.posting_status), '') <> ''
            UNION ALL
            SELECT
                e.server_id,
                date_trunc(%s, ge.observed_at) AS bucket_start,
                'event_type'::text,
                lower(trim(ge.event_type))
            FROM group_events ge
            JOIN endpoints e ON e.id = ge.endpoint_id
            WHERE ge.observed_at >= %s AND ge.observed_at < %s
              AND COALESCE(trim(ge.event_type), '') <> ''
        )
        INSERT INTO server_group_value_rollups(
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

    conn.commit()
    return GroupRollupResult(
        resolution=resolution,
        start=start_utc,
        end=end_utc,
        summary_rows_written=int(summary.rowcount or 0),
        value_rows_written=int(values.rowcount or 0),
    )


def rebuild_server_group_rollup_chain(
    conn,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[GroupRollupResult, GroupRollupResult, GroupRollupResult]:
    return tuple(
        rebuild_server_group_rollups(
            conn,
            resolution=resolution,
            start=start,
            end=end,
        )
        for resolution in ("hour", "day", "month")
    )
