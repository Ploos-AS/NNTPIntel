from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from nntpintel.probe import ProbeObservation, probe
from nntpintel.storage import Storage


CANDIDATE_SQL = """
CREATE TABLE IF NOT EXISTS candidate_qualifications (
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    classification TEXT NOT NULL,
    detail TEXT,
    UNIQUE(endpoint_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_candidate_qualifications_endpoint_time
ON candidate_qualifications(endpoint_id, observed_at DESC);
"""


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
        conn.executescript(CANDIDATE_SQL)
        conn.commit()


def due_candidates(storage: Storage, *, limit: int = 10) -> list[dict]:
    ensure_candidate_schema(storage)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT e.*, s.host
            FROM endpoints e
            JOIN servers s ON s.id = e.server_id
            WHERE s.enabled = 0
              AND e.enabled = 1
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
