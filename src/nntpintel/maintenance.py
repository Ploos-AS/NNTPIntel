from __future__ import annotations

import dataclasses
import datetime

RAW_TABLES = (
    "observations",
    "group_snapshots",
    "group_events",
    "propagation_observations",
)


@dataclasses.dataclass(frozen=True)
class RetentionPolicy:
    raw_days: int = 90
    safety_lag_hours: int = 48

    def __post_init__(self) -> None:
        if self.raw_days < 1:
            raise ValueError("raw_days must be positive")
        if self.safety_lag_hours < 1:
            raise ValueError("safety_lag_hours must be positive")


@dataclasses.dataclass(frozen=True)
class MaintenancePlan:
    cutoff: datetime.datetime
    safe_cutoff: datetime.datetime
    coverage_complete: bool
    missing_rollups: tuple[str, ...]


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("maintenance timestamps must be timezone-aware")
    return value.astimezone(datetime.UTC)


def retention_cutoff(now: datetime.datetime, policy: RetentionPolicy) -> datetime.datetime:
    return _utc(now) - datetime.timedelta(days=policy.raw_days)


def _has_missing_observation_rollups(conn, *, cutoff: datetime.datetime) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM observations o
        JOIN endpoints e ON e.id = o.endpoint_id
        WHERE o.observed_at < %s
          AND (
            NOT EXISTS (
                SELECT 1 FROM server_observation_rollups r
                WHERE r.server_id = e.server_id
                  AND r.resolution = 'day'
                  AND r.bucket_start = date_trunc('day', o.observed_at)
            )
            OR NOT EXISTS (
                SELECT 1 FROM server_protocol_rollups r
                WHERE r.server_id = e.server_id
                  AND r.resolution = 'day'
                  AND r.bucket_start = date_trunc('day', o.observed_at)
            )
          )
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    return row is not None


def _has_missing_group_rollups(conn, *, cutoff: datetime.datetime) -> bool:
    row = conn.execute(
        """
        WITH raw_group_days AS (
            SELECT DISTINCT e.server_id, date_trunc('day', s.observed_at) AS bucket_start
            FROM group_snapshots s
            JOIN endpoints e ON e.id = s.endpoint_id
            WHERE s.observed_at < %s
            UNION
            SELECT DISTINCT e.server_id, date_trunc('day', g.observed_at) AS bucket_start
            FROM group_events g
            JOIN endpoints e ON e.id = g.endpoint_id
            WHERE g.observed_at < %s
        )
        SELECT 1
        FROM raw_group_days d
        WHERE NOT EXISTS (
            SELECT 1 FROM server_group_rollups r
            WHERE r.server_id = d.server_id
              AND r.resolution = 'day'
              AND r.bucket_start = d.bucket_start
        )
        LIMIT 1
        """,
        (cutoff, cutoff),
    ).fetchone()
    return row is not None


def _has_missing_propagation_rollups(conn, *, cutoff: datetime.datetime) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM propagation_observations p
        JOIN endpoints e ON e.id = p.endpoint_id
        WHERE p.observed_at < %s
          AND NOT EXISTS (
            SELECT 1 FROM server_propagation_rollups r
            WHERE r.server_id = e.server_id
              AND r.resolution = 'day'
              AND r.bucket_start = date_trunc('day', p.observed_at)
          )
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    return row is not None


def _rollup_coverage(conn, *, cutoff: datetime.datetime) -> tuple[bool, tuple[str, ...]]:
    """Require daily rollups for every raw server/day eligible for retention.

    Coverage is intentionally domain-specific. Topology rollups are not a
    prerequisite because none of the raw tables pruned here are topology data.
    """

    missing: list[str] = []
    if _has_missing_observation_rollups(conn, cutoff=cutoff):
        missing.append("server availability/latency + TLS/capabilities")
    if _has_missing_group_rollups(conn, cutoff=cutoff):
        missing.append("groups/hierarchies")
    if _has_missing_propagation_rollups(conn, cutoff=cutoff):
        missing.append("propagation")
    return not missing, tuple(missing)


def plan_retention(
    conn,
    *,
    now: datetime.datetime,
    policy: RetentionPolicy,
) -> MaintenancePlan:
    cutoff = retention_cutoff(now, policy)
    safe_cutoff = cutoff - datetime.timedelta(hours=policy.safety_lag_hours)
    complete, missing = _rollup_coverage(conn, cutoff=safe_cutoff)
    return MaintenancePlan(cutoff, safe_cutoff, complete, missing)


def prune_raw_batches(
    conn,
    *,
    now: datetime.datetime,
    policy: RetentionPolicy,
    batch_size: int = 10_000,
) -> dict[str, int]:
    """Delete old raw rows only after per-domain daily rollup coverage passes.

    Deletion is deliberately bounded and excludes derived rollups, topology
    evidence snapshots, incidents, campaigns and normalized entity tables.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    plan = plan_retention(conn, now=now, policy=policy)
    if not plan.coverage_complete:
        raise RuntimeError("retention blocked: missing rollup coverage: " + ", ".join(plan.missing_rollups))

    deleted: dict[str, int] = {}
    for table in RAW_TABLES:
        result = conn.execute(
            f"""
            DELETE FROM {table}
            WHERE ctid IN (
                SELECT ctid FROM {table}
                WHERE observed_at < %s
                ORDER BY observed_at
                LIMIT %s
            )
            """,
            (plan.safe_cutoff, batch_size),
        )
        deleted[table] = int(result.rowcount or 0)
    conn.commit()
    return deleted
