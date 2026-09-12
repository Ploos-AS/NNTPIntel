from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
from urllib.parse import urlparse, urlunparse

import psycopg

from nntpintel.backup import create_backup, postgres_env, restore_backup, verify_backup


def _database_url_with_name(database_url: str, database: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def main() -> None:
    source_url = os.environ["NNTPINTEL_DATABASE_URL"]
    restore_database = "nntpintel_restore_qualification"
    restore_url = _database_url_with_name(source_url, restore_database)

    with psycopg.connect(source_url) as conn:
        conn.execute(
            "INSERT INTO servers(host) VALUES (%s) ON CONFLICT (host) DO NOTHING",
            ("backup-restore-qualification.example.net",),
        )
        conn.commit()
        source_schema_version = conn.execute(
            "SELECT MAX(version) FROM nntpintel_schema_version"
        ).fetchone()[0]

    with tempfile.TemporaryDirectory(prefix="nntpintel-backup-") as tmp:
        backup_path = pathlib.Path(tmp) / "qualification.dump"
        manifest = create_backup(source_url, backup_path)
        verified = verify_backup(backup_path)
        assert verified.sha256 == manifest.sha256
        assert backup_path.exists()
        assert backup_path.with_name(backup_path.name + ".manifest.json").exists()

        admin_env = postgres_env(source_url)
        admin_env["PGDATABASE"] = "postgres"
        subprocess.run(
            ["psql", "--set", "ON_ERROR_STOP=1", "--command", f"DROP DATABASE IF EXISTS {restore_database}"],
            env=admin_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            ["psql", "--set", "ON_ERROR_STOP=1", "--command", f"CREATE DATABASE {restore_database}"],
            env=admin_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )

        restore_backup(restore_url, backup_path)
        with psycopg.connect(restore_url) as conn:
            restored = conn.execute(
                "SELECT COUNT(*) FROM servers WHERE host = %s",
                ("backup-restore-qualification.example.net",),
            ).fetchone()[0]
            restored_schema_version = conn.execute(
                "SELECT MAX(version) FROM nntpintel_schema_version"
            ).fetchone()[0]
            assert restored == 1
            assert restored_schema_version == source_schema_version
            assert conn.execute("SELECT to_regclass('maintenance_runs')").fetchone()[0] is not None
            assert conn.execute("SELECT to_regclass('server_observation_rollups')").fetchone()[0] is not None

        subprocess.run(
            ["psql", "--set", "ON_ERROR_STOP=1", "--command", f"DROP DATABASE {restore_database}"],
            env=admin_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    print(
        "Backup/restore qualification PASS: custom-format dump, SHA-256 manifest, "
        "pg_restore verification, clean target restore, schema version and retained data"
    )


if __name__ == "__main__":
    main()
