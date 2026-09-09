import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_incidents import list_propagation_incidents
from nntpintel.propagation_topology_incidents import (
    evaluate_topology_incidents,
    list_topology_incidents,
)
from nntpintel.storage import Storage


def _anomaly_payload(at: str, *, include_signal: bool = True) -> dict:
    anomalies = []
    if include_signal:
        anomalies.append(
            {
                "at": at,
                "kind": "edge_reversal",
                "severity": "high",
                "source_server_id": 1,
                "target_server_id": 2,
                "source_host": "a.example.test",
                "target_host": "b.example.test",
            }
        )
    return {
        "days": 30,
        "authoritative_topology": False,
        "anomalies": anomalies,
    }


def test_topology_incident_open_update_resolve(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    storage.ensure_endpoint("a.example.test")
    storage.ensure_endpoint("b.example.test")
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(now.isoformat()),
    )
    first = evaluate_topology_incidents(storage, now=now)
    assert first["created_count"] == 1
    assert first["updated_count"] == 0
    incidents = list_topology_incidents(storage)
    assert len(incidents) == 1
    assert incidents[0]["kind"] == "topology_edge_reversal"
    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["status"] == "open"
    assert incidents[0]["authoritative_topology"] is False
    assert list_propagation_incidents(storage) == []

    second = evaluate_topology_incidents(storage, now=now + timedelta(minutes=5))
    assert second["created_count"] == 0
    assert second["updated_count"] == 1
    assert len(list_topology_incidents(storage)) == 1

    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(now.isoformat(), include_signal=False),
    )
    third = evaluate_topology_incidents(storage, now=now + timedelta(minutes=10))
    assert third["resolved_count"] == 1
    resolved = list_topology_incidents(storage)
    assert resolved[0]["status"] == "resolved"
    assert list_topology_incidents(storage, include_resolved=False) == []


def test_topology_incidents_api_and_web(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    storage.ensure_endpoint("a.example.test")
    storage.ensure_endpoint("b.example.test")
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(now.isoformat()),
    )
    evaluate_topology_incidents(storage, now=now)

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/incidents", timeout=2) as response:
            payload = json.load(response)
        assert len(payload) == 1
        assert payload[0]["kind"] == "topology_edge_reversal"
        assert payload[0]["authoritative_topology"] is False

        with urlopen(f"{base}/web/propagation/topology/incidents", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology incidents" in html
        assert "Inference only" in html
        assert "topology_edge_reversal" in html
        assert "a.example.test" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
