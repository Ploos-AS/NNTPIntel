from __future__ import annotations

import os
from datetime import UTC, datetime

from nntpintel.maintenance_cli import main as maintenance_main
from nntpintel.storage_backend import PostgresStorage


def _run_count(storage: PostgresStorage) -> int:
    with storage.connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS count FROM maintenance_runs").fetchone()["count"])


def main() -> None:
    database_url = os.environ["NNTPINTEL_DATABASE_URL"]
    storage = PostgresStorage(database_url)
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    before = _run_count(storage)

    assert maintenance_main(["--database-url", database_url, "status"], now=now) == 0
    assert maintenance_main(["--database-url", database_url, "plan"], now=now) == 0
    assert maintenance_main(
        ["--database-url", database_url, "apply", "--batch-size", "10"],
        now=now,
    ) == 0
    assert maintenance_main(
        [
            "--database-url",
            database_url,
            "retire-partition",
            "observations",
            "2026-04",
        ],
        now=now,
    ) == 0

    after_read_only = _run_count(storage)
    assert after_read_only == before, (before, after_read_only)

    assert maintenance_main(
        ["--database-url", database_url, "ensure-partitions", "--months-ahead", "1"],
        now=now,
    ) == 0

    after_ensure = _run_count(storage)
    assert after_ensure == before + 1, (before, after_ensure)

    with storage.connect() as conn:
        row = conn.execute(
            """
            SELECT kind, status, detail_json
            FROM maintenance_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        assert row["kind"] == "partition_lifecycle"
        assert row["status"] == "success"
        assert row["detail_json"]["months_ahead"] == 1
        assert len(row["detail_json"]["partitions"]) == 8

    print(
        "Maintenance CLI qualification PASS: status/plan/dry-run are read-only, "
        "destructive commands require --yes, partition ensure is persisted"
    )


if __name__ == "__main__":
    main()
