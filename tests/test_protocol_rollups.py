from datetime import UTC, datetime

import pytest

from nntpintel.protocol_rollups import rebuild_server_protocol_rollups


class FakeResult:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.committed = False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if "INSERT INTO server_protocol_rollups" in sql:
            return FakeResult(2)
        if "INSERT INTO server_protocol_value_rollups" in sql:
            return FakeResult(6)
        return FakeResult()

    def commit(self):
        self.committed = True


def test_protocol_rollup_rejects_bad_resolution_and_bounds():
    conn = FakeConnection()
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 10, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="resolution"):
        rebuild_server_protocol_rollups(conn, resolution="year", start=start, end=end)
    with pytest.raises(ValueError, match="after start"):
        rebuild_server_protocol_rollups(conn, resolution="month", start=end, end=start)


def test_protocol_rollup_is_normalized_and_bucket_rebuildable():
    conn = FakeConnection()
    start = datetime(2026, 9, 9, 20, 15, tzinfo=UTC)
    end = datetime(2026, 9, 9, 22, 15, tzinfo=UTC)
    result = rebuild_server_protocol_rollups(
        conn, resolution="hour", start=start, end=end
    )
    assert result.summary_rows_written == 2
    assert result.value_rows_written == 6
    assert conn.committed is True

    delete_values, delete_summary, summary_insert, value_insert = conn.calls
    assert delete_values[0].startswith("DELETE FROM server_protocol_value_rollups")
    assert delete_summary[0].startswith("DELETE FROM server_protocol_rollups")
    assert delete_values[1][1].minute == 0
    assert delete_values[1][2].hour == 23
    assert "jsonb_array_elements_text" in value_insert[0]
    assert "upper(split_part(trim(cap.value), ' ', 1))" in value_insert[0]
    assert "tls_protocol" in value_insert[0]
    assert "tls_cipher" in value_insert[0]
    assert summary_insert[1] == ("hour", start, end, "hour")
