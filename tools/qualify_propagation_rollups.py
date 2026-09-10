from __future__ import annotations

import os
from datetime import UTC, datetime

from nntpintel.propagation_rollups import rebuild_propagation_rollup_chain
from nntpintel.storage_backend import PostgresStorage


def main() -> None:
    storage = PostgresStorage(os.environ["NNTPINTEL_DATABASE_URL"])
    assert storage.schema_version() == 7

    with storage.connect() as conn:
        server_id = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("propagation.example.net",),
        ).fetchone()["id"]
        endpoint_id = conn.execute(
            """
            INSERT INTO endpoints(server_id, port, transport, starttls)
            VALUES (%s, 119, 'tcp', false) RETURNING id
            """,
            (server_id,),
        ).fetchone()["id"]
        article_id = conn.execute(
            """
            INSERT INTO propagation_articles(message_id, first_registered_at)
            VALUES ('<m8.3@nntpintel.test>', '2026-09-10 10:00:00+00') RETURNING id
            """
        ).fetchone()["id"]
        for observed_at, present, code, error in (
            ("2026-09-10 10:01:00+00", False, 430, None),
            ("2026-09-10 10:02:00+00", False, 500, "temporary"),
            ("2026-09-10 10:05:00+00", True, 223, None),
            ("2026-09-10 10:15:00+00", True, 223, None),
        ):
            conn.execute(
                """
                INSERT INTO propagation_observations(
                    article_id, endpoint_id, observed_at, present, response_code, error
                ) VALUES (%s, %s, %s::timestamptz, %s, %s, %s)
                """,
                (article_id, endpoint_id, observed_at, present, code, error),
            )
        campaign_id = conn.execute(
            """
            INSERT INTO propagation_campaigns(
                article_id, status, stop_after_visible, created_at, expires_at, completed_at
            ) VALUES (
                %s, 'completed', 1,
                '2026-09-10 10:00:00+00', '2026-09-10 12:00:00+00',
                '2026-09-10 10:16:00+00'
            ) RETURNING id
            """,
            (article_id,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO propagation_campaign_endpoints(campaign_id, endpoint_id) VALUES (%s, %s)",
            (campaign_id, endpoint_id),
        )
        conn.execute(
            """
            INSERT INTO propagation_incidents(
                server_id, kind, severity, started_at, updated_at, resolved_at, window
            ) VALUES (
                %s, 'delay_spike', 'warning',
                '2026-09-10 10:20:00+00', '2026-09-10 10:25:00+00',
                '2026-09-10 10:40:00+00', '1h'
            )
            """,
            (server_id,),
        )
        conn.commit()

        start = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        end = datetime(2026, 9, 10, 11, 0, tzinfo=UTC)
        results = rebuild_propagation_rollup_chain(conn, start=start, end=end)
        assert [r.server_rows_written for r in results] == [1, 1, 1]
        assert [r.campaign_rows_written for r in results] == [1, 1, 1]

        row = conn.execute(
            """
            SELECT probe_count, present_count, absent_count, unknown_count,
                   presence_ratio, article_count, first_seen_delay_count,
                   first_seen_delay_avg_seconds, incident_started_count
            FROM server_propagation_rollups
            WHERE server_id = %s AND resolution = 'hour'
            """,
            (server_id,),
        ).fetchone()
        assert row["probe_count"] == 4
        assert row["present_count"] == 2
        assert row["absent_count"] == 1
        assert row["unknown_count"] == 1
        assert row["presence_ratio"] == 2 / 3
        assert row["article_count"] == 1
        assert row["first_seen_delay_count"] == 1
        assert row["first_seen_delay_avg_seconds"] == 300.0
        assert row["incident_started_count"] == 1

        values = {
            (r["kind"], r["value"]): r["occurrence_count"]
            for r in conn.execute(
                """
                SELECT kind, value, occurrence_count
                FROM server_propagation_value_rollups
                WHERE server_id = %s AND resolution = 'hour'
                """,
                (server_id,),
            ).fetchall()
        }
        assert values[("incident_kind", "delay_spike")] == 1
        assert values[("incident_severity", "warning")] == 1

        campaign = conn.execute(
            """
            SELECT created_count, completed_count, expired_or_closed_count
            FROM propagation_campaign_rollups
            WHERE resolution = 'hour'
            """
        ).fetchone()
        assert campaign["created_count"] == 1
        assert campaign["completed_count"] == 1
        assert campaign["expired_or_closed_count"] == 1

        again = rebuild_propagation_rollup_chain(conn, start=start, end=end)
        assert [r.server_rows_written for r in again] == [1, 1, 1]
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM server_propagation_rollups WHERE server_id = %s",
            (server_id,),
        ).fetchone()["count"]
        assert count == 3
        conn.rollback()

    print(
        "Propagation rollup qualification PASS: presence, unknown semantics, first-seen delay, "
        "campaigns, incidents, hour/day/month, idempotent rebuild"
    )


if __name__ == "__main__":
    main()
