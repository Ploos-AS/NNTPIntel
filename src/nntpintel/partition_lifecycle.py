from __future__ import annotations

import datetime

PARTITIONED_TABLES = (
    "observations",
    "group_snapshots",
    "group_events",
    "propagation_observations",
)


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        raise ValueError("partition timestamps must be timezone-aware")
    return value.astimezone(datetime.UTC)


def _month_start(value: datetime.datetime) -> datetime.datetime:
    value = _utc(value)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime.datetime) -> datetime.datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def monthly_partition_name(table: str, month: datetime.datetime) -> str:
    if table not in PARTITIONED_TABLES:
        raise ValueError(f"unsupported partitioned table: {table}")
    month = _month_start(month)
    return f"{table}_{month:%Y_%m}"


def ensure_monthly_partition(conn, *, table: str, month: datetime.datetime) -> str:
    """Create one monthly partition only when its DEFAULT range is empty.

    PostgreSQL cannot safely attach a new range partition when the DEFAULT
    partition already contains rows in that range. NNTPIntel therefore refuses
    the operation instead of moving rows implicitly during maintenance.
    """

    if table not in PARTITIONED_TABLES:
        raise ValueError(f"unsupported partitioned table: {table}")
    start = _month_start(month)
    end = _next_month(start)
    name = monthly_partition_name(table, start)
    default_table = f"{table}_default"

    exists = conn.execute("SELECT to_regclass(%s) AS name", (name,)).fetchone()["name"]
    if exists:
        return name

    count = conn.execute(
        f"SELECT COUNT(*) AS count FROM {default_table} WHERE observed_at >= %s AND observed_at < %s",
        (start, end),
    ).fetchone()["count"]
    if int(count) != 0:
        raise RuntimeError(
            f"cannot create {name}: {default_table} contains {count} row(s) in target range"
        )

    conn.execute(
        f"CREATE TABLE {name} PARTITION OF {table} FOR VALUES FROM (%s) TO (%s)",
        (start, end),
    )
    conn.commit()
    return name


def ensure_partition_window(
    conn,
    *,
    now: datetime.datetime,
    months_ahead: int = 2,
) -> tuple[str, ...]:
    if months_ahead < 0:
        raise ValueError("months_ahead must be non-negative")
    month = _month_start(now)
    created: list[str] = []
    for _ in range(months_ahead + 1):
        for table in PARTITIONED_TABLES:
            created.append(ensure_monthly_partition(conn, table=table, month=month))
        month = _next_month(month)
    return tuple(created)
