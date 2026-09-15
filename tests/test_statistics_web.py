from __future__ import annotations

import datetime
import threading
from urllib.request import urlopen

import pytest

from nntpintel.statistics_http import make_statistics_server
from nntpintel.statistics_web import historical_statistics_page, resolve_preset, server_history_page


class _Storage:
    backend_name = "postgresql"


def _payloads():
    return (
        {"rows": [{"bucket_start": "2026-09-15T00:00:00Z", "server_id": 1, "inventory_count": 4, "observed_group_count": 3, "observed_hierarchy_count": 1, "event_count": 2}], "values": []},
        {"rows": [{"bucket_start": "2026-09-15T00:00:00Z", "server_id": 1, "observation_count": 4, "tls_enabled_count": 3, "tls_ratio": 0.75, "capability_entry_count": 8}], "values": []},
        {"rows": [{"bucket_start": "2026-09-15T00:00:00Z", "server_id": 1, "probe_count": 4, "present_count": 3, "absent_count": 1, "presence_ratio": 0.75, "incident_started_count": 1}], "values": [], "campaigns": [{"bucket_start": "2026-09-15T00:00:00Z", "created_count": 1, "completed_count": 1, "expired_or_closed_count": 0}]},
        {"rows": [{"bucket_start": "2026-09-15T00:00:00Z", "snapshot_count": 2, "conclusion_count": 1, "incident_started_count": 0}], "values": []},
    )


def test_resolve_preset_uses_utc_bounded_ranges():
    start, end = resolve_preset("24h", "hour")
    assert end is not None and start is not None
    assert end.tzinfo == datetime.UTC
    assert end - start == datetime.timedelta(days=1)


def test_resolve_preset_all_time_is_unbounded():
    assert resolve_preset("all-time", "month") == (None, None)


def test_resolve_preset_rejects_unknown():
    with pytest.raises(ValueError, match="unknown statistics range preset"):
        resolve_preset("90d", "day")


def test_historical_statistics_page_renders_rollup_sections(monkeypatch):
    payloads = iter(_payloads())
    monkeypatch.setattr("nntpintel.statistics_web.group_statistics", lambda *a, **k: next(payloads))
    monkeypatch.setattr("nntpintel.statistics_web.protocol_statistics", lambda *a, **k: next(payloads))
    monkeypatch.setattr("nntpintel.statistics_web.propagation_statistics", lambda *a, **k: next(payloads))
    monkeypatch.setattr("nntpintel.statistics_web.topology_statistics", lambda *a, **k: next(payloads))
    html = historical_statistics_page(_Storage(), resolution="day", preset="30d")
    assert "Historical overview" in html
    assert "Group / hierarchy rollups" in html
    assert "Protocol / TLS rollups" in html
    assert "Propagation campaigns" in html
    assert "Inferred topology rollups" in html
    assert "TLS ratio trend" in html
    assert "Propagation presence trend" in html
    assert "Topology incident trend" in html
    assert '<polyline class="series"' in html
    assert "preset=24h" in html


def test_historical_statistics_page_passes_bounded_range(monkeypatch):
    captured = []
    payloads = iter(_payloads())

    def capture(function):
        def wrapped(storage, **kwargs):
            captured.append(kwargs)
            return next(payloads)
        return wrapped

    monkeypatch.setattr("nntpintel.statistics_web.group_statistics", capture("group"))
    monkeypatch.setattr("nntpintel.statistics_web.protocol_statistics", capture("protocol"))
    monkeypatch.setattr("nntpintel.statistics_web.propagation_statistics", capture("propagation"))
    monkeypatch.setattr("nntpintel.statistics_web.topology_statistics", capture("topology"))
    historical_statistics_page(_Storage(), resolution="hour", preset="7d")
    assert len(captured) == 4
    assert all(item["resolution"] == "hour" for item in captured)
    assert all(item["start"] is not None and item["end"] is not None for item in captured)


def test_server_history_page_renders_server_metrics(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_web.server_statistics",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "observation_count": 10,
                    "success_count": 9,
                    "failure_count": 1,
                    "availability_ratio": 0.9,
                    "connect_ms_count": 9,
                    "connect_ms_avg": 120.0,
                    "connect_ms_min": 90.0,
                    "connect_ms_max": 180.0,
                }
            ]
        },
    )
    html = server_history_page(_Storage(), 7, resolution="hour", preset="24h")
    assert "news.example" in html
    assert "Avg availability" in html
    assert "0.900" in html
    assert "120.0" in html
    assert "Availability trend" in html
    assert "Connection latency trend" in html
    assert '<polyline class="series"' in html
    assert "/web/statistics/server/7" in html


def test_server_history_page_rejects_invalid_server_id():
    with pytest.raises(ValueError, match="server_id must be a positive integer"):
        server_history_page(_Storage(), 0)


def test_statistics_http_serves_historical_page(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_http.historical_statistics_page",
        lambda storage, **kwargs: "<html>historical statistics</html>",
    )
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/web/statistics?resolution=day&preset=7d", timeout=2) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert "historical statistics" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_statistics_http_serves_server_history(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_http.server_history_page",
        lambda storage, server_id, **kwargs: f"<html>server {server_id} history</html>",
    )
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/web/statistics/server/7?resolution=hour&preset=7d", timeout=2) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert "server 7 history" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
