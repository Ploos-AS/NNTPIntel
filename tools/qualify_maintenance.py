from __future__ import annotations

import os
from datetime import UTC, datetime

from nntpintel.maintenance import RetentionPolicy, plan_retention, prune_raw_batches
from nntpintel.maintenance_status import (
    finish_maintenance_run,
    start_maintenance_run,
)
from nntpintel.partition_lifecycle import ensure_partition_window
from nntpintel.storage_backend import PostgresStorage


def main() -> None:
    storage = PostgresStorage(os.environ["NNTPINTEL_DATABASE_URL"])
    with storage.connect() as conn:
        names = ensure_partition_window(
            conn,
            now=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
            months_ahead=1,
        )
        assert len(names) == 8
        assert "observations_2026_09" in names
        assert "observations_2026_10" in names

        for name in names:
            row = conn.execute("SELECT to_regclass(%s) AS name", (name,)).fetchone()
            assert row["name"] is not None, name

        partition_run_id = start_maintenance_run(
            conn,
            kind="partition_lifecycle",
            detail={"partition_count": len(names)},
        )
        finish_maintenance_run(
            conn,
            run_id=partition_run_id,
            status="success",
            detail={"partition_count": len(names)},
        )
        row = conn.execute(
            "SELECT kind, status, finished_at, detail_json FROM maintenance_runs WHERE id = %s",
            (partition_run_id,),
        ).fetchone()
        assert row["kind"] == "partition_lifecycle"
        assert row["status"] == "success"
        assert row["finished_at"] is not None
        assert row["detail_json"]["partition_count"] == 8

        server_id = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("maintenance-qualification.example.net",),
        ).fetchone()["id"]
        endpoint_id = conn.execute(
            """
            INSERT INTO endpoints(server_id, port, transport, starttls)
            VALUES (%s, 119, 'tcp', false)
            RETURNING id
            """,
            (server_id,),
        ).fetchone()["id"]
        old_observed_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        conn.execute(
            """
            INSERT INTO observations(
                endpoint_id, observed_at, success, connect_ms,
                capabilities_json, tls_json, raw_json
            ) VALUES (%s, %s, true, 123.0, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb)
            """,
            (endpoint_id, old_observed_at),
        )
        conn.commit()

        now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
        policy = RetentionPolicy(raw_days=90, safety_lag_hours=48)
        blocked_plan = plan_retention(conn, now=now, policy=policy)
        assert not blocked_plan.coverage_complete
        assert blocked_plan.missing_rollups == (
            "server availability/latency + TLS/capabilities",
        )

        blocked_run_id = start_maintenance_run(
            conn,
            kind="raw_retention",
            detail={"safe_cutoff": blocked_plan.safe_cutoff.isoformat()},
        )
        try:
            prune_raw_batches(conn, now=now, policy=policy, batch_size=100)
        except RuntimeError as exc:
            assert "missing rollup coverage" in str(exc)
            finish_maintenance_run(
                conn,
                run_id=blocked_run_id,
                status="blocked",
                detail={"missing_rollups": list(blocked_plan.missing_rollups)},
            )
        else:
            raise AssertionError("retention unexpectedly proceeded without rollup coverage")

        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert remaining == 1

        bucket_start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        conn.execute(
            """
            INSERT INTO server_observation_rollups(
                server_id, resolution, bucket_start, observation_count,
                success_count, failure_count, availability_ratio,
                connect_ms_count, connect_ms_avg, connect_ms_min, connect_ms_max
            ) VALUES (%s, 'day', %s, 1, 1, 0, 1.0, 1, 123.0, 123.0, 123.0)
            """,
            (server_id, bucket_start),
        )
        conn.execute(
            """
            INSERT INTO server_protocol_rollups(
                server_id, resolution, bucket_start, observation_count,
                tls_enabled_count, tls_ratio, capabilities_observed_count,
                capability_entry_count
            ) VALUES (%s, 'day', %s, 1, 0, 0.0, 0, 0)
            """,
            (server_id, bucket_start),
        )
        conn.commit()

        ready_plan = plan_retention(conn, now=now, policy=policy)
        assert ready_plan.coverage_complete
        assert ready_plan.missing_rollups == ()

        success_run_id = start_maintenance_run(
            conn,
            kind="raw_retention",
            detail={"safe_cutoff": ready_plan.safe_cutoff.isoformat()},
        )
        deleted = prune_raw_batches(conn, now=now, policy=policy, batch_size=100)
        assert deleted["observations"] == 1
        assert deleted["group_snapshots"] == 0
        assert deleted["group_events"] == 0
        assert deleted["propagation_observations"] == 0
        finish_maintenance_run(
            conn,
            run_id=success_run_id,
            status="success",
            detail={"deleted": deleted},
        )

        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM observations WHERE endpoint_id = %s",
            (endpoint_id,),
        ).fetchone()["count"]
        assert remaining == 0

        statuses = {
            int(row["id"]): row["status"]
            for row in conn.execute(
                "SELECT id, status FROM maintenance_runs WHERE id IN (%s, %s)",
                (blocked_run_id, success_run_id),
            ).fetchall()
        }
        assert statuses[blocked_run_id] == "blocked"
        assert statuses[success_run_id] == "success"

        conn.execute("DELETE FROM servers WHERE id = %s", (server_id,))
        conn.commit()

    print(
        "Maintenance qualification PASS: monthly partition window, safe default-range guard, "
        "per-server/day retention coverage, blocked retention, bounded pruning and persisted status"
    )


if __name__ == "__main__":
    main()
