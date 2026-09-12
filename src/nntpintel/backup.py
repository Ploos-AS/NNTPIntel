from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
from urllib.parse import parse_qs, unquote, urlparse


@dataclasses.dataclass(frozen=True)
class BackupManifest:
    created_at: str
    format: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, str | int]:
        return dataclasses.asdict(self)


def postgres_env(database_url: str) -> dict[str, str]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("backup/restore requires a PostgreSQL database URL")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise ValueError("PostgreSQL URL must include host and database name")

    env = os.environ.copy()
    env["PGHOST"] = parsed.hostname
    env["PGDATABASE"] = unquote(parsed.path.lstrip("/"))
    if parsed.port is not None:
        env["PGPORT"] = str(parsed.port)
    if parsed.username is not None:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)

    query = parse_qs(parsed.query)
    if query.get("sslmode"):
        env["PGSSLMODE"] = query["sslmode"][-1]
    return env


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(backup_path: pathlib.Path) -> pathlib.Path:
    return backup_path.with_name(backup_path.name + ".manifest.json")


def create_backup(database_url: str, backup_path: pathlib.Path, *, overwrite: bool = False) -> BackupManifest:
    backup_path = backup_path.resolve()
    if backup_path.exists() and not overwrite:
        raise FileExistsError(f"backup already exists: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    with backup_path.open("wb") as output:
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-privileges"],
            env=postgres_env(database_url),
            stdout=output,
            check=True,
        )
    manifest = BackupManifest(
        created_at=datetime.datetime.now(datetime.UTC).isoformat(),
        format="postgresql-custom",
        sha256=sha256_file(backup_path),
        size_bytes=backup_path.stat().st_size,
    )
    manifest_path(backup_path).write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_manifest(backup_path: pathlib.Path) -> BackupManifest:
    data = json.loads(manifest_path(backup_path).read_text(encoding="utf-8"))
    return BackupManifest(
        created_at=str(data["created_at"]),
        format=str(data["format"]),
        sha256=str(data["sha256"]),
        size_bytes=int(data["size_bytes"]),
    )


def verify_backup(backup_path: pathlib.Path) -> BackupManifest:
    backup_path = backup_path.resolve()
    manifest = load_manifest(backup_path)
    if manifest.format != "postgresql-custom":
        raise RuntimeError(f"unsupported backup format: {manifest.format}")
    if backup_path.stat().st_size != manifest.size_bytes:
        raise RuntimeError("backup verification failed: size mismatch")
    if sha256_file(backup_path) != manifest.sha256:
        raise RuntimeError("backup verification failed: SHA-256 mismatch")
    with backup_path.open("rb") as source:
        subprocess.run(
            ["pg_restore", "--list"],
            stdin=source,
            stdout=subprocess.DEVNULL,
            check=True,
        )
    return manifest


def restore_backup(database_url: str, backup_path: pathlib.Path, *, clean: bool = False) -> BackupManifest:
    manifest = verify_backup(backup_path)
    command = ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error"]
    if clean:
        command.extend(["--clean", "--if-exists"])
    with backup_path.resolve().open("rb") as source:
        subprocess.run(
            command,
            env=postgres_env(database_url),
            stdin=source,
            check=True,
        )
    return manifest
