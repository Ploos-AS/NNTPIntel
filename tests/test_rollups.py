from datetime import datetime, timezone

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
        if sql.lstrip().startswith("INSERT INTO server_observation_rollups"):
            return FakeResult(rowcount=3)
        return FakeResult()

    def commit(self):
        self.committed = True


def test_rollup_rejects_invalid_resolution_and_bounds():
    conn = FakeConnection()
    start = datetime(2026, 9, 9, tzinfo=timezone.utc)
    end = datetime(2026, 9, 10, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="resolution"):
        rebuild_server_observation_rollups(
            conn, resolution="month", start=start, end=end
        )
    with pytest.raises(ValueError, match="after start"):
        rebuild_server_observation_rollups(
            conn, resolution="hour", start=end, end=start
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        rebuild_server_observation_rollups(
            conn,
            resolution="hour",
            start=datetime(2026, 9, 9),
            end=datetime(2026, 9, 10),
        )


def test_rollup_rebuild_is_bounded_and_idempotent_by_replace():
    conn = FakeConnection()
    start = datetime(2026, 9, 9, tzinfo=timezone.utc)
    end = datetime(2026, 9, 10, tzinfo=timezone.utc)

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
    assert insert_sql.startswith("INSERT INTO server_observation_rollups")
    assert "FROM observations o JOIN endpoints e" in insert_sql
    assert "o.observed_at >= %s" in insert_sql
    assert "o.observed_at < %s" in insert_sql
    assert insert_params == ("hour", "hour", start, end, "hour")
