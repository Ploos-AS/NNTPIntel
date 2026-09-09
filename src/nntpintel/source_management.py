from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nntpintel.cycle import ensure_cycle_schema, list_cycle_schedules
from nntpintel.discovery import ensure_discovery_schema, list_sources
from nntpintel.storage import Storage


def set_source_enabled(storage: Storage, source: str, enabled: bool) -> dict[str, Any]:
    ensure_discovery_schema(storage)
    with storage.connect() as conn:
        cursor = conn.execute(
            "UPDATE discovery_sources SET enabled = ? WHERE name = ?",
            (int(enabled), source),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"unknown discovery source: {source}")
    return {"source": source, "enabled": int(enabled)}


def set_cycle_schedule_enabled(
    storage: Storage,
    source: str,
    enabled: bool,
    *,
    run_now: bool = False,
) -> dict[str, Any]:
    ensure_cycle_schema(storage)
    next_cycle_at = datetime.now(UTC).isoformat() if run_now else None
    with storage.connect() as conn:
        if run_now:
            cursor = conn.execute(
                """
                UPDATE candidate_cycle_schedule
                SET enabled = ?, next_cycle_at = ?
                WHERE source = ?
                """,
                (int(enabled), next_cycle_at, source),
            )
        else:
            cursor = conn.execute(
                "UPDATE candidate_cycle_schedule SET enabled = ? WHERE source = ?",
                (int(enabled), source),
            )
        conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"cycle source is not scheduled: {source}")
    return next(item for item in list_cycle_schedules(storage) if item["source"] == source)


def list_source_management(storage: Storage) -> list[dict[str, Any]]:
    sources = list_sources(storage)
    schedules = {item["source"]: item for item in list_cycle_schedules(storage)}
    result: list[dict[str, Any]] = []
    for source in sources:
        schedule = schedules.get(source["name"])
        item = dict(source)
        item["schedule_enabled"] = None if schedule is None else schedule["enabled"]
        item["interval_seconds"] = None if schedule is None else schedule["interval_seconds"]
        item["candidate_limit"] = None if schedule is None else schedule["candidate_limit"]
        item["timeout_seconds"] = None if schedule is None else schedule["timeout_seconds"]
        item["next_cycle_at"] = None if schedule is None else schedule["next_cycle_at"]
        item["last_cycle_at"] = None if schedule is None else schedule["last_cycle_at"]
        item["consecutive_failures"] = None if schedule is None else schedule["consecutive_failures"]
        result.append(item)
    return result
