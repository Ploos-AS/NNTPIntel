# ruff: noqa: I001
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from nntpintel.candidates import qualify_candidates
from nntpintel.discovery import refresh_builtin_source
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
"""


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
