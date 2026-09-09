import sqlite3

from nntpintel.storage import SCHEMA_VERSION, Storage


V4_TABLES = {
    "discovery_sources",
    "server_sources",
    "candidate_qualifications",
    "candidate_decisions",
    "candidate_cycle_runs",
    "candidate_cycle_schedule",
}


def test_fresh_storage_creates_consolidated_v4_schema(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    with storage.connect() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert version == SCHEMA_VERSION == 4
    assert V4_TABLES <= tables


def test_v3_upgrade_preserves_legacy_discovery_rows_and_adds_active(tmp_path):
    path = tmp_path / "nntpintel.db"
    storage = Storage(path)
    with storage.connect() as conn:
        conn.execute("INSERT INTO servers(host, enabled) VALUES ('legacy.example', 0)")
        server_id = conn.execute("SELECT id FROM servers WHERE host = 'legacy.example'").fetchone()["id"]
        conn.execute(
            "INSERT INTO discovery_sources(name, source_ref) VALUES ('legacy-source', 'legacy://source')"
        )
        source_id = conn.execute(
            "SELECT id FROM discovery_sources WHERE name = 'legacy-source'"
        ).fetchone()["id"]
        conn.execute("DROP TABLE server_sources")
        conn.execute(
            """
            CREATE TABLE server_sources (
                server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
                source_id INTEGER NOT NULL REFERENCES discovery_sources(id) ON DELETE CASCADE,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY(server_id, source_id)
            )
            """
        )
        conn.execute(
            "INSERT INTO server_sources(server_id, source_id, first_seen_at, last_seen_at) "
            "VALUES (?, ?, '2026-09-09T00:00:00+00:00', '2026-09-09T00:00:00+00:00')",
            (server_id, source_id),
        )
        conn.execute("UPDATE schema_version SET version = 3")
        conn.commit()

    upgraded = Storage(path)
    with upgraded.connect() as conn:
        version = conn.execute("SELECT version FROM schema_version").fetchone()["version"]
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(server_sources)")}
        row = conn.execute(
            "SELECT server_id, source_id, active FROM server_sources"
        ).fetchone()
    assert version == 4
    assert "active" in columns
    assert dict(row) == {"server_id": server_id, "source_id": source_id, "active": 1}


def test_v4_schema_is_idempotent(tmp_path):
    path = tmp_path / "nntpintel.db"
    Storage(path)
    Storage(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 4
