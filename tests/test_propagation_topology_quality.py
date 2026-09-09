import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation import record_presence
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_topology_quality import topology_data_quality
from nntpintel.storage import Storage


def test_topology_data_quality_reports_coverage_freshness_and_confidence(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = storage.ensure_endpoint("a.example.test")
    second = storage.ensure_endpoint("b.example.test")
    start = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    for index in range(3):
        message_id = f"<quality-{index}@example.test>"
        create_campaign(storage, message_id, [first, second], now=start)
        observed = start + timedelta(minutes=index)
        record_presence(
            storage,
            message_id,
            first,
            observed_at=observed.isoformat(),
            present=True,
            response_code=223,
        )
        record_presence(
            storage,
            message_id,
            second,
            observed_at=(observed + timedelta(seconds=10)).isoformat(),
            present=True,
            response_code=223,
        )

    result = topology_data_quality(storage, now=datetime(2026, 9, 9, 15, 0, tzinfo=UTC))
    assert result["authoritative_topology"] is False
    assert result["targeted_article_count"] == 3
    assert result["comparable_article_count"] == 3
    assert result["comparable_article_ratio"] == 1.0
    assert result["edge_count"] == 1
    assert result["strong_edge_count"] == 1
    assert result["stale_server_count"] == 2
    assert all(item["valid_presence_coverage"] == 1.0 for item in result["servers"])


def test_topology_quality_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/quality", timeout=2) as response:
            payload = json.load(response)
        assert payload["model"] == "inferred_topology_data_quality"
        assert payload["authoritative_topology"] is False
        assert "quality_score" in payload

        with urlopen(f"{base}/web/propagation/topology/quality", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology data quality / confidence" in html
        assert "Evidence quality" in html
        assert "Server evidence coverage" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
