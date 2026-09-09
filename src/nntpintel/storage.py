from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from nntpintel.groups import GroupInventory
from nntpintel.probe import ProbeObservation

SCHEMA_VERSION = 5


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

CREATE TABLE IF NOT EXISTS hierarchies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS newsgroups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    hierarchy_id INTEGER NOT NULL REFERENCES hierarchies(id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS group_snapshots (
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    newsgroup_id INTEGER NOT NULL REFERENCES newsgroups(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    high_water INTEGER,
    low_water INTEGER,
    posting_status TEXT,
    description TEXT,
    UNIQUE(endpoint_id, newsgroup_id, observed_at)
);

CREATE TABLE IF NOT EXISTS group_events (
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    newsgroup_id INTEGER NOT NULL REFERENCES newsgroups(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS group_inventory_schedule (
    endpoint_id INTEGER PRIMARY KEY REFERENCES endpoints(id) ON DELETE CASCADE,
    interval_seconds INTEGER NOT NULL DEFAULT 21600,
    next_inventory_at TEXT,
    last_inventory_at TEXT
);

CREATE TABLE IF NOT EXISTS discovery_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    source_ref TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_import_at TEXT
);

CREATE TABLE IF NOT EXISTS server_sources (
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES discovery_sources(id) ON DELETE CASCADE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(server_id, source_id)
);

CREATE TABLE IF NOT EXISTS candidate_qualifications (
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    classification TEXT NOT NULL,
    detail TEXT,
    UNIQUE(endpoint_id, observed_at)
);

CREATE TABLE IF NOT EXISTS candidate_decisions (
    server_id INTEGER PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_at TEXT,
    note TEXT
);

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

CREATE TABLE IF NOT EXISTS propagation_articles (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    newsgroup TEXT,
    article_date TEXT,
    first_registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS propagation_observations (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES propagation_articles(id) ON DELETE CASCADE,
    endpoint_id INTEGER NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    present INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'stat',
    response_code INTEGER,
    error TEXT,
    UNIQUE(article_id, endpoint_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_observations_endpoint_time
ON observations(endpoint_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_endpoints_due
ON endpoints(enabled, next_probe_at);

CREATE INDEX IF NOT EXISTS idx_group_snapshots_group_time
ON group_snapshots(newsgroup_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_group_events_endpoint_time
ON group_events(endpoint_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_group_inventory_due
ON group_inventory_schedule(next_inventory_at);

CREATE INDEX IF NOT EXISTS idx_candidate_qualifications_endpoint_time
ON candidate_qualifications(endpoint_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_candidate_cycle_runs_source_time
ON candidate_cycle_runs(source, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_candidate_cycle_schedule_due
ON candidate_cycle_schedule(enabled, next_cycle_at);

CREATE INDEX IF NOT EXISTS idx_propagation_observations_article_time
ON propagation_observations(article_id, observed_at ASC);

CREATE INDEX IF NOT EXISTS idx_propagation_observations_endpoint_time
ON propagation_observations(endpoint_id, observed_at DESC);
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
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(server_sources)")}
            if "active" not in columns:
                conn.execute("ALTER TABLE server_sources ADD COLUMN active INTEGER NOT NULL DEFAULT 1")

            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] in {1, 2, 3, 4}:
                conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported schema version {row['version']}; expected {SCHEMA_VERSION}"
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO group_inventory_schedule(endpoint_id, next_inventory_at)
                SELECT id, CURRENT_TIMESTAMP FROM endpoints
                """
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
        group_interval_seconds: int = 21600,
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
            endpoint_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO group_inventory_schedule(endpoint_id, interval_seconds, next_inventory_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(endpoint_id) DO NOTHING
                """,
                (endpoint_id, group_interval_seconds),
            )
            conn.commit()
            return endpoint_id

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

    def due_group_endpoints(self, now_iso: str, *, limit: int = 20) -> list[sqlite3.Row]:
        with closing(self.connect()) as conn:
            return list(
                conn.execute(
                    """
                    SELECT e.*, s.host, g.interval_seconds AS group_interval_seconds,
                           g.next_inventory_at, g.last_inventory_at
                    FROM group_inventory_schedule g
                    JOIN endpoints e ON e.id = g.endpoint_id
                    JOIN servers s ON s.id = e.server_id
                    WHERE e.enabled = 1
                      AND s.enabled = 1
                      AND (g.next_inventory_at IS NULL OR g.next_inventory_at <= ?)
                    ORDER BY COALESCE(g.next_inventory_at, '') ASC, e.id ASC
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

    def record_group_inventory(self, endpoint_id: int, inventory: GroupInventory) -> int:
        if inventory.error is not None:
            return 0
        with closing(self.connect()) as conn:
            previous_at_row = conn.execute(
                "SELECT MAX(observed_at) AS observed_at FROM group_snapshots WHERE endpoint_id = ?",
                (endpoint_id,),
            ).fetchone()
            previous_at = previous_at_row["observed_at"] if previous_at_row else None
            previous: dict[str, sqlite3.Row] = {}
            if previous_at is not None:
                rows = conn.execute(
                    """
                    SELECT n.name, g.high_water, g.low_water, g.posting_status, g.description
                    FROM group_snapshots g
                    JOIN newsgroups n ON n.id = g.newsgroup_id
                    WHERE g.endpoint_id = ? AND g.observed_at = ?
                    """,
                    (endpoint_id, previous_at),
                ).fetchall()
                previous = {row["name"]: row for row in rows}

            current_names = {group.name for group in inventory.groups}
            for group in inventory.groups:
                conn.execute(
                    """
                    INSERT INTO hierarchies(name, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET last_seen_at = excluded.last_seen_at
                    """,
                    (group.hierarchy, inventory.observed_at, inventory.observed_at),
                )
                hierarchy_id = conn.execute(
                    "SELECT id FROM hierarchies WHERE name = ?", (group.hierarchy,)
                ).fetchone()["id"]
                conn.execute(
                    """
                    INSERT INTO newsgroups(name, hierarchy_id, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET last_seen_at = excluded.last_seen_at
                    """,
                    (group.name, hierarchy_id, inventory.observed_at, inventory.observed_at),
                )
                newsgroup_id = int(
                    conn.execute(
                        "SELECT id FROM newsgroups WHERE name = ?", (group.name,)
                    ).fetchone()["id"]
                )
                conn.execute(
                    """
                    INSERT INTO group_snapshots(
                        endpoint_id, newsgroup_id, observed_at,
                        high_water, low_water, posting_status, description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        endpoint_id,
                        newsgroup_id,
                        inventory.observed_at,
                        group.high,
                        group.low,
                        group.status,
                        group.description,
                    ),
                )

                old = previous.get(group.name)
                if old is None:
                    event_type = "appeared"
                    detail = {}
                else:
                    before = [
                        old["high_water"], old["low_water"], old["posting_status"], old["description"]
                    ]
                    after = [group.high, group.low, group.status, group.description]
                    event_type = "changed" if before != after else ""
                    detail = {"before": before, "after": after} if event_type else {}
                if event_type:
                    conn.execute(
                        """
                        INSERT INTO group_events(
                            endpoint_id, newsgroup_id, observed_at, event_type, detail_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            endpoint_id,
                            newsgroup_id,
                            inventory.observed_at,
                            event_type,
                            json.dumps(detail, sort_keys=True),
                        ),
                    )

            for name in sorted(set(previous) - current_names):
                newsgroup_id = int(
                    conn.execute(
                        "SELECT id FROM newsgroups WHERE name = ?", (name,)
                    ).fetchone()["id"]
                )
                conn.execute(
                    """
                    INSERT INTO group_events(
                        endpoint_id, newsgroup_id, observed_at, event_type, detail_json
                    ) VALUES (?, ?, ?, 'disappeared', '{}')
                    """,
                    (endpoint_id, newsgroup_id, inventory.observed_at),
                )
            conn.commit()
        return len(inventory.groups)

    def update_group_schedule(
        self,
        endpoint_id: int,
        *,
        last_inventory_at: str,
        next_inventory_at: str,
    ) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                UPDATE group_inventory_schedule
                SET last_inventory_at = ?, next_inventory_at = ?
                WHERE endpoint_id = ?
                """,
                (last_inventory_at, next_inventory_at, endpoint_id),
            )
            conn.commit()

    def group_count(self) -> int:
        with closing(self.connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM newsgroups").fetchone()[0])

    def hierarchy_count(self) -> int:
        with closing(self.connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM hierarchies").fetchone()[0])

    def group_event_count(self) -> int:
        with closing(self.connect()) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM group_events").fetchone()[0])

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