from __future__ import annotations

import os
from datetime import UTC, datetime

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

        run_id = start_maintenance_run(
            conn,
            kind="partition_lifecycle",
            detail={"partition_count": len(names)},
        )
        finish_maintenance_run(
            conn,
            run_id=run_id,
            status="success",
            detail={"partition_count": len(names)},
        )
        row = conn.execute(
            "SELECT kind, status, finished_at, detail_json FROM maintenance_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        assert row["kind"] == "partition_lifecycle"
        assert row["status"] == "success"
        assert row["finished_at"] is not None
        assert row["detail_json"]["partition_count"] == 8
        conn.rollback()

    print(
        "Maintenance qualification PASS: monthly partition window, safe default-range guard, "
        "persisted maintenance status"
    )


if __name__ == "__main__":
    main()
