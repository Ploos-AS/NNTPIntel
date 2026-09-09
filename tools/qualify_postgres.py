from __future__ import annotations

import os

from nntpintel.storage_backend import PostgresStorage


def _assert_partitioned(conn, table: str) -> None:
    row = conn.execute(
        """
        SELECT c.relkind, pg_get_partkeydef(c.oid) AS partkey
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema() AND c.relname = %s
        """,
        (table,),
    ).fetchone()
    assert row is not None, table
    assert row["relkind"] == "p", (table, row)
    assert "observed_at" in row["partkey"], (table, row)


def _assert_default_partition(conn, table: str) -> None:
    row = conn.execute(
        """
        SELECT child.relname
        FROM pg_inherits i
        JOIN pg_class parent ON parent.oid = i.inhparent
        JOIN pg_class child ON child.oid = i.inhrelid
        WHERE parent.relname = %s AND pg_get_expr(child.relpartbound, child.oid) = 'DEFAULT'
        """,
        (table,),
    ).fetchone()
    assert row is not None, table


def main() -> None:
    url = os.environ["NNTPINTEL_DATABASE_URL"]
    storage = PostgresStorage(url)
    assert storage.schema_version() == 2
    assert storage.migrate() == 2

    with storage.connect() as conn:
        versions = [
            int(row["version"])
            for row in conn.execute(
                "SELECT version FROM nntpintel_schema_version ORDER BY version"
            ).fetchall()
        ]
        assert versions == [1, 2], versions

        for table in (
            "observations",
            "group_snapshots",
            "group_events",
            "propagation_observations",
        ):
            _assert_partitioned(conn, table)
            _assert_default_partition(conn, table)

        observed_at = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'observations'
              AND column_name = 'observed_at'
            """
        ).fetchone()
        assert observed_at["data_type"] == "timestamp with time zone", observed_at

        raw_json = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'observations'
              AND column_name = 'raw_json'
            """
        ).fetchone()
        assert raw_json["data_type"] == "jsonb", raw_json

        server_id = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("qualification.example.net",),
        ).fetchone()["id"]
        endpoint_id = conn.execute(
            """
            INSERT INTO endpoints(server_id, port, transport, starttls)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (server_id, 119, "tcp", False),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO observations(
                endpoint_id, observed_at, success, capabilities_json, tls_json, raw_json
            ) VALUES (
                %s, TIMESTAMPTZ '2026-09-09 20:00:00+00', TRUE,
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
            )
            """,
            (endpoint_id,),
        )
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert count == 1, count

        default_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM observations_default WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert default_rows == 1, default_rows
        conn.rollback()

    print("PostgreSQL qualification PASS: migrations, schema, partitioning, types, insert/query")


if __name__ == "__main__":
    main()
