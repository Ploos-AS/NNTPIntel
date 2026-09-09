from datetime import UTC, datetime, timedelta

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
