from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresMigration:
    version: int
    name: str
    sql: str


POSTGRES_MIGRATIONS = (
    PostgresMigration(
        1,
        "bootstrap schema metadata",
        """
        CREATE TABLE IF NOT EXISTS nntpintel_schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
)


def apply_postgres_migrations(conn) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nntpintel_schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    rows = conn.execute("SELECT version FROM nntpintel_schema_version").fetchall()
    applied = {int(row["version"]) for row in rows}

    for migration in POSTGRES_MIGRATIONS:
        if migration.version in applied:
            continue
        conn.execute(migration.sql)
        conn.execute(
            "INSERT INTO nntpintel_schema_version(version, name) VALUES (%s, %s)",
            (migration.version, migration.name),
        )
    conn.commit()
    return POSTGRES_MIGRATIONS[-1].version if POSTGRES_MIGRATIONS else 0
