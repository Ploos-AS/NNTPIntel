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


def _rollup_coverage(conn, *, cutoff: datetime.datetime) -> tuple[bool, tuple[str, ...]]:
    required = {
        "server_observation_rollups": "server availability/latency",
        "server_protocol_rollups": "TLS/capabilities",
        "server_group_rollups": "groups/hierarchies",
        "server_propagation_rollups": "propagation",
        "topology_rollups": "topology/evidence",
    }
    missing: list[str] = []
    for table, label in required.items():
        row = conn.execute(
            f"SELECT MAX(bucket_start) FROM {table} WHERE resolution = 'day'"
        ).fetchone()
        latest = row[0] if row else None
        if latest is None or _utc(latest) < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            missing.append(label)
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
    """Delete old raw rows only after daily rollup coverage passes.

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
