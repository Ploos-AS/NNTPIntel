from __future__ import annotations

import os
from datetime import UTC, datetime

from nntpintel.group_rollups import rebuild_server_group_rollup_chain
from nntpintel.storage_backend import PostgresStorage


def main() -> None:
    storage = PostgresStorage(os.environ["NNTPINTEL_DATABASE_URL"])
    assert storage.schema_version() == 6

    with storage.connect() as conn:
        server_id = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("groups-qualification.example.net",),
        ).fetchone()["id"]
        endpoint_id = conn.execute(
            """
            INSERT INTO endpoints(server_id, port, transport, starttls)
            VALUES (%s, 119, 'tcp', false)
            RETURNING id
            """,
            (server_id,),
        ).fetchone()["id"]

        comp_id = conn.execute(
            """
            INSERT INTO hierarchies(name, first_seen_at, last_seen_at)
            VALUES ('comp', '2026-09-09 20:00:00+00', '2026-09-09 21:00:00+00')
            RETURNING id
            """
        ).fetchone()["id"]
        alt_id = conn.execute(
            """
            INSERT INTO hierarchies(name, first_seen_at, last_seen_at)
            VALUES ('alt', '2026-09-09 20:00:00+00', '2026-09-09 21:00:00+00')
            RETURNING id
            """
        ).fetchone()["id"]

        groups = {}
        for name, hierarchy_id in (
            ("comp.test", comp_id),
            ("comp.lang.python", comp_id),
            ("alt.test", alt_id),
        ):
            groups[name] = conn.execute(
                """
                INSERT INTO newsgroups(name, hierarchy_id, first_seen_at, last_seen_at)
                VALUES (%s, %s, '2026-09-09 20:00:00+00', '2026-09-09 21:00:00+00')
                RETURNING id
                """,
                (name, hierarchy_id),
            ).fetchone()["id"]

        snapshots = (
            ("2026-09-09 20:05:00+00", "comp.test", "y"),
            ("2026-09-09 20:05:00+00", "comp.lang.python", "m"),
            ("2026-09-09 20:05:00+00", "alt.test", "n"),
            ("2026-09-09 21:05:00+00", "comp.test", "y"),
            ("2026-09-09 21:05:00+00", "comp.lang.python", "y"),
        )
        for observed_at, name, status in snapshots:
            conn.execute(
                """
                INSERT INTO group_snapshots(
                    endpoint_id, newsgroup_id, observed_at, high_water, low_water,
                    posting_status, description
                ) VALUES (%s, %s, %s::timestamptz, 10, 1, %s, '')
                """,
                (endpoint_id, groups[name], observed_at, status),
            )

        events = (
            ("2026-09-09 20:05:00+00", "comp.test", "appeared"),
            ("2026-09-09 20:05:00+00", "comp.lang.python", "appeared"),
            ("2026-09-09 20:05:00+00", "alt.test", "appeared"),
            ("2026-09-09 21:05:00+00", "comp.lang.python", "changed"),
            ("2026-09-09 21:05:00+00", "alt.test", "disappeared"),
        )
        for observed_at, name, event_type in events:
            conn.execute(
                """
                INSERT INTO group_events(
                    endpoint_id, newsgroup_id, observed_at, event_type, detail_json
                ) VALUES (%s, %s, %s::timestamptz, %s, '{}'::jsonb)
                """,
                (endpoint_id, groups[name], observed_at, event_type),
            )
        conn.commit()

        start = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)
        end = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
        results = rebuild_server_group_rollup_chain(conn, start=start, end=end)
        assert [item.summary_rows_written for item in results] == [2, 1, 1]

        daily = conn.execute(
            """
            SELECT inventory_count, snapshot_count, observed_group_count,
                   observed_hierarchy_count, event_count
            FROM server_group_rollups
            WHERE server_id = %s AND resolution = 'day'
            """,
            (server_id,),
        ).fetchone()
        assert daily["inventory_count"] == 2
        assert daily["snapshot_count"] == 5
        assert daily["observed_group_count"] == 3
        assert daily["observed_hierarchy_count"] == 2
        assert daily["event_count"] == 5

        values = {
            (row["kind"], row["value"]): row["occurrence_count"]
            for row in conn.execute(
                """
                SELECT kind, value, occurrence_count
                FROM server_group_value_rollups
                WHERE server_id = %s AND resolution = 'day'
                """,
                (server_id,),
            ).fetchall()
        }
        assert values[("posting_status", "y")] == 3
        assert values[("posting_status", "m")] == 1
        assert values[("posting_status", "n")] == 1
        assert values[("event_type", "appeared")] == 3
        assert values[("event_type", "changed")] == 1
        assert values[("event_type", "disappeared")] == 1

        again = rebuild_server_group_rollup_chain(conn, start=start, end=end)
        assert [item.summary_rows_written for item in again] == [2, 1, 1]
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM server_group_rollups WHERE server_id = %s",
            (server_id,),
        ).fetchone()["count"]
        assert count == 4, count
        conn.rollback()

    print(
        "Group rollup qualification PASS: hourly/daily/monthly inventories, groups, "
        "hierarchies, posting status, events and idempotent rebuild"
    )


if __name__ == "__main__":
    main()
