from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

from nntpintel.probe import ProbeObservation

SCHEMA_VERSION = 1


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS servers (
    id INTEGER PRIMARY KEY,
    host TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS endpoints (
    id INTEGER PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    port INTEGER NOT NULL,
    transport TEXT NOT NULL,
    starttls INTEGER NOT NULL DEFAULT 0,
    interval_seconds INTEGER NOT NULL DEFAULT 900,
    timeout_seconds REAL NOT NULL DEFAULT 10.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    next_probe_at TEXT,
    last_probe_at TEXT,
    UNIQUE(server_id, port, transport, starttls)
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    connect_ms REAL,
    greeting_code INTEGER,
    greeting TEXT,
    posting_allowed INTEGER,
    mode_reader_code INTEGER,
    mode_reader_response TEXT,
    capabilities_json TEXT NOT NULL,
    tls_json TEXT NOT NULL,
    error TEXT,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_observations_endpoint_time
ON observations(endpoint_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_endpoints_due
ON endpoints(enabled, next_probe_at);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA_SQL)
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported schema version {row['version']}; expected {SCHEMA_VERSION}"
                )
            conn.commit()

    def ensure_endpoint(
        self,
        host: str,
        *,
        port: int = 119,
        transport: str = "tcp",
        starttls: bool = False,
        interval_seconds: int = 900,
        timeout_seconds: float = 10.0,
    ) -> int:
        with closing(self.connect()) as conn:
            conn.execute("INSERT OR IGNORE INTO servers(host) VALUES (?)", (host,))
            server_id = conn.execute(
                "SELECT id FROM servers WHERE host = ?", (host,)
            ).fetchone()["id"]
            conn.execute(
                """
                INSERT OR IGNORE INTO endpoints(
                    server_id, port, transport, starttls,
                    interval_seconds, timeout_seconds, next_probe_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    server_id,
                    port,
                    transport,
                    int(starttls),
                    interval_seconds,
                    timeout_seconds,
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM endpoints
                WHERE server_id = ? AND port = ? AND transport = ? AND starttls = ?
                """,
                (server_id, port, transport, int(starttls)),
            ).fetchone()
            conn.commit()
            return int(row["id"])

    def due_endpoints(self, now_iso: str, *, limit: int = 100) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return list(
                conn.execute(
                    """
                    SELECT e.*, s.host
                    FROM endpoints e
                    JOIN servers s ON s.id = e.server_id
                    WHERE e.enabled = 1
                      AND s.enabled = 1
                      AND (e.next_probe_at IS NULL OR e.next_probe_at <= ?)
                    ORDER BY COALESCE(e.next_probe_at, '') ASC, e.id ASC
                    LIMIT ?
                    """,
                    (now_iso, limit),
                ).fetchall()
            )

    def record_observation(self, endpoint_id: int, observation: ProbeObservation) -> None:
        payload = observation.to_dict()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO observations(
                    endpoint_id, observed_at, success, connect_ms,
                    greeting_code, greeting, posting_allowed,
                    mode_reader_code, mode_reader_response,
                    capabilities_json, tls_json, error, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    endpoint_id,
                    observation.observed_at,
                    int(observation.error is None),
                    observation.connect_ms,
                    observation.greeting_code,
                    observation.greeting,
                    None if observation.posting_allowed is None else int(observation.posting_allowed),
                    observation.mode_reader_code,
                    observation.mode_reader_response,
                    json.dumps(observation.capabilities, sort_keys=True),
                    json.dumps(payload["tls"], sort_keys=True),
                    observation.error,
                    json.dumps(payload, sort_keys=True),
                ),
            )
            conn.commit()

    def update_schedule(
        self,
        endpoint_id: int,
        *,
        last_probe_at: str,
        next_probe_at: str,
        consecutive_failures: int,
    ) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE endpoints
                SET last_probe_at = ?, next_probe_at = ?, consecutive_failures = ?
                WHERE id = ?
                """,
                (last_probe_at, next_probe_at, consecutive_failures, endpoint_id),
            )
            conn.commit()

    def observation_count(self) -> int:
        with closing(self.connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def list_endpoints(self) -> Iterable[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return list(
                conn.execute(
                    """
                    SELECT e.*, s.host
                    FROM endpoints e
                    JOIN servers s ON s.id = e.server_id
                    ORDER BY s.host, e.port
                    """
                ).fetchall()
            )
