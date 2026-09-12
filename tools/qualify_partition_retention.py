from __future__ import annotations

import os
from datetime import UTC, datetime

from nntpintel.maintenance import (
    RetentionPolicy,
    list_partition_retirement_candidates,
    plan_retention,
    retire_eligible_partitions,
)
from nntpintel.partition_lifecycle import ensure_monthly_partition
from nntpintel.storage_backend import PostgresStorage


def _insert_rollups(conn, *, server_id: int, day: datetime, connect_ms: float) -> None:
    conn.execute(
        """
        INSERT INTO server_observation_rollups(
            server_id, resolution, bucket_start, observation_count,
            success_count, failure_count, availability_ratio,
            connect_ms_count, connect_ms_avg, connect_ms_min, connect_ms_max
        ) VALUES (%s, 'day', %s, 1, 1, 0, 1.0, 1, %s, %s, %s)
        """,
        (server_id, day, connect_ms, connect_ms, connect_ms),
    )
    conn.execute(
        """
        INSERT INTO server_protocol_rollups(
            server_id, resolution, bucket_start, observation_count,
            tls_enabled_count, tls_ratio, capabilities_observed_count,
            capability_entry_count
        ) VALUES (%s, 'day', %s, 1, 0, 0.0, 0, 0)
        """,
        (server_id, day),
    )
    conn.commit()


def _insert_observation(conn, *, endpoint_id: int, observed_at: datetime, connect_ms: float) -> None:
    conn.execute(
        """
        INSERT INTO observations(
            endpoint_id, observed_at, success, connect_ms,
            capabilities_json, tls_json, raw_json
        ) VALUES (%s, %s, true, %s, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb)
        """,
        (endpoint_id, observed_at, connect_ms),
    )
    conn.commit()


def main() -> None:
    storage = PostgresStorage(os.environ["NNTPINTEL_DATABASE_URL"])
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    policy = RetentionPolicy(raw_days=90, safety_lag_hours=48)

    with storage.connect() as conn:
        march = datetime(2026, 3, 1, tzinfo=UTC)
        april = datetime(2026, 4, 1, tzinfo=UTC)
        march_name = ensure_monthly_partition(conn, table="observations", month=march)
        april_name = ensure_monthly_partition(conn, table="observations", month=april)

        march_server = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("retention-march.example.net",),
        ).fetchone()["id"]
        april_server = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("retention-april.example.net",),
        ).fetchone()["id"]
        march_endpoint = conn.execute(
            """
            INSERT INTO endpoints(server_id, port, transport, starttls)
            VALUES (%s, 119, 'tcp', false) RETURNING id
            """,
            (march_server,),
        ).fetchone()["id"]
        april_endpoint = conn.execute(
            """
            INSERT INTO endpoints(server_id, port, transport, starttls)
            VALUES (%s, 119, 'tcp', false) RETURNING id
            """,
            (april_server,),
        ).fetchone()["id"]
        conn.commit()

        _insert_observation(
            conn,
            endpoint_id=march_endpoint,
            observed_at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
            connect_ms=31.0,
        )
        _insert_observation(
            conn,
            endpoint_id=april_endpoint,
            observed_at=datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
            connect_ms=41.0,
        )
        _insert_rollups(
            conn,
            server_id=april_server,
            day=datetime(2026, 4, 15, tzinfo=UTC),
            connect_ms=41.0,
        )

        global_plan = plan_retention(conn, now=now, policy=policy)
        assert not global_plan.coverage_complete

        candidates = {
            candidate.partition: candidate
            for candidate in list_partition_retirement_candidates(conn, now=now, policy=policy)
        }
        assert candidates[march_name].coverage_complete is False
        assert candidates[april_name].coverage_complete is True

        retired = retire_eligible_partitions(conn, now=now, policy=policy, limit=1)
        assert retired == (april_name,)
        assert conn.execute("SELECT to_regclass(%s) AS name", (april_name,)).fetchone()["name"] is None
        assert conn.execute("SELECT to_regclass(%s) AS name", (march_name,)).fetchone()["name"] is not None

        _insert_rollups(
            conn,
            server_id=march_server,
            day=datetime(2026, 3, 15, tzinfo=UTC),
            connect_ms=31.0,
        )
        retired = retire_eligible_partitions(conn, now=now, policy=policy)
        assert march_name in retired
        assert conn.execute("SELECT to_regclass(%s) AS name", (march_name,)).fetchone()["name"] is None

        conn.execute("DELETE FROM servers WHERE id IN (%s, %s)", (march_server, april_server))
        conn.commit()

    print(
        "Partition retention qualification PASS: exact month coverage, unrelated missing "
        "coverage isolation, eligible enumeration, limit and safe bulk retirement"
    )


if __name__ == "__main__":
    main()
