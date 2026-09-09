from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from nntpintel.probe import ProbeObservation, probe
from nntpintel.storage import SCHEMA_VERSION, Storage

DEFAULT_REQUALIFICATION_AGE_SECONDS = 21600
DEFAULT_PROMOTION_FRESHNESS_SECONDS = 604800


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


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def ensure_candidate_schema(storage: Storage) -> None:
    with storage.connect() as conn:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None or int(row["version"]) != SCHEMA_VERSION:
        raise RuntimeError("candidate schema requires initialized Storage schema")


def due_candidates(
    storage: Storage,
    *,
    limit: int = 10,
    min_age_seconds: int = DEFAULT_REQUALIFICATION_AGE_SECONDS,
    now: datetime | None = None,
) -> list[dict]:
    if limit < 0:
        raise ValueError("candidate limit must be zero or greater")
    if min_age_seconds < 0:
        raise ValueError("minimum qualification age must be zero or greater")
    ensure_candidate_schema(storage)
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(seconds=min_age_seconds)).isoformat()
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
              AND (
                  (SELECT MAX(cq.observed_at)
                   FROM candidate_qualifications cq
                   WHERE cq.endpoint_id = e.id) IS NULL
                  OR
                  (SELECT MAX(cq.observed_at)
                   FROM candidate_qualifications cq
                   WHERE cq.endpoint_id = e.id) <= ?
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
            (cutoff, limit),
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
        return "unreachable", error
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
    min_age_seconds: int = DEFAULT_REQUALIFICATION_AGE_SECONDS,
    probe_func: Callable[..., ProbeObservation] = probe,
) -> list[dict]:
    results = [
        qualify_candidate(storage, endpoint, probe_func=probe_func, timeout=timeout)
        for endpoint in due_candidates(
            storage,
            limit=limit,
            min_age_seconds=min_age_seconds,
        )
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
                   (
                       SELECT COUNT(*)
                       FROM candidate_qualifications cq
                       JOIN endpoints e2 ON e2.id = cq.endpoint_id
                       WHERE e2.server_id = s.id
                   ) AS qualification_count,
                   (
                       SELECT COUNT(*)
                       FROM candidate_qualifications cq
                       JOIN endpoints e2 ON e2.id = cq.endpoint_id
                       WHERE e2.server_id = s.id AND cq.classification = 'reachable'
                   ) AS reachable_count,
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
            LEFT JOIN candidate_decisions cd ON cd.server_id = s.id
            WHERE EXISTS (
                SELECT 1
                FROM server_sources ss
                JOIN discovery_sources ds ON ds.id = ss.source_id
                WHERE ss.server_id = s.id
                  AND ss.active = 1
                  AND ds.enabled = 1
            )
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


def _has_candidate_provenance(storage: Storage, server_id: int, *, active_only: bool) -> bool:
    active_clause = "AND ss.active = 1 AND ds.enabled = 1" if active_only else ""
    with storage.connect() as conn:
        row = conn.execute(
            f"""
            SELECT 1
            FROM server_sources ss
            JOIN discovery_sources ds ON ds.id = ss.source_id
            WHERE ss.server_id = ? {active_clause}
            LIMIT 1
            """,
            (server_id,),
        ).fetchone()
    return row is not None


def set_candidate_status(storage: Storage, host: str, status: str, *, note: str | None = None) -> dict:
    if status not in {"pending", "rejected", "ignored"}:
        raise ValueError(f"invalid candidate status: {status}")
    ensure_candidate_schema(storage)
    server_id = _server_id(storage, host)
    if not _has_candidate_provenance(storage, server_id, active_only=False):
        raise ValueError(f"server is not a discovery candidate: {host}")
    with storage.connect() as conn:
        current = conn.execute(
            "SELECT status FROM candidate_decisions WHERE server_id = ?",
            (server_id,),
        ).fetchone()
        if current is not None and current["status"] == "promoted":
            raise ValueError("promoted candidate cannot be changed with candidate status controls")
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


def promote_candidate(
    storage: Storage,
    host: str,
    *,
    min_reachable: int = 2,
    freshness_seconds: int = DEFAULT_PROMOTION_FRESHNESS_SECONDS,
    now: datetime | None = None,
) -> dict:
    if min_reachable < 1:
        raise ValueError("min_reachable must be at least 1")
    if freshness_seconds <= 0:
        raise ValueError("freshness_seconds must be greater than zero")
    ensure_candidate_schema(storage)
    server_id = _server_id(storage, host)
    if not _has_candidate_provenance(storage, server_id, active_only=True):
        raise ValueError("candidate requires active provenance from an enabled discovery source")
    with storage.connect() as conn:
        decision = conn.execute(
            "SELECT status FROM candidate_decisions WHERE server_id = ?",
            (server_id,),
        ).fetchone()
        status = "pending" if decision is None else str(decision["status"])
        if status != "pending":
            raise ValueError(f"candidate status must be pending before promotion; is {status}")
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
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(seconds=freshness_seconds)
        fresh_rows = [row for row in rows if _as_utc(str(row["observed_at"])) >= cutoff]
        reachable_count = sum(1 for row in fresh_rows if row["classification"] == "reachable")
        latest = fresh_rows[0]["classification"] if fresh_rows else None
        if reachable_count < min_reachable:
            raise ValueError(
                f"candidate needs {min_reachable} recent reachable qualifications; has {reachable_count}"
            )
        if latest != "reachable":
            raise ValueError(f"latest recent qualification must be reachable; is {latest or 'none'}")
        decided_at = current.isoformat()
        conn.execute("UPDATE servers SET enabled = 1 WHERE id = ?", (server_id,))
        conn.execute(
            """
            INSERT INTO candidate_decisions(server_id, status, decided_at, note)
            VALUES (?, 'promoted', ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                status = 'promoted', decided_at = excluded.decided_at, note = excluded.note
            """,
            (
                server_id,
                decided_at,
                f"promotion policy: {reachable_count} recent reachable qualifications",
            ),
        )
        conn.commit()
    return {
        "host": host.lower(),
        "status": "promoted",
        "reachable_count": reachable_count,
        "required_reachable": min_reachable,
        "freshness_seconds": freshness_seconds,
        "decided_at": decided_at,
    }
