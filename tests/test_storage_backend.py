import pytest

from nntpintel.storage import Storage
from nntpintel.storage_backend import (
    PostgresStorage,
    SQLiteStorage,
    open_storage,
    parse_database_target,
)
from nntpintel.storage_migrations import POSTGRES_MIGRATIONS, apply_postgres_migrations


def test_parse_database_target_supports_paths_and_urls(tmp_path):
    path = tmp_path / "nntpintel.db"
    assert parse_database_target(path).backend == "sqlite"
    assert parse_database_target(path).value == str(path)

    relative = parse_database_target("sqlite:///data/nntpintel.db")
    assert relative.backend == "sqlite"
    assert relative.value == "data/nntpintel.db"

    absolute = parse_database_target("sqlite:////var/lib/nntpintel/nntpintel.db")
    assert absolute.backend == "sqlite"
    assert absolute.value == "/var/lib/nntpintel/nntpintel.db"

    postgres = parse_database_target("postgresql://user:pass@db/nntpintel")
    assert postgres.backend == "postgresql"
    assert postgres.value == "postgresql://user:pass@db/nntpintel"


def test_parse_database_target_rejects_unknown_and_remote_sqlite_urls():
    with pytest.raises(ValueError, match="unsupported database URL scheme"):
        parse_database_target("mysql://db/nntpintel")
    with pytest.raises(ValueError, match="remote host"):
        parse_database_target("sqlite://remote/data.db")


def test_open_storage_uses_explicit_sqlite_backend_and_keeps_legacy_compatibility(tmp_path):
    storage = open_storage(tmp_path / "nntpintel.db")
    assert isinstance(storage, SQLiteStorage)
    assert isinstance(storage, Storage)
    assert storage.backend_name == "sqlite"
    endpoint_id = storage.ensure_endpoint("news.example.net")
    assert endpoint_id > 0


def test_postgres_storage_can_be_configured_without_eager_driver_import():
    storage = PostgresStorage("postgres://user:pass@db/nntpintel", initialize=False)
    assert storage.backend_name == "postgresql"
    assert storage.database_url == "postgres://user:pass@db/nntpintel"

    with pytest.raises(ValueError, match="requires a postgres"):
        PostgresStorage("sqlite:///data.db", initialize=False)


class FakeConnection:
    def __init__(self):
        self.applied: set[int] = set()
        self.inserted: list[tuple[int, str]] = []
        self.committed = False
        self.executed_sql: list[str] = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.executed_sql.append(normalized)
        if normalized.startswith("SELECT version FROM nntpintel_schema_version"):
            return FakeResult([{"version": version} for version in sorted(self.applied)])
        if normalized.startswith("INSERT INTO nntpintel_schema_version"):
            version, name = params
            self.applied.add(int(version))
            self.inserted.append((int(version), str(name)))
        return FakeResult([])

    def commit(self):
        self.committed = True


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_postgres_migrations_are_idempotent():
    conn = FakeConnection()
    assert apply_postgres_migrations(conn) == 6
    expected = [
        (1, "bootstrap schema metadata"),
        (2, "production core schema and observation partitions"),
        (3, "server availability and latency rollups"),
        (4, "allow monthly server observation rollups"),
        (5, "server TLS and capability rollups"),
        (6, "server group hierarchy and event rollups"),
    ]
    assert conn.inserted == expected
    assert conn.committed is True

    conn.committed = False
    assert apply_postgres_migrations(conn) == 6
    assert conn.inserted == expected
    assert conn.committed is True


def test_postgres_production_schema_uses_timestamptz_jsonb_and_range_partitioning():
    migration = POSTGRES_MIGRATIONS[1]
    sql = " ".join(migration.sql.split())

    assert migration.version == 2
    assert "TIMESTAMPTZ" in sql
    assert "JSONB" in sql
    for table in (
        "observations",
        "group_snapshots",
        "group_events",
        "propagation_observations",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert "PARTITION BY RANGE (observed_at)" in sql
        assert f"CREATE TABLE IF NOT EXISTS {table}_default PARTITION OF {table} DEFAULT" in sql


def test_partitioned_primary_and_unique_keys_include_observed_at():
    sql = " ".join(POSTGRES_MIGRATIONS[1].sql.split())
    assert sql.count("PRIMARY KEY(id, observed_at)") == 4
    assert "UNIQUE(endpoint_id, newsgroup_id, observed_at)" in sql
    assert "UNIQUE(article_id, endpoint_id, observed_at)" in sql


def test_server_observation_rollup_schema_is_version_three():
    migration = POSTGRES_MIGRATIONS[2]
    sql = " ".join(migration.sql.split())
    assert migration.version == 3
    assert "CREATE TABLE IF NOT EXISTS server_observation_rollups" in sql
    assert "resolution IN ('hour', 'day')" in sql
    assert "PRIMARY KEY(server_id, resolution, bucket_start)" in sql


def test_monthly_rollup_support_is_an_upgrade_migration():
    migration = POSTGRES_MIGRATIONS[3]
    sql = " ".join(migration.sql.split())
    assert migration.version == 4
    assert migration.name == "allow monthly server observation rollups"
    assert "DROP CONSTRAINT IF EXISTS server_observation_rollups_resolution_check" in sql
    assert "CHECK (resolution IN ('hour', 'day', 'month'))" in sql


def test_protocol_rollup_schema_is_version_five():
    migration = POSTGRES_MIGRATIONS[4]
    sql = " ".join(migration.sql.split())
    assert migration.version == 5
    assert "CREATE TABLE IF NOT EXISTS server_protocol_rollups" in sql
    assert "CREATE TABLE IF NOT EXISTS server_protocol_value_rollups" in sql
    assert "tls_protocol" in sql
    assert "tls_cipher" in sql
    assert "capability" in sql
    assert "resolution IN ('hour', 'day', 'month')" in sql


def test_group_hierarchy_rollup_schema_is_version_six():
    migration = POSTGRES_MIGRATIONS[5]
    sql = " ".join(migration.sql.split())
    assert migration.version == 6
    assert migration.name == "server group hierarchy and event rollups"
    assert "CREATE TABLE IF NOT EXISTS server_group_rollups" in sql
    assert "CREATE TABLE IF NOT EXISTS server_group_value_rollups" in sql
    assert "inventory_count" in sql
    assert "observed_group_count" in sql
    assert "observed_hierarchy_count" in sql
    assert "posting_status" in sql
    assert "event_type" in sql
