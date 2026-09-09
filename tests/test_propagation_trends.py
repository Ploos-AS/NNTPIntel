import json
import threading
from datetime import UTC, datetime
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation import record_presence
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_trends import propagation_trends
from nntpintel.storage import Storage


def _build_trend_fixture(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    fast = storage.ensure_endpoint("fast.example.test")
    slow = storage.ensure_endpoint("slow.example.test")
    for index, delay in enumerate((60, 70, 80), start=1):
        message_id = f"<trend-{index}@example.test>"
        create_campaign(storage, message_id, [fast, slow], stop_after_visible=2)
        base = datetime(2026, 9, 8, index, 0, tzinfo=UTC)
        record_presence(
            storage,
            message_id,
            fast,
            observed_at=base.isoformat(),
            present=True,
            response_code=223,
        )
        record_presence(
            storage,
            message_id,
            slow,
            observed_at=base.replace(second=delay % 60, minute=delay // 60).isoformat(),
            present=True,
            response_code=223,
        )
    return storage


def test_trends_detects_persistent_lagging_server(tmp_path):
    storage = _build_trend_fixture(tmp_path)
    trends = propagation_trends(storage, now=datetime(2026, 9, 9, 6, 0, tzinfo=UTC))

    seven = trends["windows"]["7d"]
    assert seven["article_count"] == 3
    assert seven["lagging_server_count"] == 1
    servers = {item["host"]: item for item in seven["servers"]}
    assert servers["fast.example.test"]["median_delay_seconds"] == 0.0
    assert servers["fast.example.test"]["lagging"] is False
    assert servers["slow.example.test"]["sample_count"] == 3
    assert servers["slow.example.test"]["median_delay_seconds"] == 70.0
    assert servers["slow.example.test"]["median_delta_seconds"] == 40.0
    assert servers["slow.example.test"]["lagging"] is True
    assert trends["daily"]


def test_trends_requires_three_samples_before_lagging(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    fast = storage.ensure_endpoint("fast.example.test")
    slow = storage.ensure_endpoint("slow.example.test")
    message_id = "<single-trend@example.test>"
    create_campaign(storage, message_id, [fast, slow], stop_after_visible=2)
    record_presence(storage, message_id, fast, observed_at="2026-09-09T04:00:00+00:00", present=True, response_code=223)
    record_presence(storage, message_id, slow, observed_at="2026-09-09T04:02:00+00:00", present=True, response_code=223)

    trends = propagation_trends(storage, now=datetime(2026, 9, 9, 6, 0, tzinfo=UTC))
    slow_row = next(item for item in trends["windows"]["24h"]["servers"] if item["host"] == "slow.example.test")
    assert slow_row["median_delta_seconds"] == 60.0
    assert slow_row["lagging"] is False


def test_propagation_trends_api(tmp_path):
    storage = _build_trend_fixture(tmp_path)
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/propagation/trends", timeout=2) as response:
            payload = json.load(response)
        assert set(payload["windows"]) == {"24h", "7d", "30d"}
        assert payload["lagging_min_samples"] == 3
        assert payload["lagging_min_delta_seconds"] == 30.0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
