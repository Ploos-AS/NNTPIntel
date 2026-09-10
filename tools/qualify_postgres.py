from __future__ import annotations

import os
from datetime import UTC, datetime

from nntpintel.rollups import rebuild_server_observation_rollup_chain
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
    assert storage.schema_version() == 3
    assert storage.migrate() == 3

    with storage.connect() as conn:
        versions = [
            int(row["version"])
            for row in conn.execute(
                "SELECT version FROM nntpintel_schema_version ORDER BY version"
            ).fetchall()
        ]
        assert versions == [1, 2, 3], versions

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

        observations = (
            ("2026-09-09 20:05:00+00", True, 100.0),
            ("2026-09-09 20:35:00+00", False, None),
            ("2026-09-09 21:05:00+00", True, 200.0),
            ("2026-09-09 21:35:00+00", True, 300.0),
        )
        for observed, success, connect_ms in observations:
            conn.execute(
                """
                INSERT INTO observations(
                    endpoint_id, observed_at, success, connect_ms,
                    capabilities_json, tls_json, raw_json
                ) VALUES (%s, %s::timestamptz, %s, %s, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb)
                """,
                (endpoint_id, observed, success, connect_ms),
            )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert count == 4, count

        start = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)
        end = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
        hourly, daily, monthly = rebuild_server_observation_rollup_chain(
            conn, start=start, end=end
        )
        assert hourly.rows_written == 2, hourly
        assert daily.rows_written == 1, daily
        assert monthly.rows_written == 1, monthly

        hourly_rows = conn.execute(
            """
            SELECT bucket_start, observation_count, success_count, failure_count,
                   availability_ratio, connect_ms_count, connect_ms_avg,
                   connect_ms_min, connect_ms_max
            FROM server_observation_rollups
            WHERE server_id = %s AND resolution = 'hour'
            ORDER BY bucket_start
            """,
            (server_id,),
        ).fetchall()
        assert len(hourly_rows) == 2, hourly_rows
        assert hourly_rows[0]["observation_count"] == 2
        assert hourly_rows[0]["success_count"] == 1
        assert hourly_rows[0]["failure_count"] == 1
        assert hourly_rows[0]["availability_ratio"] == 0.5
        assert hourly_rows[0]["connect_ms_count"] == 1
        assert hourly_rows[0]["connect_ms_avg"] == 100.0
        assert hourly_rows[1]["availability_ratio"] == 1.0
        assert hourly_rows[1]["connect_ms_avg"] == 250.0
        assert hourly_rows[1]["connect_ms_min"] == 200.0
        assert hourly_rows[1]["connect_ms_max"] == 300.0

        daily_row = conn.execute(
            """
            SELECT observation_count, success_count, failure_count,
                   availability_ratio, connect_ms_count, connect_ms_avg
            FROM server_observation_rollups
            WHERE server_id = %s AND resolution = 'day'
            """,
            (server_id,),
        ).fetchone()
        assert daily_row["observation_count"] == 4
        assert daily_row["success_count"] == 3
        assert daily_row["failure_count"] == 1
        assert daily_row["availability_ratio"] == 0.75
        assert daily_row["connect_ms_count"] == 3
        assert daily_row["connect_ms_avg"] == 200.0

        monthly_row = conn.execute(
            """
            SELECT bucket_start, observation_count, success_count, failure_count,
                   availability_ratio, connect_ms_count, connect_ms_avg
            FROM server_observation_rollups
            WHERE server_id = %s AND resolution = 'month'
            """,
            (server_id,),
        ).fetchone()
        assert monthly_row["bucket_start"] == datetime(2026, 9, 1, tzinfo=UTC)
        assert monthly_row["observation_count"] == 4
        assert monthly_row["success_count"] == 3
        assert monthly_row["failure_count"] == 1
        assert monthly_row["availability_ratio"] == 0.75
        assert monthly_row["connect_ms_count"] == 3
        assert monthly_row["connect_ms_avg"] == 200.0

        hourly_again, daily_again, monthly_again = rebuild_server_observation_rollup_chain(
            conn, start=start, end=end
        )
        assert hourly_again.rows_written == 2
        assert daily_again.rows_written == 1
        assert monthly_again.rows_written == 1
        total_rollups = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM server_observation_rollups
            WHERE server_id = %s
            """,
            (server_id,),
        ).fetchone()["count"]
        assert total_rollups == 4, total_rollups

        default_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM observations_default WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert default_rows == 4, default_rows
        conn.rollback()

    print(
        "PostgreSQL qualification PASS: migrations, partitioning, types, "
        "insert/query, hourly/daily/monthly rollups, idempotent rebuild"
    )


if __name__ == "__main__":
    main()
