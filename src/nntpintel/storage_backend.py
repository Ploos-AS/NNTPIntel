from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import unquote, urlparse

from nntpintel.storage import SCHEMA_VERSION, Storage


@runtime_checkable
class StorageBackend(Protocol):
    """Minimum backend contract used while storage is migrated off SQLite assumptions."""

    backend_name: str

    def connect(self): ...


@dataclass(frozen=True)
class DatabaseTarget:
    backend: str
    value: str


def parse_database_target(value: str | Path) -> DatabaseTarget:
    if isinstance(value, Path):
        return DatabaseTarget("sqlite", str(value))

    text = str(value)
    if "://" not in text:
        return DatabaseTarget("sqlite", text)

    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme == "sqlite":
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("sqlite database URL must not contain a remote host")
        path = unquote(parsed.path)
        if path in {"", "/"}:
            raise ValueError("sqlite database URL requires a path")
        if text.startswith("sqlite:////"):
            sqlite_path = "/" + path.lstrip("/")
        else:
            sqlite_path = path.lstrip("/")
        return DatabaseTarget("sqlite", sqlite_path)

    if scheme in {"postgres", "postgresql"}:
        return DatabaseTarget("postgresql", text)

    raise ValueError(f"unsupported database URL scheme: {scheme}")


class SQLiteStorage(Storage):
    """Explicit SQLite backend; legacy Storage remains compatible during migration."""

    backend_name = "sqlite"


class PostgresStorage:
    """PostgreSQL connection/migration foundation.

    Domain persistence methods move onto the backend contract in later M8 milestones.
    M8.1 intentionally fails closed if a caller tries to use PostgreSQL without the
    optional driver installed.
    """

    backend_name = "postgresql"

    def __init__(self, database_url: str, *, initialize: bool = True):
        target = parse_database_target(database_url)
        if target.backend != "postgresql":
            raise ValueError("PostgresStorage requires a postgres/postgresql database URL")
        self.database_url = target.value
        if initialize:
            self.migrate()

    @staticmethod
    def _driver():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL support requires the 'postgres' extra: "
                "pip install 'nntpintel[postgres]'"
            ) from exc
        return psycopg, dict_row

    def connect(self):
        psycopg, dict_row = self._driver()
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def migrate(self) -> int:
        from nntpintel.storage_migrations import apply_postgres_migrations

        with self.connect() as conn:
            return apply_postgres_migrations(conn)

    def schema_version(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT version FROM nntpintel_schema_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return 0
        return int(row["version"])


def open_storage(value: str | Path) -> StorageBackend:
    target = parse_database_target(value)
    if target.backend == "sqlite":
        return SQLiteStorage(target.value)
    if target.backend == "postgresql":
        return PostgresStorage(target.value)
    raise AssertionError(f"unhandled database backend: {target.backend}")


def expected_schema_version() -> int:
    return SCHEMA_VERSION
