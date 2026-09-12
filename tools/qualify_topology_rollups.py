from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from nntpintel.storage_backend import PostgresStorage
from nntpintel.topology_rollups import rebuild_topology_rollup_chain


def _bundle(*, conclusion_type: str, evidence_level: str, risk_path: str, risk_level: str) -> str:
    analysis = {risk_path: {"risk_level": risk_level}}
    return json.dumps(
        {
            "model": "nntpintel_topology_evidence_bundle",
            "schema_version": 1,
            "authoritative_topology": False,
            "conclusion": {"type": conclusion_type},
            "quality": {"evidence_level": evidence_level},
            "analysis": analysis,
        }
    )


def main() -> None:
    storage = PostgresStorage(os.environ["NNTPINTEL_DATABASE_URL"])
    assert storage.schema_version() == 9

    with storage.connect() as conn:
        server_id = conn.execute(
            "INSERT INTO servers(host) VALUES (%s) RETURNING id",
            ("topology-rollups.example.net",),
        ).fetchone()["id"]

        snapshots = (
            (
                "risk:server:qualification",
                "risk",
                "fp-risk-moderate",
                "2026-09-10 10:05:00+00",
                _bundle(
                    conclusion_type="risk",
                    evidence_level="high",
                    risk_path="risk",
                    risk_level="moderate",
                ),
            ),
            (
                "community:qualification",
                "community",
                "fp-community-high",
                "2026-09-10 10:35:00+00",
                _bundle(
                    conclusion_type="community",
                    evidence_level="limited",
                    risk_path="community",
                    risk_level="high",
                ),
            ),
            (
                "risk:server:qualification",
                "risk",
                "fp-risk-critical",
                "2026-09-10 11:05:00+00",
                _bundle(
                    conclusion_type="risk",
                    evidence_level="low",
                    risk_path="risk",
                    risk_level="critical",
                ),
            ),
        )
        for conclusion_ref, conclusion_type, fingerprint, captured_at, bundle_json in snapshots:
            conn.execute(
                """
                INSERT INTO topology_evidence_snapshots(
                    conclusion_ref, conclusion_type, fingerprint, captured_at, bundle_json
                ) VALUES (%s, %s, %s, %s::timestamptz, %s::jsonb)
                """,
                (conclusion_ref, conclusion_type, fingerprint, captured_at, bundle_json),
            )

        incidents = (
            (
                "topology_edge_reversal",
                "high",
                "2026-09-10 10:20:00+00",
                "2026-09-10 10:30:00+00",
            ),
            (
                "topology_churn",
                "warning",
                "2026-09-10 11:20:00+00",
                "2026-09-10 11:30:00+00",
            ),
            (
                "delay_spike",
                "warning",
                "2026-09-10 10:25:00+00",
                "2026-09-10 10:35:00+00",
            ),
        )
        for kind, severity, started_at, resolved_at in incidents:
            conn.execute(
                """
                INSERT INTO propagation_incidents(
                    server_id, kind, severity, started_at, updated_at, resolved_at, "window"
                ) VALUES (
                    %s, %s, %s, %s::timestamptz, %s::timestamptz,
                    %s::timestamptz, '1h'
                )
                """,
                (server_id, kind, severity, started_at, resolved_at, resolved_at),
            )
        conn.commit()

        start = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
        end = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
        results = rebuild_topology_rollup_chain(conn, start=start, end=end)
        assert [r.summary_rows_written for r in results] == [2, 1, 1]

        daily = conn.execute(
            """
            SELECT snapshot_count, conclusion_count, incident_started_count
            FROM topology_rollups
            WHERE resolution = 'day'
            """
        ).fetchone()
        assert daily["snapshot_count"] == 3
        assert daily["conclusion_count"] == 2
        assert daily["incident_started_count"] == 2

        values = {
            (row["kind"], row["value"]): row["occurrence_count"]
            for row in conn.execute(
                """
                SELECT kind, value, occurrence_count
                FROM topology_value_rollups
                WHERE resolution = 'day'
                """
            ).fetchall()
        }
        assert values[("conclusion_type", "risk")] == 2
        assert values[("conclusion_type", "community")] == 1
        assert values[("evidence_level", "high")] == 1
        assert values[("evidence_level", "limited")] == 1
        assert values[("evidence_level", "low")] == 1
        assert values[("risk_level", "moderate")] == 1
        assert values[("risk_level", "high")] == 1
        assert values[("risk_level", "critical")] == 1
        assert values[("incident_kind", "topology_edge_reversal")] == 1
        assert values[("incident_kind", "topology_churn")] == 1
        assert values[("incident_severity", "high")] == 1
        assert values[("incident_severity", "warning")] == 1
        assert ("incident_kind", "delay_spike") not in values

        again = rebuild_topology_rollup_chain(conn, start=start, end=end)
        assert [r.summary_rows_written for r in again] == [2, 1, 1]
        count = conn.execute("SELECT COUNT(*) AS count FROM topology_rollups").fetchone()["count"]
        assert count == 4
        conn.rollback()

    print(
        "Topology rollup qualification PASS: persisted evidence snapshots, risk/evidence "
        "dimensions, topology incidents, hour/day/month and idempotent rebuild"
    )


if __name__ == "__main__":
    main()
