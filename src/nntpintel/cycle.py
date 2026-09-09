# ruff: noqa: I001
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from nntpintel.candidates import qualify_candidates
from nntpintel.discovery import BUILTIN_SOURCES, refresh_builtin_source
from nntpintel.probe import ProbeObservation, probe
from nntpintel.storage import Storage


CYCLE_SQL = """
CREATE TABLE IF NOT EXISTS candidate_cycle_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    added INTEGER NOT NULL DEFAULT 0,
    still_present INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    qualification_count INTEGER NOT NULL DEFAULT 0,
    classifications_json TEXT NOT NULL DEFAULT '{}',
    promotion_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidate_cycle_runs_source_time
ON candidate_cycle_runs(source, started_at DESC);

CREATE TABLE IF NOT EXISTS candidate_cycle_schedule (
    source TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    interval_seconds INTEGER NOT NULL DEFAULT 21600,
    candidate_limit INTEGER NOT NULL DEFAULT 3,
    timeout_seconds REAL NOT NULL DEFAULT 5.0,
    next_cycle_at TEXT,
    last_cycle_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_candidate_cycle_schedule_due
ON candidate_cycle_schedule(enabled, next_cycle_at);
"""

MIN_CYCLE_INTERVAL_SECONDS = 3600
MAX_CYCLE_INTERVAL_SECONDS = 604800
MAX_CYCLE_FAILURE_BACKOFF_SECONDS = 86400


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_cycle_schema(storage: Storage) -> None:
    with storage.connect() as conn:
        conn.executescript(CYCLE_SQL)
        conn.commit()


def list_cycle_runs(
    storage: Storage,
    *,
    source: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_cycle_schema(storage)
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    where = "WHERE source = ?" if source else ""
    params: tuple[Any, ...] = (source, limit) if source else (limit,)
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, source, started_at, finished_at, status,
                   added, still_present, missing, qualification_count,
                   classifications_json, promotion_count, error
            FROM candidate_cycle_runs
            {where}
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["classifications"] = json.loads(item.pop("classifications_json"))
        result.append(item)
    return result


def configure_cycle_schedule(
    storage: Storage,
    source: str,
    *,
    interval_seconds: int = 21600,
    candidate_limit: int = 3,
    timeout_seconds: float = 5.0,
    enabled: bool = True,
    run_now: bool = False,
) -> dict[str, Any]:
    if source not in BUILTIN_SOURCES:
        raise ValueError(f"unknown built-in source: {source}")
    if not MIN_CYCLE_INTERVAL_SECONDS <= interval_seconds <= MAX_CYCLE_INTERVAL_SECONDS:
        raise ValueError(
            f"cycle interval must be between {MIN_CYCLE_INTERVAL_SECONDS} and "
            f"{MAX_CYCLE_INTERVAL_SECONDS} seconds"
        )
    if not 0 <= candidate_limit <= 10:
        raise ValueError("candidate limit must be between 0 and 10")
    if timeout_seconds <= 0 or timeout_seconds > 15:
        raise ValueError("cycle timeout must be greater than 0 and at most 15 seconds")

    ensure_cycle_schema(storage)
    now = datetime.now(UTC)
    next_cycle_at = now if run_now else now + timedelta(seconds=interval_seconds)
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO candidate_cycle_schedule(
                source, enabled, interval_seconds, candidate_limit,
                timeout_seconds, next_cycle_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                enabled = excluded.enabled,
                interval_seconds = excluded.interval_seconds,
                candidate_limit = excluded.candidate_limit,
                timeout_seconds = excluded.timeout_seconds,
                next_cycle_at = excluded.next_cycle_at
            """,
            (
                source,
                int(enabled),
                interval_seconds,
                candidate_limit,
                timeout_seconds,
                next_cycle_at.isoformat(),
            ),
        )
        conn.commit()
    return get_cycle_schedule(storage, source)


def get_cycle_schedule(storage: Storage, source: str) -> dict[str, Any]:
    ensure_cycle_schema(storage)
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT * FROM candidate_cycle_schedule WHERE source = ?",
            (source,),
        ).fetchone()
    if row is None:
        raise ValueError(f"cycle source is not scheduled: {source}")
    return dict(row)


def list_cycle_schedules(storage: Storage) -> list[dict[str, Any]]:
    ensure_cycle_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT source, enabled, interval_seconds, candidate_limit,
                   timeout_seconds, next_cycle_at, last_cycle_at,
                   consecutive_failures
            FROM candidate_cycle_schedule
            ORDER BY source
            """
        ).fetchall()
    return [dict(row) for row in rows]


def due_cycle_schedules(
    storage: Storage,
    *,
    now: datetime | None = None,
    limit: int = 1,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 10:
        raise ValueError("due cycle limit must be between 1 and 10")
    ensure_cycle_schema(storage)
    now = now or datetime.now(UTC)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT source, enabled, interval_seconds, candidate_limit,
                   timeout_seconds, next_cycle_at, last_cycle_at,
                   consecutive_failures
            FROM candidate_cycle_schedule
            WHERE enabled = 1
              AND (next_cycle_at IS NULL OR next_cycle_at <= ?)
            ORDER BY COALESCE(next_cycle_at, '') ASC, source ASC
            LIMIT ?
            """,
            (now.isoformat(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _update_cycle_schedule_after_run(
    storage: Storage,
    source: str,
    *,
    success: bool,
    finished: datetime,
    max_backoff_seconds: int = MAX_CYCLE_FAILURE_BACKOFF_SECONDS,
) -> None:
    schedule = get_cycle_schedule(storage, source)
    previous_failures = int(schedule["consecutive_failures"])
    failures = 0 if success else previous_failures + 1
    interval = int(schedule["interval_seconds"])
    if success:
        delay = interval
    else:
        delay = min(interval * (2 ** min(failures, 8)), max_backoff_seconds)
    next_cycle_at = finished + timedelta(seconds=delay)
    with storage.connect() as conn:
        conn.execute(
            """
            UPDATE candidate_cycle_schedule
            SET last_cycle_at = ?, next_cycle_at = ?, consecutive_failures = ?
            WHERE source = ?
            """,
            (finished.isoformat(), next_cycle_at.isoformat(), failures, source),
        )
        conn.commit()


def run_due_candidate_cycles(
    storage: Storage,
    *,
    limit: int = 1,
    now: datetime | None = None,
    max_backoff_seconds: int = MAX_CYCLE_FAILURE_BACKOFF_SECONDS,
    cycle_func: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    schedules = due_cycle_schedules(storage, now=now, limit=limit)
    runner = cycle_func or run_candidate_cycle
    results: list[dict[str, Any]] = []
    for schedule in schedules:
        source = str(schedule["source"])
        success = False
        try:
            result = runner(
                storage,
                source,
                limit=int(schedule["candidate_limit"]),
                timeout=float(schedule["timeout_seconds"]),
            )
            success = True
            results.append({"source": source, "status": "success", "result": result})
        except Exception as exc:
            results.append(
                {
                    "source": source,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            _update_cycle_schedule_after_run(
                storage,
                source,
                success=success,
                finished=datetime.now(UTC),
                max_backoff_seconds=max_backoff_seconds,
            )
    return results


def run_candidate_cycle(
    storage: Storage,
    source: str,
    *,
    limit: int = 3,
    timeout: float = 5.0,
    content: str | None = None,
    probe_func: Callable[..., ProbeObservation] = probe,
    refresh_func: Callable[..., dict[str, int]] = refresh_builtin_source,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if limit > 10:
        raise ValueError("conservative candidate cycle limit cannot exceed 10")
    if timeout <= 0 or timeout > 15:
        raise ValueError("candidate cycle timeout must be greater than 0 and at most 15 seconds")

    ensure_cycle_schema(storage)
    started_at = _now()
    with storage.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO candidate_cycle_runs(source, started_at, status)
            VALUES (?, ?, 'running')
            """,
            (source, started_at),
        )
        run_id = int(cursor.lastrowid)
        conn.commit()

    try:
        refresh = refresh_func(storage, source, activate=False, content=content)
        qualifications = qualify_candidates(
            storage,
            limit=limit,
            timeout=timeout,
            probe_func=probe_func,
        )
        classifications = dict(
            sorted(Counter(item["classification"] for item in qualifications).items())
        )
        finished_at = _now()
        with storage.connect() as conn:
            conn.execute(
                """
                UPDATE candidate_cycle_runs
                SET finished_at = ?, status = 'success',
                    added = ?, still_present = ?, missing = ?,
                    qualification_count = ?, classifications_json = ?,
                    promotion_count = 0, error = NULL
                WHERE id = ?
                """,
                (
                    finished_at,
                    int(refresh.get("added", 0)),
                    int(refresh.get("still_present", 0)),
                    int(refresh.get("missing", 0)),
                    len(qualifications),
                    json.dumps(classifications, sort_keys=True),
                    run_id,
                ),
            )
            conn.commit()
        return {
            "run_id": run_id,
            "source": source,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": "success",
            "refresh": refresh,
            "qualification_count": len(qualifications),
            "classifications": classifications,
            "qualifications": qualifications,
            "promotion_count": 0,
        }
    except Exception as exc:
        finished_at = _now()
        with storage.connect() as conn:
            conn.execute(
                """
                UPDATE candidate_cycle_runs
                SET finished_at = ?, status = 'failed', error = ?
                WHERE id = ?
                """,
                (finished_at, f"{type(exc).__name__}: {exc}", run_id),
            )
            conn.commit()
        raise
