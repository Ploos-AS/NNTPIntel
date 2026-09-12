import pathlib
import subprocess

import pytest

from nntpintel.backup import BackupManifest, manifest_path, postgres_env, restore_backup


def test_postgres_env_keeps_credentials_out_of_command_arguments(monkeypatch):
    monkeypatch.setenv("KEEP_ME", "yes")
    env = postgres_env("postgresql://user:p%40ss@example.net:5544/nntpintel?sslmode=require")
    assert env["PGHOST"] == "example.net"
    assert env["PGPORT"] == "5544"
    assert env["PGDATABASE"] == "nntpintel"
    assert env["PGUSER"] == "user"
    assert env["PGPASSWORD"] == "p@ss"
    assert env["PGSSLMODE"] == "require"
    assert env["KEEP_ME"] == "yes"


def test_postgres_env_rejects_non_postgres_urls():
    with pytest.raises(ValueError):
        postgres_env("sqlite:///tmp/nntpintel.db")


def test_manifest_path_is_sidecar():
    path = pathlib.Path("backup.dump")
    assert manifest_path(path) == pathlib.Path("backup.dump.manifest.json")


def test_backup_manifest_serializes_stable_fields():
    manifest = BackupManifest(
        created_at="2026-09-12T00:00:00+00:00",
        format="postgresql-custom",
        sha256="a" * 64,
        size_bytes=123,
    )
    assert manifest.as_dict() == {
        "created_at": "2026-09-12T00:00:00+00:00",
        "format": "postgresql-custom",
        "sha256": "a" * 64,
        "size_bytes": 123,
    }


def test_restore_targets_database_explicitly(monkeypatch, tmp_path):
    backup_path = tmp_path / "backup.dump"
    backup_path.write_bytes(b"dump")
    manifest = BackupManifest(
        created_at="2026-09-12T00:00:00+00:00",
        format="postgresql-custom",
        sha256="a" * 64,
        size_bytes=4,
    )
    monkeypatch.setattr("nntpintel.backup.verify_backup", lambda path: manifest)

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    restore_backup("postgresql://user:secret@example.net:5544/restore_db", backup_path)

    command, kwargs = calls[0]
    assert command[:3] == ["pg_restore", "--dbname", "restore_db"]
    assert "secret" not in " ".join(command)
    assert kwargs["env"]["PGHOST"] == "example.net"
    assert kwargs["env"]["PGPORT"] == "5544"
    assert kwargs["env"]["PGPASSWORD"] == "secret"
