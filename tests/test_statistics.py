from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from nntpintel.statistics import (
    parse_statistics_time,
    server_statistics,
    validate_statistics_range,
)


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params
        return _Cursor(self.rows)


class _Storage:
    backend_name = "postgresql"

    def __init__(self, rows):
        self.connection = _Connection(rows)

    def connect(self):
        return self.connection


def test_parse_statistics_time_normalizes_to_utc():
    parsed = parse_statistics_time("2026-09-12T21:30:00+02:00")
    assert parsed == datetime.datetime(2026, 9, 12, 19, 30, tzinfo=datetime.UTC)


def test_statistics_range_requires_complete_bounded_window():
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    with pytest.raises(ValueError, match="supplied together"):
        validate_statistics_range(resolution="day", start=start)


def test_server_statistics_queries_rollups_for_bounded_range():
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
    row = {
        "server_id": 7,
        "host": "news.example.net",
        "bucket_start": start,
        "observation_count": 12,
        "success_count": 11,
        "failure_count": 1,
        "availability_ratio": Decimal("0.9166666667"),
        "connect_ms_count": 12,
        "connect_ms_avg": Decimal("42.0"),
        "connect_ms_min": Decimal("30.0"),
        "connect_ms_max": Decimal("70.0"),
        "generated_at": end,
    }
    storage = _Storage([row])

    result = server_statistics(
        storage,
        resolution="day",
        start=start,
        end=end,
        server_id=7,
    )

    assert result["source"] == "server_observation_rollups"
    assert result["range"] == {
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-02-01T00:00:00Z",
        "all_time": False,
    }
    assert result["rows"][0]["bucket_start"] == "2026-01-01T00:00:00Z"
    assert result["rows"][0]["generated_at"] == "2026-02-01T00:00:00Z"
    assert result["rows"][0]["availability_ratio"] == pytest.approx(0.9166666667)
    assert result["rows"][0]["connect_ms_avg"] == 42.0
    assert "server_observation_rollups" in storage.connection.query
    assert "observations" not in storage.connection.query.replace("server_observation_rollups", "")
    assert storage.connection.params == ("day", start, end, 7)


def test_server_statistics_all_time_uses_rollups_without_raw_time_bounds():
    storage = _Storage([])
    result = server_statistics(storage, resolution="month")

    assert result["range"] == {"start": None, "end": None, "all_time": True}
    assert storage.connection.params == ("month",)
    assert "bucket_start >=" not in storage.connection.query


def test_server_statistics_rejects_sqlite_backend():
    class SQLiteLike:
        backend_name = "sqlite"

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        server_statistics(SQLiteLike(), resolution="day")
