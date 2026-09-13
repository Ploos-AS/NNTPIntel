from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from nntpintel.statistics import (
    group_statistics,
    parse_statistics_time,
    protocol_statistics,
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


class _SequenceConnection:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.calls.append((query, params))
        return _Cursor(self.result_sets.pop(0))


class _SequenceStorage:
    backend_name = "postgresql"

    def __init__(self, result_sets):
        self.connection = _SequenceConnection(result_sets)

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


def test_group_statistics_queries_summary_and_value_rollups():
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
    summary = {
        "server_id": 7,
        "host": "news.example.net",
        "bucket_start": start,
        "inventory_count": 31,
        "snapshot_count": 1200,
        "observed_group_count": 840,
        "observed_hierarchy_count": 17,
        "event_count": 9,
        "generated_at": end,
    }
    value = {
        "server_id": 7,
        "host": "news.example.net",
        "bucket_start": start,
        "kind": "event_type",
        "value": "added",
        "occurrence_count": 5,
        "generated_at": end,
    }
    storage = _SequenceStorage([[summary], [value]])

    result = group_statistics(
        storage,
        resolution="day",
        start=start,
        end=end,
        server_id=7,
    )

    assert result["metric_family"] == "group_hierarchy_inventory_changes"
    assert result["source"] == ["server_group_rollups", "server_group_value_rollups"]
    assert result["rows"][0]["observed_group_count"] == 840
    assert result["rows"][0]["observed_hierarchy_count"] == 17
    assert result["values"][0]["value"] == "added"
    assert result["rows"][0]["bucket_start"] == "2026-01-01T00:00:00Z"
    assert len(storage.connection.calls) == 2
    assert "server_group_rollups" in storage.connection.calls[0][0]
    assert "server_group_value_rollups" in storage.connection.calls[1][0]
    assert storage.connection.calls[0][1] == ("day", start, end, 7)
    assert storage.connection.calls[1][1] == ("day", start, end, 7)
    assert "group_snapshots" not in storage.connection.calls[0][0]
    assert "group_events" not in storage.connection.calls[1][0]


def test_protocol_statistics_queries_summary_and_value_rollups():
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
    summary = {
        "server_id": 7,
        "host": "news.example.net",
        "bucket_start": start,
        "observation_count": 20,
        "tls_enabled_count": 18,
        "tls_ratio": Decimal("0.9"),
        "capabilities_observed_count": 19,
        "capability_entry_count": 125,
        "generated_at": end,
    }
    values = [
        {
            "server_id": 7,
            "host": "news.example.net",
            "bucket_start": start,
            "kind": "tls_protocol",
            "value": "TLSv1.3",
            "occurrence_count": 17,
            "generated_at": end,
        },
        {
            "server_id": 7,
            "host": "news.example.net",
            "bucket_start": start,
            "kind": "capability",
            "value": "STARTTLS",
            "occurrence_count": 19,
            "generated_at": end,
        },
    ]
    storage = _SequenceStorage([[summary], values])

    result = protocol_statistics(
        storage,
        resolution="day",
        start=start,
        end=end,
        server_id=7,
    )

    assert result["metric_family"] == "protocol_tls_capabilities"
    assert result["source"] == ["server_protocol_rollups", "server_protocol_value_rollups"]
    assert result["rows"][0]["tls_ratio"] == pytest.approx(0.9)
    assert result["values"][0]["kind"] == "tls_protocol"
    assert result["values"][1]["value"] == "STARTTLS"
    assert len(storage.connection.calls) == 2
    assert "server_protocol_rollups" in storage.connection.calls[0][0]
    assert "server_protocol_value_rollups" in storage.connection.calls[1][0]
    assert storage.connection.calls[0][1] == ("day", start, end, 7)
    assert storage.connection.calls[1][1] == ("day", start, end, 7)
    assert "observations" not in storage.connection.calls[0][0]
    assert "observations" not in storage.connection.calls[1][0]


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


def test_group_statistics_rejects_legacy_sqlite_storage():
    class LegacyStorage:
        pass

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        group_statistics(LegacyStorage(), resolution="day")


def test_protocol_statistics_rejects_legacy_sqlite_storage():
    class LegacyStorage:
        pass

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        protocol_statistics(LegacyStorage(), resolution="day")
