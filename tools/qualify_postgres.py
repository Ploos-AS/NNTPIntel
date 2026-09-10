from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from nntpintel.protocol_rollups import rebuild_server_protocol_rollup_chain
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
    assert storage.schema_version() == 5
    assert storage.migrate() == 5

    with storage.connect() as conn:
        versions = [
            int(row["version"])
            for row in conn.execute(
                "SELECT version FROM nntpintel_schema_version ORDER BY version"
            ).fetchall()
        ]
        assert versions == [1, 2, 3, 4, 5], versions

        constraint = conn.execute(
            """
            SELECT pg_get_constraintdef(c.oid) AS definition
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'server_observation_rollups'
              AND c.conname = 'server_observation_rollups_resolution_check'
            """
        ).fetchone()
        assert constraint is not None
        assert "month" in constraint["definition"], constraint

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
            (
                "2026-09-09 20:05:00+00",
                True,
                100.0,
                ["VERSION 2", "READER", "STARTTLS"],
                {"enabled": True, "protocol": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384"},
            ),
            (
                "2026-09-09 20:35:00+00",
                False,
                None,
                [],
                {"enabled": False},
            ),
            (
                "2026-09-09 21:05:00+00",
                True,
                200.0,
                ["VERSION 2", "READER"],
                {"enabled": True, "protocol": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384"},
            ),
            (
                "2026-09-09 21:35:00+00",
                True,
                300.0,
                ["VERSION 2", "READER", "OVER"],
                {"enabled": True, "protocol": "TLSv1.2", "cipher": "ECDHE-RSA-AES256-GCM-SHA384"},
            ),
        )
        for observed, success, connect_ms, capabilities, tls in observations:
            conn.execute(
                """
                INSERT INTO observations(
                    endpoint_id, observed_at, success, connect_ms,
                    capabilities_json, tls_json, raw_json
                ) VALUES (%s, %s::timestamptz, %s, %s, %s::jsonb, %s::jsonb, '{}'::jsonb)
                """,
                (
                    endpoint_id,
                    observed,
                    success,
                    connect_ms,
                    json.dumps(capabilities),
                    json.dumps(tls),
                ),
            )
        conn.commit()

        start = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)
        end = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
        hourly, daily, monthly = rebuild_server_observation_rollup_chain(
            conn, start=start, end=end
        )
        assert (hourly.rows_written, daily.rows_written, monthly.rows_written) == (2, 1, 1)

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
            SELECT bucket_start, observation_count, availability_ratio
            FROM server_observation_rollups
            WHERE server_id = %s AND resolution = 'month'
            """,
            (server_id,),
        ).fetchone()
        assert monthly_row["bucket_start"] == datetime(2026, 9, 1, tzinfo=UTC)
        assert monthly_row["observation_count"] == 4
        assert monthly_row["availability_ratio"] == 0.75

        protocol_results = rebuild_server_protocol_rollup_chain(conn, start=start, end=end)
        assert [item.summary_rows_written for item in protocol_results] == [2, 1, 1]

        protocol_daily = conn.execute(
            """
            SELECT observation_count, tls_enabled_count, tls_ratio,
                   capabilities_observed_count, capability_entry_count
            FROM server_protocol_rollups
            WHERE server_id = %s AND resolution = 'day'
            """,
            (server_id,),
        ).fetchone()
        assert protocol_daily["observation_count"] == 4
        assert protocol_daily["tls_enabled_count"] == 3
        assert protocol_daily["tls_ratio"] == 0.75
        assert protocol_daily["capabilities_observed_count"] == 3
        assert protocol_daily["capability_entry_count"] == 8

        values = {
            (row["kind"], row["value"]): row["occurrence_count"]
            for row in conn.execute(
                """
                SELECT kind, value, occurrence_count
                FROM server_protocol_value_rollups
                WHERE server_id = %s AND resolution = 'day'
                """,
                (server_id,),
            ).fetchall()
        }
        assert values[("tls_protocol", "TLSv1.3")] == 2
        assert values[("tls_protocol", "TLSv1.2")] == 1
        assert values[("capability", "VERSION")] == 3
        assert values[("capability", "READER")] == 3
        assert values[("capability", "STARTTLS")] == 1
        assert values[("capability", "OVER")] == 1

        protocol_again = rebuild_server_protocol_rollup_chain(conn, start=start, end=end)
        assert [item.summary_rows_written for item in protocol_again] == [2, 1, 1]
        summary_count = conn.execute(
            "SELECT COUNT(*) AS count FROM server_protocol_rollups WHERE server_id = %s",
            (server_id,),
        ).fetchone()["count"]
        assert summary_count == 4, summary_count

        default_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM observations_default WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert default_rows == 4, default_rows
        conn.rollback()

    print(
        "PostgreSQL qualification PASS: migrations, partitioning, hourly/daily/monthly "
        "availability, latency, TLS and normalized capability rollups"
    )


if __name__ == "__main__":
    main()
