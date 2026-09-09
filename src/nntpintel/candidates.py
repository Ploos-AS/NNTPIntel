from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from nntpintel.probe import ProbeObservation, probe
from nntpintel.storage import SCHEMA_VERSION, Storage


@dataclass(frozen=True)
class QualificationResult:
    endpoint_id: int
    host: str
    port: int
    classification: str
    observed_at: str
    detail: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_candidate_schema(storage: Storage) -> None:
    with storage.connect() as conn:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None or int(row["version"]) != SCHEMA_VERSION:
        raise RuntimeError("candidate schema requires initialized Storage schema")


def due_candidates(storage: Storage, *, limit: int = 10) -> list[dict]:
    ensure_candidate_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT e.*, s.host
            FROM endpoints e
            JOIN servers s ON s.id = e.server_id
            LEFT JOIN candidate_decisions cd ON cd.server_id = s.id
            WHERE s.enabled = 0
              AND e.enabled = 1
              AND COALESCE(cd.status, 'pending') = 'pending'
              AND EXISTS (
                  SELECT 1
                  FROM server_sources ss
                  JOIN discovery_sources ds ON ds.id = ss.source_id
                  WHERE ss.server_id = s.id
                    AND ss.active = 1
                    AND ds.enabled = 1
              )
            ORDER BY (
                SELECT MAX(cq.observed_at)
                FROM candidate_qualifications cq
                WHERE cq.endpoint_id = e.id
            ) IS NOT NULL ASC,
            (
                SELECT MAX(cq.observed_at)
                FROM candidate_qualifications cq
                WHERE cq.endpoint_id = e.id
            ) ASC,
            e.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def classify_observation(observation: ProbeObservation) -> tuple[str, str | None]:
    if observation.error is None and observation.greeting_code in {200, 201}:
        return "reachable", observation.greeting
    if observation.greeting_code in {480, 481, 482, 502}:
        return "auth_required", observation.greeting
    error = observation.error or ""
    if "SSLError" in error or "certificate" in error.lower():
        return "tls_error", error
    if "NNTPProtocolError" in error and observation.greeting_code is None:
        return "not_nntp", error
    if any(name in error for name in ("TimeoutError", "ConnectionRefusedError", "gaierror", "OSError")):
        return "dead", error
    if observation.greeting_code is not None:
        return "nntp_rejected", observation.greeting or error
    return "unknown", error or None


def qualify_candidate(
    storage: Storage,
    endpoint: dict,
    *,
    probe_func: Callable[..., ProbeObservation] = probe,
    timeout: float = 5.0,
) -> QualificationResult:
    ensure_candidate_schema(storage)
    observation = probe_func(
        endpoint["host"],
        port=int(endpoint["port"]),
        implicit_tls=endpoint["transport"] == "tls",
        starttls=bool(endpoint["starttls"]),
        timeout=timeout,
    )
    classification, detail = classify_observation(observation)
    observed_at = observation.observed_at or _now()
    result = QualificationResult(
        endpoint_id=int(endpoint["id"]),
        host=str(endpoint["host"]),
        port=int(endpoint["port"]),
        classification=classification,
        observed_at=observed_at,
        detail=detail,
    )
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO candidate_qualifications(
                endpoint_id, observed_at, classification, detail
            ) VALUES (?, ?, ?, ?)
            """,
            (result.endpoint_id, result.observed_at, result.classification, result.detail),
        )
        conn.commit()
    return result


def qualify_candidates(
    storage: Storage,
    *,
    limit: int = 5,
    timeout: float = 5.0,
    probe_func: Callable[..., ProbeObservation] = probe,
) -> list[dict]:
    results = [
        qualify_candidate(storage, endpoint, probe_func=probe_func, timeout=timeout)
        for endpoint in due_candidates(storage, limit=limit)
    ]
    return [asdict(result) for result in results]


def list_candidate_qualifications(storage: Storage, *, limit: int = 100) -> list[dict]:
    ensure_candidate_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT cq.id, cq.endpoint_id, s.host, e.port, e.transport, e.starttls,
                   cq.observed_at, cq.classification, cq.detail
            FROM candidate_qualifications cq
            JOIN endpoints e ON e.id = cq.endpoint_id
            JOIN servers s ON s.id = e.server_id
            ORDER BY cq.observed_at DESC, cq.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_candidates(storage: Storage) -> list[dict]:
    ensure_candidate_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id AS server_id, s.host, s.enabled,
                   COALESCE(cd.status, CASE WHEN s.enabled = 1 THEN 'promoted' ELSE 'pending' END) AS status,
                   cd.decided_at, cd.note,
                   COUNT(cq.id) AS qualification_count,
                   COALESCE(SUM(CASE WHEN cq.classification = 'reachable' THEN 1 ELSE 0 END), 0) AS reachable_count,
                   (
                       SELECT cq2.classification
                       FROM candidate_qualifications cq2
                       JOIN endpoints e2 ON e2.id = cq2.endpoint_id
                       WHERE e2.server_id = s.id
                       ORDER BY cq2.observed_at DESC, cq2.id DESC
                       LIMIT 1
                   ) AS latest_classification,
                   (
                       SELECT cq2.observed_at
                       FROM candidate_qualifications cq2
                       JOIN endpoints e2 ON e2.id = cq2.endpoint_id
                       WHERE e2.server_id = s.id
                       ORDER BY cq2.observed_at DESC, cq2.id DESC
                       LIMIT 1
                   ) AS latest_qualified_at
            FROM servers s
            JOIN endpoints e ON e.server_id = s.id
            JOIN server_sources ss ON ss.server_id = s.id AND ss.active = 1
            LEFT JOIN candidate_decisions cd ON cd.server_id = s.id
            LEFT JOIN candidate_qualifications cq ON cq.endpoint_id = e.id
            GROUP BY s.id
            ORDER BY s.host
            """
        ).fetchall()
        return [dict(row) for row in rows]


def _server_id(storage: Storage, host: str) -> int:
    with storage.connect() as conn:
        row = conn.execute("SELECT id FROM servers WHERE lower(host) = lower(?)", (host.strip(),)).fetchone()
    if row is None:
        raise ValueError(f"unknown candidate: {host}")
    return int(row["id"])


def set_candidate_status(storage: Storage, host: str, status: str, *, note: str | None = None) -> dict:
    if status not in {"pending", "rejected", "ignored"}:
        raise ValueError(f"invalid candidate status: {status}")
    ensure_candidate_schema(storage)
    server_id = _server_id(storage, host)
    decided_at = None if status == "pending" else _now()
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO candidate_decisions(server_id, status, decided_at, note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                status = excluded.status,
                decided_at = excluded.decided_at,
                note = excluded.note
            """,
            (server_id, status, decided_at, note),
        )
        if status != "pending":
            conn.execute("UPDATE servers SET enabled = 0 WHERE id = ?", (server_id,))
        conn.commit()
    return {"host": host.lower(), "status": status, "decided_at": decided_at, "note": note}


def promote_candidate(storage: Storage, host: str, *, min_reachable: int = 2) -> dict:
    if min_reachable < 1:
        raise ValueError("min_reachable must be at least 1")
    ensure_candidate_schema(storage)
    server_id = _server_id(storage, host)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT cq.classification, cq.observed_at
            FROM candidate_qualifications cq
            JOIN endpoints e ON e.id = cq.endpoint_id
            WHERE e.server_id = ?
            ORDER BY cq.observed_at DESC, cq.id DESC
            """,
            (server_id,),
        ).fetchall()
        reachable_count = sum(1 for row in rows if row["classification"] == "reachable")
        latest = rows[0]["classification"] if rows else None
        if reachable_count < min_reachable:
            raise ValueError(
                f"candidate needs {min_reachable} reachable qualifications; has {reachable_count}"
            )
        if latest != "reachable":
            raise ValueError(f"latest qualification must be reachable; is {latest or 'none'}")
        now = _now()
        conn.execute("UPDATE servers SET enabled = 1 WHERE id = ?", (server_id,))
        conn.execute(
            """
            INSERT INTO candidate_decisions(server_id, status, decided_at, note)
            VALUES (?, 'promoted', ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                status = 'promoted', decided_at = excluded.decided_at, note = excluded.note
            """,
            (server_id, now, f"promotion policy: {reachable_count} reachable qualifications"),
        )
        conn.commit()
    return {
        "host": host.lower(),
        "status": "promoted",
        "reachable_count": reachable_count,
        "required_reachable": min_reachable,
        "decided_at": now,
    }
