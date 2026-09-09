import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation import record_presence
from nntpintel.propagation_analytics import propagation_analytics
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_probe import PresenceProbeResult, probe_and_record_presence
from nntpintel.storage import Storage


def test_analytics_computes_delay_coverage_and_slowest_endpoints(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = storage.ensure_endpoint("news-a.example.test")
    second = storage.ensure_endpoint("news-b.example.test")
    third = storage.ensure_endpoint("news-c.example.test")

    message_one = "<analytics-one@example.test>"
    message_two = "<analytics-two@example.test>"
    for message_id in (message_one, message_two):
        create_campaign(storage, message_id, [first, second, third], stop_after_visible=3)

    record_presence(storage, message_one, first, observed_at="2026-09-09T06:00:00+00:00", present=True, response_code=223)
    record_presence(storage, message_one, second, observed_at="2026-09-09T06:00:10+00:00", present=True, response_code=223)
    record_presence(storage, message_one, third, observed_at="2026-09-09T06:00:30+00:00", present=True, response_code=223)
    record_presence(storage, message_two, first, observed_at="2026-09-09T06:10:00+00:00", present=True, response_code=223)
    record_presence(storage, message_two, second, observed_at="2026-09-09T06:10:20+00:00", present=True, response_code=223)
    record_presence(storage, message_two, third, observed_at="2026-09-09T06:10:20+00:00", present=False, response_code=430)

    analytics = propagation_analytics(storage)
    assert analytics["article_count"] == 2
    assert analytics["articles_with_visibility"] == 2
    assert analytics["targeted_pair_count"] == 6
    assert analytics["targeted_visible_pair_count"] == 5
    assert analytics["target_coverage_percent"] == 83.33
    assert analytics["sample_count"] == 5
    assert analytics["median_delay_seconds"] == 10.0
    assert analytics["p95_delay_seconds"] == 28.0

    endpoints = {item["host"]: item for item in analytics["endpoints"]}
    assert endpoints["news-a.example.test"]["coverage_percent"] == 100.0
    assert endpoints["news-a.example.test"]["median_delay_seconds"] == 0.0
    assert endpoints["news-b.example.test"]["median_delay_seconds"] == 15.0
    assert endpoints["news-b.example.test"]["p95_delay_seconds"] == 19.5
    assert endpoints["news-c.example.test"]["coverage_percent"] == 50.0
    assert endpoints["news-c.example.test"]["median_delay_seconds"] == 30.0
    assert analytics["endpoints"][0]["host"] == "news-c.example.test"


def test_unknown_probe_result_is_not_persisted_as_absent(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")

    def fake_probe(host, message_id, **kwargs):
        return PresenceProbeResult(
            observed_at="2026-09-09T06:30:00+00:00",
            host=host,
            port=119,
            transport="tcp",
            message_id=message_id,
            present=False,
            response_code=480,
            response="480 authentication required",
            error="unexpected STAT status 480: 480 authentication required",
        )

    result = probe_and_record_presence(
        storage,
        endpoint_id,
        "<unknown@example.test>",
        probe_func=fake_probe,
    )
    assert result["error"] is not None
    with storage.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM propagation_observations").fetchone()[0] == 0


def test_propagation_analytics_api(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news-api.example.test")
    message_id = "<analytics-api@example.test>"
    create_campaign(storage, message_id, [endpoint_id], stop_after_visible=1)
    record_presence(
        storage,
        message_id,
        endpoint_id,
        observed_at="2026-09-09T06:45:00+00:00",
        present=True,
        response_code=223,
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://{host}:{port}/propagation/analytics", timeout=2) as response:
            payload = json.load(response)
        assert payload["target_coverage_percent"] == 100.0
        assert payload["median_delay_seconds"] == 0.0
        assert payload["servers"][0]["host"] == "news-api.example.test"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
