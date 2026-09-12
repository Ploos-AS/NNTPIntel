from __future__ import annotations

import dataclasses
import datetime

from nntpintel.partition_lifecycle import PARTITIONED_TABLES, monthly_partition_name

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


@dataclasses.dataclass(frozen=True)
class PartitionRetirementCandidate:
    table: str
    partition: str
    month: datetime.datetime
    month_end: datetime.datetime
    coverage_complete: bool
    missing_rollups: tuple[str, ...]


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("maintenance timestamps must be timezone-aware")
    return value.astimezone(datetime.UTC)


def _month_start(value: datetime.datetime) -> datetime.datetime:
    value = _utc(value)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime.datetime) -> datetime.datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def retention_cutoff(now: datetime.datetime, policy: RetentionPolicy) -> datetime.datetime:
    return _utc(now) - datetime.timedelta(days=policy.raw_days)


def _has_missing_observation_rollups(
    conn,
    *,
    cutoff: datetime.datetime | None = None,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
) -> bool:
    if cutoff is not None:
        predicate = "o.observed_at < %s"
        params = (cutoff,)
    elif start is not None and end is not None:
        predicate = "o.observed_at >= %s AND o.observed_at < %s"
        params = (start, end)
    else:
        raise ValueError("cutoff or start/end required")
    row = conn.execute(
        f"""
        SELECT 1
        FROM observations o
        JOIN endpoints e ON e.id = o.endpoint_id
        WHERE {predicate}
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
        params,
    ).fetchone()
    return row is not None


def _has_missing_group_rollups(
    conn,
    *,
    cutoff: datetime.datetime | None = None,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    table: str | None = None,
) -> bool:
    if table not in (None, "group_snapshots", "group_events"):
        raise ValueError(f"unsupported group table: {table}")

    parts: list[str] = []
    params: list[datetime.datetime] = []
    sources = (table,) if table else ("group_snapshots", "group_events")
    aliases = {"group_snapshots": "s", "group_events": "g"}
    for source in sources:
        alias = aliases[source]
        if cutoff is not None:
            predicate = f"{alias}.observed_at < %s"
            params.append(cutoff)
        elif start is not None and end is not None:
            predicate = f"{alias}.observed_at >= %s AND {alias}.observed_at < %s"
            params.extend((start, end))
        else:
            raise ValueError("cutoff or start/end required")
        parts.append(
            f"""SELECT DISTINCT e.server_id, date_trunc('day', {alias}.observed_at) AS bucket_start
                FROM {source} {alias}
                JOIN endpoints e ON e.id = {alias}.endpoint_id
                WHERE {predicate}"""
        )

    raw_days = " UNION ".join(parts)
    row = conn.execute(
        f"""
        WITH raw_group_days AS (
            {raw_days}
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
        tuple(params),
    ).fetchone()
    return row is not None


def _has_missing_propagation_rollups(
    conn,
    *,
    cutoff: datetime.datetime | None = None,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
) -> bool:
    if cutoff is not None:
        predicate = "p.observed_at < %s"
        params = (cutoff,)
    elif start is not None and end is not None:
        predicate = "p.observed_at >= %s AND p.observed_at < %s"
        params = (start, end)
    else:
        raise ValueError("cutoff or start/end required")
    row = conn.execute(
        f"""
        SELECT 1
        FROM propagation_observations p
        JOIN endpoints e ON e.id = p.endpoint_id
        WHERE {predicate}
          AND NOT EXISTS (
            SELECT 1 FROM server_propagation_rollups r
            WHERE r.server_id = e.server_id
              AND r.resolution = 'day'
              AND r.bucket_start = date_trunc('day', p.observed_at)
          )
        LIMIT 1
        """,
        params,
    ).fetchone()
    return row is not None


def _rollup_coverage(conn, *, cutoff: datetime.datetime) -> tuple[bool, tuple[str, ...]]:
    """Require daily rollups for every raw server/day eligible for row retention."""

    missing: list[str] = []
    if _has_missing_observation_rollups(conn, cutoff=cutoff):
        missing.append("server availability/latency + TLS/capabilities")
    if _has_missing_group_rollups(conn, cutoff=cutoff):
        missing.append("groups/hierarchies")
    if _has_missing_propagation_rollups(conn, cutoff=cutoff):
        missing.append("propagation")
    return not missing, tuple(missing)


def partition_rollup_coverage(
    conn,
    *,
    table: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[bool, tuple[str, ...]]:
    """Check rollup coverage only for raw rows inside one partition range."""

    if table not in RAW_TABLES or table not in PARTITIONED_TABLES:
        raise ValueError(f"unsupported retention table: {table}")
    start = _utc(start)
    end = _utc(end)
    if end <= start:
        raise ValueError("partition coverage end must be after start")

    missing: list[str] = []
    if table == "observations" and _has_missing_observation_rollups(conn, start=start, end=end):
        missing.append("server availability/latency + TLS/capabilities")
    elif table in ("group_snapshots", "group_events") and _has_missing_group_rollups(
        conn, start=start, end=end, table=table
    ):
        missing.append("groups/hierarchies")
    elif table == "propagation_observations" and _has_missing_propagation_rollups(
        conn, start=start, end=end
    ):
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


def list_partition_retirement_candidates(
    conn,
    *,
    now: datetime.datetime,
    policy: RetentionPolicy,
) -> tuple[PartitionRetirementCandidate, ...]:
    """List attached monthly partitions whose full month is old enough to retire."""

    plan = plan_retention(conn, now=now, policy=policy)
    rows = conn.execute(
        """
        SELECT parent.relname AS parent_name, child.relname AS partition_name,
               pg_get_expr(child.relpartbound, child.oid) AS partition_bound
        FROM pg_inherits i
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_class child ON child.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = child.relnamespace
        WHERE n.nspname = current_schema()
          AND parent.relname = ANY(%s)
        ORDER BY parent.relname, child.relname
        """,
        (list(PARTITIONED_TABLES),),
    ).fetchall()

    candidates: list[PartitionRetirementCandidate] = []
    for row in rows:
        table = row["parent_name"]
        name = row["partition_name"]
        if row["partition_bound"] == "DEFAULT" or name == f"{table}_default":
            continue
        prefix = f"{table}_"
        suffix = name.removeprefix(prefix)
        try:
            month = datetime.datetime.strptime(suffix, "%Y_%m").replace(tzinfo=datetime.UTC)
        except ValueError:
            continue
        if monthly_partition_name(table, month) != name:
            continue
        month_end = _next_month(month)
        if month_end > plan.safe_cutoff:
            continue
        complete, missing = partition_rollup_coverage(conn, table=table, start=month, end=month_end)
        candidates.append(
            PartitionRetirementCandidate(table, name, month, month_end, complete, missing)
        )
    return tuple(candidates)


def prune_raw_batches(
    conn,
    *,
    now: datetime.datetime,
    policy: RetentionPolicy,
    batch_size: int = 10_000,
) -> dict[str, int]:
    """Delete old raw rows only after global per-domain daily rollup coverage passes.

    This is a conservative fallback for data in DEFAULT partitions or legacy
    layouts. Monthly partition retirement is the preferred production path.
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


def retire_monthly_partition(
    conn,
    *,
    table: str,
    month: datetime.datetime,
    now: datetime.datetime,
    policy: RetentionPolicy,
) -> str:
    """Drop one old monthly raw partition after exact range coverage checks."""

    if table not in RAW_TABLES or table not in PARTITIONED_TABLES:
        raise ValueError(f"unsupported retention table: {table}")

    start = _month_start(month)
    end = _next_month(start)
    plan = plan_retention(conn, now=now, policy=policy)
    if end > plan.safe_cutoff:
        raise RuntimeError(
            f"retention blocked: partition month ends at {end.isoformat()}, "
            f"after safe cutoff {plan.safe_cutoff.isoformat()}"
        )

    complete, missing = partition_rollup_coverage(conn, table=table, start=start, end=end)
    if not complete:
        raise RuntimeError("retention blocked: missing rollup coverage: " + ", ".join(missing))

    name = monthly_partition_name(table, start)
    default_name = f"{table}_default"
    if name == default_name:
        raise RuntimeError("retention blocked: DEFAULT partition can never be retired")

    row = conn.execute(
        """
        SELECT pg_get_expr(child.relpartbound, child.oid) AS partition_bound
        FROM pg_inherits i
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_class child ON child.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = child.relnamespace
        WHERE n.nspname = current_schema()
          AND parent.relname = %s
          AND child.relname = %s
        """,
        (table, name),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"retention blocked: {name} is not an attached partition of {table}")
    if row["partition_bound"] == "DEFAULT":
        raise RuntimeError("retention blocked: DEFAULT partition can never be retired")

    conn.execute(f"DROP TABLE {name}")
    conn.commit()
    return name


def retire_eligible_partitions(
    conn,
    *,
    now: datetime.datetime,
    policy: RetentionPolicy,
    limit: int | None = None,
) -> tuple[str, ...]:
    """Retire all currently eligible partitions with complete exact coverage."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    candidates = [
        candidate
        for candidate in list_partition_retirement_candidates(conn, now=now, policy=policy)
        if candidate.coverage_complete
    ]
    if limit is not None:
        candidates = candidates[:limit]

    retired: list[str] = []
    for candidate in candidates:
        retired.append(
            retire_monthly_partition(
                conn,
                table=candidate.table,
                month=candidate.month,
                now=now,
                policy=policy,
            )
        )
    return tuple(retired)
