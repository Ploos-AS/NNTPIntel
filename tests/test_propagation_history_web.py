from __future__ import annotations

import threading
from urllib.request import urlopen

import pytest

from nntpintel.propagation_history_web import propagation_history_page
from nntpintel.statistics_http import make_statistics_server


class _Storage:
    backend_name = "postgresql"


def test_propagation_history_page_renders_trends(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.propagation_history_web.propagation_statistics",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "probe_count": 10,
                    "present_count": 8,
                    "absent_count": 1,
                    "unknown_count": 1,
                    "presence_ratio": 0.8,
                    "article_count": 4,
                    "first_seen_delay_avg_seconds": 12.5,
                    "incident_started_count": 2,
                }
            ],
            "values": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "kind": "incident_kind",
                    "value": "propagation_gap",
                    "occurrence_count": 2,
                }
            ],
            "campaigns": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "created_count": 3,
                    "completed_count": 2,
                    "expired_or_closed_count": 1,
                }
            ],
        },
    )
    html = propagation_history_page(_Storage(), 7, resolution="day", preset="30d")
    assert "news.example" in html
    assert "Avg presence ratio" in html
    assert "0.800" in html
    assert "Incidents started" in html
    assert "propagation_gap" in html
    assert "Global campaign trend" in html
    assert "/web/statistics/server/7/propagation" in html


def test_propagation_history_page_filters_values(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.propagation_history_web.propagation_statistics",
        lambda *args, **kwargs: {
            "rows": [],
            "values": [
                {"kind": "incident_kind", "value": "propagation_gap", "occurrence_count": 2},
                {"kind": "state", "value": "present", "occurrence_count": 3},
            ],
            "campaigns": [],
        },
    )
    html = propagation_history_page(
        _Storage(), 7, kind="incident_kind", value="propagation_gap"
    )
    assert "propagation_gap" in html
    assert ">present<" not in html
    assert "Filtered values" in html


def test_propagation_history_page_rejects_invalid_server_id():
    with pytest.raises(ValueError, match="server_id must be a positive integer"):
        propagation_history_page(_Storage(), 0)


def test_statistics_http_serves_propagation_history(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_http.propagation_history_page",
        lambda storage, server_id, **kwargs: f"<html>propagation {server_id} history</html>",
    )
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(
            f"http://{host}:{port}/web/statistics/server/7/propagation?resolution=day&preset=30d",
            timeout=2,
        ) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert "propagation 7 history" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
