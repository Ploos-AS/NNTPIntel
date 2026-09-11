from __future__ import annotations

import dataclasses
import datetime

from nntpintel.rollups import _bucket_delete_bounds, _utc

_ALLOWED_RESOLUTIONS = {"hour", "day", "month"}


@dataclasses.dataclass(frozen=True)
class TopologyRollupResult:
    resolution: str
    start: datetime.datetime
    end: datetime.datetime
    summary_rows_written: int
    value_rows_written: int


def rebuild_topology_rollups(
    conn,
    *,
    resolution: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> TopologyRollupResult:
    """Rebuild persisted topology evidence and topology-incident rollups.

    Snapshot rows are fingerprint-deduplicated state changes, not periodic samples.
    Rollups therefore describe captured evidence-state changes, not authoritative
    real-world topology changes.
    """

    if resolution not in _ALLOWED_RESOLUTIONS:
        raise ValueError("resolution must be 'hour', 'day' or 'month'")
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("rollup end must be after start")

    delete_start, delete_end = _bucket_delete_bounds(start_utc, end_utc, resolution)
    for table in ("topology_value_rollups", "topology_rollups"):
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
                date_trunc(%s, captured_at) AS bucket_start,
                conclusion_ref
            FROM topology_evidence_snapshots
            WHERE captured_at >= %s AND captured_at < %s
        ), snapshot_summary AS (
            SELECT bucket_start,
                   COUNT(*) AS snapshot_count,
                   COUNT(DISTINCT conclusion_ref) AS conclusion_count
            FROM snapshot_scoped
            GROUP BY bucket_start
        ), incident_scoped AS (
            SELECT date_trunc(%s, started_at) AS bucket_start
            FROM propagation_incidents
            WHERE started_at >= %s AND started_at < %s
              AND substring(kind FROM 1 FOR 9) = 'topology_'
        ), incident_summary AS (
            SELECT bucket_start, COUNT(*) AS incident_started_count
            FROM incident_scoped
            GROUP BY bucket_start
        ), buckets AS (
            SELECT bucket_start FROM snapshot_summary
            UNION
            SELECT bucket_start FROM incident_summary
        )
        INSERT INTO topology_rollups(
            resolution, bucket_start, snapshot_count, conclusion_count,
            incident_started_count, generated_at
        )
        SELECT
            %s,
            b.bucket_start,
            COALESCE(s.snapshot_count, 0),
            COALESCE(s.conclusion_count, 0),
            COALESCE(i.incident_started_count, 0),
            CURRENT_TIMESTAMP
        FROM buckets b
        LEFT JOIN snapshot_summary s USING (bucket_start)
        LEFT JOIN incident_summary i USING (bucket_start)
        ORDER BY b.bucket_start
        """,
        (
            resolution,
            start_utc,
            end_utc,
            resolution,
            start_utc,
            end_utc,
            resolution,
        ),
    )

    values = conn.execute(
        """
        WITH values AS (
            SELECT date_trunc(%s, captured_at) AS bucket_start,
                   'conclusion_type'::text AS kind,
                   lower(trim(conclusion_type)) AS value
            FROM topology_evidence_snapshots
            WHERE captured_at >= %s AND captured_at < %s
              AND trim(conclusion_type) <> ''
            UNION ALL
            SELECT date_trunc(%s, captured_at),
                   'evidence_level'::text,
                   lower(trim(bundle_json #>> '{quality,evidence_level}'))
            FROM topology_evidence_snapshots
            WHERE captured_at >= %s AND captured_at < %s
              AND COALESCE(trim(bundle_json #>> '{quality,evidence_level}'), '') <> ''
            UNION ALL
            SELECT date_trunc(%s, captured_at),
                   'risk_level'::text,
                   lower(trim(COALESCE(
                       bundle_json #>> '{analysis,risk,risk_level}',
                       bundle_json #>> '{analysis,community,risk_level}'
                   )))
            FROM topology_evidence_snapshots
            WHERE captured_at >= %s AND captured_at < %s
              AND COALESCE(trim(COALESCE(
                  bundle_json #>> '{analysis,risk,risk_level}',
                  bundle_json #>> '{analysis,community,risk_level}'
              )), '') <> ''
            UNION ALL
            SELECT date_trunc(%s, started_at),
                   'incident_kind'::text,
                   lower(trim(kind))
            FROM propagation_incidents
            WHERE started_at >= %s AND started_at < %s
              AND substring(kind FROM 1 FOR 9) = 'topology_'
            UNION ALL
            SELECT date_trunc(%s, started_at),
                   'incident_severity'::text,
                   lower(trim(severity))
            FROM propagation_incidents
            WHERE started_at >= %s AND started_at < %s
              AND substring(kind FROM 1 FOR 9) = 'topology_'
        )
        INSERT INTO topology_value_rollups(
            resolution, bucket_start, kind, value, occurrence_count, generated_at
        )
        SELECT %s, bucket_start, kind, value, COUNT(*), CURRENT_TIMESTAMP
        FROM values
        GROUP BY bucket_start, kind, value
        ORDER BY bucket_start, kind, value
        """,
        (
            resolution,
            start_utc,
            end_utc,
            resolution,
            start_utc,
            end_utc,
            resolution,
            start_utc,
            end_utc,
            resolution,
            start_utc,
            end_utc,
            resolution,
            start_utc,
            end_utc,
            resolution,
        ),
    )

    conn.commit()
    return TopologyRollupResult(
        resolution=resolution,
        start=start_utc,
        end=end_utc,
        summary_rows_written=int(summary.rowcount or 0),
        value_rows_written=int(values.rowcount or 0),
    )


def rebuild_topology_rollup_chain(
    conn,
    *,
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[TopologyRollupResult, TopologyRollupResult, TopologyRollupResult]:
    return tuple(
        rebuild_topology_rollups(conn, resolution=resolution, start=start, end=end)
        for resolution in ("hour", "day", "month")
    )
