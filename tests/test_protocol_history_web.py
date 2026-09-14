from __future__ import annotations

import threading
from urllib.request import urlopen

import pytest

from nntpintel.protocol_history_web import protocol_history_page
from nntpintel.statistics_http import make_statistics_server


class _Storage:
    backend_name = "postgresql"


def test_protocol_history_page_renders_tls_and_capabilities(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.protocol_history_web.protocol_statistics",
        lambda *args, **kwargs: {
            "rows": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "observation_count": 10,
                    "tls_enabled_count": 9,
                    "tls_ratio": 0.9,
                    "capabilities_observed_count": 10,
                    "capability_entry_count": 42,
                }
            ],
            "values": [
                {
                    "bucket_start": "2026-09-15T00:00:00Z",
                    "server_id": 7,
                    "host": "news.example",
                    "kind": "capability",
                    "value": "STARTTLS",
                    "occurrence_count": 10,
                }
            ],
        },
    )
    html = protocol_history_page(_Storage(), 7, resolution="day", preset="30d")
    assert "news.example" in html
    assert "Avg TLS ratio" in html
    assert "0.900" in html
    assert "Capability entries" in html
    assert "STARTTLS" in html
    assert "/web/statistics/server/7/protocol" in html


def test_protocol_history_page_filters_values(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.protocol_history_web.protocol_statistics",
        lambda *args, **kwargs: {
            "rows": [],
            "values": [
                {"kind": "capability", "value": "STARTTLS", "occurrence_count": 2},
                {"kind": "capability", "value": "OVER", "occurrence_count": 3},
            ],
        },
    )
    html = protocol_history_page(_Storage(), 7, kind="capability", value="STARTTLS")
    assert "STARTTLS" in html
    assert "OVER" not in html
    assert "Filtered values" in html


def test_protocol_history_page_rejects_invalid_server_id():
    with pytest.raises(ValueError, match="server_id must be a positive integer"):
        protocol_history_page(_Storage(), 0)


def test_statistics_http_serves_protocol_history(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.statistics_http.protocol_history_page",
        lambda storage, server_id, **kwargs: f"<html>protocol {server_id} history</html>",
    )
    server = make_statistics_server(_Storage(), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(
            f"http://{host}:{port}/web/statistics/server/7/protocol?resolution=day&preset=30d",
            timeout=2,
        ) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            assert "protocol 7 history" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
