import json
import threading
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from nntpintel.api import make_server
from nntpintel.statistics_api import (
    group_statistics_request,
    propagation_statistics_request,
    protocol_statistics_request,
    server_statistics_request,
    topology_statistics_request,
)
from nntpintel.storage import Storage


def test_statistics_request_parses_public_query(monkeypatch):
    captured = {}
    def fake_server_statistics(storage, **kwargs):
        captured["storage"] = storage; captured.update(kwargs); return {"rows": []}
    monkeypatch.setattr("nntpintel.statistics_api.server_statistics", fake_server_statistics)
    storage = object()
    result = server_statistics_request(storage, {"resolution": ["day"], "start": ["2026-01-01T00:00:00Z"], "end": ["2026-02-01T00:00:00+00:00"], "server_id": ["7"]})
    assert result == {"rows": []}
    assert captured == {"storage": storage, "resolution": "day", "start": datetime(2026, 1, 1, tzinfo=UTC), "end": datetime(2026, 2, 1, tzinfo=UTC), "server_id": 7}


def test_group_statistics_request_parses_public_query(monkeypatch):
    captured = {}
    def fake_group_statistics(storage, **kwargs):
        captured["storage"] = storage; captured.update(kwargs); return {"rows": [], "values": []}
    monkeypatch.setattr("nntpintel.statistics_api.group_statistics", fake_group_statistics)
    storage = object()
    result = group_statistics_request(storage, {"resolution": ["month"], "start": ["2026-01-01T00:00:00Z"], "end": ["2026-07-01T00:00:00Z"], "server_id": ["11"]})
    assert result == {"rows": [], "values": []}
    assert captured["server_id"] == 11


def test_protocol_statistics_request_parses_public_query(monkeypatch):
    captured = {}
    def fake_protocol_statistics(storage, **kwargs):
        captured["storage"] = storage; captured.update(kwargs); return {"rows": [], "values": []}
    monkeypatch.setattr("nntpintel.statistics_api.protocol_statistics", fake_protocol_statistics)
    storage = object()
    result = protocol_statistics_request(storage, {"resolution": ["hour"], "start": ["2026-09-01T00:00:00Z"], "end": ["2026-09-02T00:00:00Z"], "server_id": ["3"]})
    assert result == {"rows": [], "values": []}
    assert captured["server_id"] == 3


def test_propagation_statistics_request_parses_public_query(monkeypatch):
    captured = {}
    def fake_propagation_statistics(storage, **kwargs):
        captured["storage"] = storage; captured.update(kwargs); return {"rows": [], "values": [], "campaigns": []}
    monkeypatch.setattr("nntpintel.statistics_api.propagation_statistics", fake_propagation_statistics)
    storage = object()
    result = propagation_statistics_request(storage, {"resolution": ["day"], "start": ["2026-09-01T00:00:00Z"], "end": ["2026-09-08T00:00:00Z"], "server_id": ["5"]})
    assert result == {"rows": [], "values": [], "campaigns": []}
    assert captured == {"storage": storage, "resolution": "day", "start": datetime(2026, 9, 1, tzinfo=UTC), "end": datetime(2026, 9, 8, tzinfo=UTC), "server_id": 5}


def test_topology_statistics_request_parses_global_query(monkeypatch):
    captured = {}
    def fake_topology_statistics(storage, **kwargs):
        captured["storage"] = storage; captured.update(kwargs); return {"rows": [], "values": []}
    monkeypatch.setattr("nntpintel.statistics_api.topology_statistics", fake_topology_statistics)
    storage = object()
    result = topology_statistics_request(storage, {"resolution": ["month"], "start": ["2026-01-01T00:00:00Z"], "end": ["2026-07-01T00:00:00Z"]})
    assert result == {"rows": [], "values": []}
    assert captured == {"storage": storage, "resolution": "month", "start": datetime(2026, 1, 1, tzinfo=UTC), "end": datetime(2026, 7, 1, tzinfo=UTC)}


def test_topology_statistics_request_rejects_server_filter():
    with pytest.raises(ValueError, match="not supported"):
        topology_statistics_request(object(), {"resolution": ["day"], "server_id": ["7"]})


@pytest.mark.parametrize(("params", "message"), [({}, "resolution is required"), ({"resolution": ["day", "month"]}, "resolution must be specified once"), ({"resolution": ["day"], "server_id": ["x"]}, "server_id must be a positive integer"), ({"resolution": ["day"], "server_id": ["0"]}, "server_id must be a positive integer")])
def test_statistics_request_rejects_invalid_public_query(params, message):
    for request in (server_statistics_request, group_statistics_request, protocol_statistics_request, propagation_statistics_request):
        with pytest.raises(ValueError, match=message):
            request(object(), params)


def _error_json(url: str) -> tuple[int, dict]:
    try:
        urlopen(url, timeout=2)
    except HTTPError as exc:
        return exc.code, json.load(exc)
    raise AssertionError("expected HTTP error")


def test_statistics_http_validation_and_backend_status(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bases = (
        f"http://{host}:{port}/api/v1/statistics/servers",
        f"http://{host}:{port}/api/v1/statistics/groups",
        f"http://{host}:{port}/api/v1/statistics/protocol",
        f"http://{host}:{port}/api/v1/statistics/propagation",
    )
    try:
        for base in bases:
            status, payload = _error_json(base)
            assert status == 400
            assert payload == {"error": "resolution is required"}
            status, payload = _error_json(f"{base}?resolution=day&server_id=nope")
            assert status == 400
            assert payload == {"error": "server_id must be a positive integer"}
            status, payload = _error_json(f"{base}?resolution=day")
            assert status == 503
            assert "PostgreSQL" in payload["error"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_topology_statistics_http_contract(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}/api/v1/statistics/topology"
    try:
        status, payload = _error_json(base)
        assert status == 400
        assert payload == {"error": "resolution is required"}
        status, payload = _error_json(f"{base}?resolution=day&server_id=7")
        assert status == 400
        assert "not supported" in payload["error"]
        status, payload = _error_json(f"{base}?resolution=day")
        assert status == 503
        assert "PostgreSQL" in payload["error"]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
