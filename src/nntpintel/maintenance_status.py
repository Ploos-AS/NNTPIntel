from __future__ import annotations

import json
from datetime import UTC, datetime


def ensure_maintenance_schema(conn) -> None:
    """Fail closed unless the production maintenance schema was migrated.

    Runtime maintenance operations must never create or alter production schema.
    PostgreSQL migration v9 owns maintenance_runs and its indexes.
    """

    row = conn.execute("SELECT to_regclass('maintenance_runs') AS name").fetchone()
    if row is None or row["name"] is None:
        raise RuntimeError("maintenance schema is missing; run PostgreSQL migrations first")


def start_maintenance_run(conn, *, kind: str, detail: dict | None = None) -> int:
    ensure_maintenance_schema(conn)
    row = conn.execute(
        """
        INSERT INTO maintenance_runs(kind, status, started_at, detail_json)
        VALUES (%s, 'running', %s, %s::jsonb)
        RETURNING id
        """,
        (kind, datetime.now(UTC), json.dumps(detail or {}, sort_keys=True)),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def finish_maintenance_run(
    conn,
    *,
    run_id: int,
    status: str,
    detail: dict | None = None,
) -> None:
    if status not in {"success", "failed", "blocked"}:
        raise ValueError("terminal maintenance status must be success, failed or blocked")
    conn.execute(
        """
        UPDATE maintenance_runs
        SET status = %s, finished_at = %s, detail_json = %s::jsonb
        WHERE id = %s
        """,
        (status, datetime.now(UTC), json.dumps(detail or {}, sort_keys=True), int(run_id)),
    )
    conn.commit()
