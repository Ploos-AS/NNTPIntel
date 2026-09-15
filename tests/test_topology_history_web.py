from __future__ import annotations

import threading
from urllib.request import urlopen

from nntpintel.statistics_http import make_statistics_server
from nntpintel.topology_history_web import topology_history_page


class _Storage:
    backend_name = "postgresql"


def test_topology_history_page_renders_global_trends(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.topology_history_web.topology_statistics",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "snapshot_count": 4,
                    "conclusion_count": 7,
                    "incident_started_count": 2,
                }
            ],
            "values": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "kind": "risk_level",
                    "value": "high",
                    "occurrence_count": 2,
                },
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "kind": "conclusion_type",
                    "value": "peer",
                    "occurrence_count": 3,
                },
            ],
        },
    )
    html = topology_history_page(_Storage(), resolution="day", preset="30d")
    assert "Global inferred topology history" in html
    assert "Topology snapshots" in html
    assert "Conclusions" in html
    assert "Incidents started" in html
    assert "risk_level" in html
    assert "high" in html
    assert "/api/v1/statistics/topology?resolution=day" in html


def test_topology_history_page_filters_values(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.topology_history_web.topology_statistics",
        lambda *args, **kwargs: {
            "rows": [],
            "values": [
                {"kind": "risk_level", "value": "high", "occurrence_count": 2},
                {"kind": "risk_level", "value": "low", "occurrence_count": 5},
            ],
        },
    )
    html = topology_history_page(_Storage(), kind="risk_level", value="high")
    assert ">high<" in html
    assert ">low<" not in html
    assert "Filtered values" in html


def test_statistics_http_serves_topology_history(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_http.topology_history_page",
        lambda storage, **kwargs: "<html>global topology history</html>",
    )
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(
            f"http://{host}:{port}/web/statistics/topology?resolution=day&preset=30d",
            timeout=2,
        ) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert "global topology history" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
