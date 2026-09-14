from __future__ import annotations

import threading
from urllib.request import urlopen

from nntpintel.group_history_web import group_history_page
from nntpintel.statistics_http import make_statistics_server


class _Storage:
    backend_name = "postgresql"


def test_group_history_page_renders_inventory_and_filtered_values(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.group_history_web.group_statistics",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "inventory_count": 1,
                    "snapshot_count": 2,
                    "observed_group_count": 3,
                    "observed_hierarchy_count": 1,
                    "event_count": 4,
                }
            ],
            "values": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "kind": "hierarchy",
                    "value": "comp",
                    "occurrence_count": 3,
                },
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "kind": "newsgroup",
                    "value": "comp.lang.python",
                    "occurrence_count": 2,
                },
            ],
        },
    )
    html = group_history_page(
        _Storage(),
        7,
        resolution="day",
        preset="30d",
        kind="hierarchy",
        value="comp",
    )
    assert "news.example" in html
    assert "Inventory history" in html
    assert "Hierarchy / group values" in html
    assert "comp" in html
    assert "comp.lang.python" not in html
    assert "server_id=7" in html


def test_statistics_http_serves_group_history(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_http.group_history_page",
        lambda storage, server_id, **kwargs: f"<html>groups {server_id}</html>",
    )
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        url = (
            f"http://{host}:{port}/web/statistics/server/7/groups"
            "?resolution=day&preset=30d&kind=hierarchy&value=comp"
        )
        with urlopen(url, timeout=2) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert "groups 7" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
