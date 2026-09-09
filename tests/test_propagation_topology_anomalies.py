import json
import threading
from urllib.request import urlopen

import pytest

from nntpintel.api import make_server
from nntpintel.propagation_topology_anomalies import topology_anomalies
from nntpintel.storage import Storage


def test_topology_anomalies_detect_reversal_confidence_collapse_and_churn(monkeypatch, tmp_path):
    history = {
        "disclaimer": "inferred only",
        "events": [
            {
                "at": "2026-09-08T00:00:00+00:00",
                "event": "disappeared",
                "source_server_id": 1,
                "source_host": "a.example.test",
                "target_server_id": 2,
                "target_host": "b.example.test",
                "confidence": 1.0,
                "median_lead_seconds": 30.0,
            },
            {
                "at": "2026-09-08T00:00:00+00:00",
                "event": "appeared",
                "source_server_id": 2,
                "source_host": "b.example.test",
                "target_server_id": 1,
                "target_host": "a.example.test",
                "confidence": 1.0,
                "median_lead_seconds": 25.0,
            },
            {
                "at": "2026-09-08T00:00:00+00:00",
                "event": "appeared",
                "source_server_id": 3,
                "source_host": "c.example.test",
                "target_server_id": 4,
                "target_host": "d.example.test",
                "confidence": 0.9,
                "median_lead_seconds": 10.0,
            },
            {
                "at": "2026-09-09T00:00:00+00:00",
                "event": "changed",
                "source_server_id": 3,
                "source_host": "c.example.test",
                "target_server_id": 4,
                "target_host": "d.example.test",
                "confidence": 0.7,
                "previous_confidence": 1.0,
                "median_lead_seconds": 12.0,
                "previous_median_lead_seconds": 10.0,
            },
        ],
    }

    monkeypatch.setattr(
        "nntpintel.propagation_topology_anomalies.topology_history",
        lambda storage, days=30: history,
    )
    storage = Storage(tmp_path / "nntpintel.db")
    result = topology_anomalies(storage, min_churn_events=3)
    kinds = [item["kind"] for item in result["anomalies"]]
    assert "edge_reversal" in kinds
    assert "confidence_collapse" in kinds
    assert "edge_disappeared" in kinds
    assert "topology_churn" in kinds
    collapse = next(item for item in result["anomalies"] if item["kind"] == "confidence_collapse")
    assert collapse["confidence_drop"] == 0.3


def test_topology_anomalies_validates_thresholds(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    with pytest.raises(ValueError, match="min_confidence_drop"):
        topology_anomalies(storage, min_confidence_drop=0)
    with pytest.raises(ValueError, match="min_churn_events"):
        topology_anomalies(storage, min_churn_events=0)


def test_topology_anomalies_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/anomalies", timeout=2) as response:
            payload = json.load(response)
        assert payload["authoritative_topology"] is False
        assert set(payload["counts"]) == {
            "edge_reversal",
            "confidence_collapse",
            "edge_disappeared",
            "topology_churn",
        }

        with urlopen(f"{base}/web/propagation/topology/anomalies", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology anomalies" in html
        assert "Inference only" in html
        assert "Confidence collapses" in html
        assert "Churn events" in html
        assert "/web/propagation/topology/incidents" in html

        with urlopen(f"{base}/web/propagation/topology", timeout=2) as response:
            topology_html = response.read().decode("utf-8")
        assert "/web/propagation/topology/anomalies" in topology_html
        assert "/web/propagation/topology/incidents" in topology_html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
