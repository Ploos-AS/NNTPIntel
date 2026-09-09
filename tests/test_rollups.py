from datetime import UTC, datetime

import pytest

from nntpintel.rollups import rebuild_server_observation_rollups


class FakeResult:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.committed = False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        if "INSERT INTO server_observation_rollups" in sql:
            return FakeResult(rowcount=3)
        return FakeResult()

    def commit(self):
        self.committed = True


def test_rollup_rejects_invalid_resolution_and_bounds():
    conn = FakeConnection()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 10, tzinfo=UTC)

    with pytest.raises(ValueError, match="resolution"):
        rebuild_server_observation_rollups(
            conn, resolution="month", start=start, end=end
        )
    with pytest.raises(ValueError, match="after start"):
        rebuild_server_observation_rollups(
            conn, resolution="hour", start=end, end=start
        )
    naive_start = start.replace(tzinfo=None)
    naive_end = end.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        rebuild_server_observation_rollups(
            conn,
            resolution="hour",
            start=naive_start,
            end=naive_end,
        )


def test_rollup_rebuild_is_bounded_and_idempotent_by_replace():
    conn = FakeConnection()
    start = datetime(2026, 9, 9, tzinfo=UTC)
    end = datetime(2026, 9, 10, tzinfo=UTC)

    result = rebuild_server_observation_rollups(
        conn, resolution="hour", start=start, end=end
    )

    assert result.rows_written == 3
    assert result.resolution == "hour"
    assert conn.committed is True
    assert len(conn.calls) == 2

    delete_sql, delete_params = conn.calls[0]
    insert_sql, insert_params = conn.calls[1]
    assert delete_sql.startswith("DELETE FROM server_observation_rollups")
    assert delete_params == ("hour", start, end)
    assert insert_sql.startswith("WITH scoped AS")
    assert "INSERT INTO server_observation_rollups" in insert_sql
    assert "FROM observations o JOIN endpoints e" in insert_sql
    assert "o.observed_at >= %s" in insert_sql
    assert "o.observed_at < %s" in insert_sql
    assert "GROUP BY server_id, bucket_start" in insert_sql
    assert insert_params == ("hour", start, end, "hour")
