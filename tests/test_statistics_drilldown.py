from __future__ import annotations

import datetime
import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from nntpintel.statistics_drilldown import server_observation_drilldown
from nntpintel.statistics_http import make_statistics_server


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

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params
        return _Cursor(self.rows)


class _Storage:
    backend_name = "postgresql"

    def __init__(self, rows=()):
        self.connection = _Connection(list(rows))

    def connect(self):
        return self.connection


def _window(hours=1):
    start = datetime.datetime(2026, 9, 15, 8, tzinfo=datetime.UTC)
    return start, start + datetime.timedelta(hours=hours)


def test_drilldown_queries_raw_observations_with_server_and_bounds():
    start, end = _window()
    storage = _Storage([{"id": 1, "observed_at": start, "success": True}])
    payload = server_observation_drilldown(
        storage, server_id=7, start=start, end=end, limit=25
    )
    assert payload["source"] == "observations"
    assert payload["server_id"] == 7
    assert payload["limit"] == 25
    assert payload["rows"][0]["observed_at"] == "2026-09-15T08:00:00Z"
    assert "FROM observations o" in storage.connection.query
    assert "server_observation_rollups" not in storage.connection.query
    assert storage.connection.params == (7, start, end, 25)


def test_drilldown_rejects_wide_windows_and_large_limits():
    start, end = _window(25)
    with pytest.raises(ValueError, match="must not exceed 24 hours"):
        server_observation_drilldown(_Storage(), server_id=1, start=start, end=end)
    start, end = _window()
    with pytest.raises(ValueError, match="between 1 and 500"):
        server_observation_drilldown(
            _Storage(), server_id=1, start=start, end=end, limit=501
        )


def test_drilldown_http_requires_explicit_range():
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with pytest.raises(HTTPError) as exc_info:
            urlopen(
                f"http://{host}:{port}/api/v1/statistics/server/7/observations",
                timeout=2,
            )
        assert exc_info.value.code == 400
        payload = json.loads(exc_info.value.read())
        assert "start and end are required" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_drilldown_http_serves_bounded_rows():
    start, _ = _window()
    storage = _Storage([{"id": 9, "observed_at": start, "success": True}])
    server = make_statistics_server(storage, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        url = (
            f"http://{host}:{port}/api/v1/statistics/server/7/observations"
            "?start=2026-09-15T08:00:00Z&end=2026-09-15T09:00:00Z&limit=10"
        )
        with urlopen(url, timeout=2) as response:
            payload = json.loads(response.read())
        assert payload["source"] == "observations"
        assert payload["rows"][0]["id"] == 9
        assert storage.connection.params[-1] == 10
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
