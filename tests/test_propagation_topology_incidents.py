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


def _anomaly_payload(
    marker: str,
    *,
    include_signal: bool = True,
    severity: str = "high",
    kind: str = "edge_reversal",
) -> dict:
    anomalies = []
    if include_signal:
        anomalies.append(
            {
                "at": marker,
                "kind": kind,
                "severity": severity,
                "source_server_id": 1,
                "target_server_id": 2,
                "source_host": "a.example.test",
                "target_host": "b.example.test",
            }
        )
    return {
        "days": 30,
        "snapshot_marker": marker,
        "authoritative_topology": False,
        "anomalies": anomalies,
    }


def _storage(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    storage.ensure_endpoint("a.example.test")
    storage.ensure_endpoint("b.example.test")
    return storage


def _quality(level="good", coverage=1.0, freshness="fresh"):
    return {
        "quality_score": 90 if level == "good" else 30,
        "quality_level": level,
        "servers": [
            {
                "server_id": 1,
                "host": "a.example.test",
                "valid_presence_coverage": coverage,
                "freshness": freshness,
            }
        ],
    }


def test_critical_topology_incident_opens_immediately_and_recovers_stably(monkeypatch, tmp_path):
    storage = _storage(tmp_path)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    marker1 = "2026-09-09T00:00:00+00:00"

    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker1),
    )
    first = evaluate_topology_incidents(storage, now=now)
    assert first["created_count"] == 1
    incidents = list_topology_incidents(storage)
    assert len(incidents) == 1
    assert incidents[0]["kind"] == "topology_edge_reversal"
    assert incidents[0]["severity"] == "critical"
    assert incidents[0]["status"] == "open"
    assert incidents[0]["authoritative_topology"] is False
    assert list_propagation_incidents(storage) == []

    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker1, include_signal=False),
    )
    same = evaluate_topology_incidents(storage, now=now + timedelta(minutes=5))
    assert same["resolved_count"] == 0
    assert list_topology_incidents(storage)[0]["status"] == "open"

    marker2 = "2026-09-10T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker2, include_signal=False),
    )
    recovering = evaluate_topology_incidents(storage, now=now + timedelta(days=1))
    assert recovering["resolved_count"] == 0
    assert list_topology_incidents(storage)[0]["status"] == "recovering"

    marker3 = "2026-09-11T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker3, include_signal=False),
    )
    resolved_result = evaluate_topology_incidents(storage, now=now + timedelta(days=2))
    assert resolved_result["resolved_count"] == 1
    resolved = list_topology_incidents(storage)
    assert resolved[0]["status"] == "resolved"
    states = [item["state"] for item in resolved[0]["detail"]["evidence_history"]]
    assert states == ["open", "recovering", "resolved"]
    assert list_topology_incidents(storage, include_resolved=False) == []


def test_warning_requires_two_distinct_snapshots_before_open(monkeypatch, tmp_path):
    storage = _storage(tmp_path)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    marker1 = "2026-09-09T00:00:00+00:00"

    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker1, severity="medium", kind="confidence_collapse"),
    )
    first = evaluate_topology_incidents(storage, now=now)
    assert first["created_count"] == 0
    assert first["pending_count"] == 1
    assert list_topology_incidents(storage) == []

    duplicate = evaluate_topology_incidents(storage, now=now + timedelta(minutes=5))
    assert duplicate["created_count"] == 0
    assert list_topology_incidents(storage) == []

    marker2 = "2026-09-10T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker2, severity="medium", kind="confidence_collapse"),
    )
    second = evaluate_topology_incidents(storage, now=now + timedelta(days=1))
    assert second["created_count"] == 1
    incidents = list_topology_incidents(storage)
    assert len(incidents) == 1
    assert incidents[0]["kind"] == "topology_confidence_collapse"
    assert incidents[0]["status"] == "open"
    assert incidents[0]["detail"]["signal_streak"] == 2
    assert len(incidents[0]["detail"]["evidence_history"]) == 2


def test_one_off_warning_is_suppressed(monkeypatch, tmp_path):
    storage = _storage(tmp_path)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    marker1 = "2026-09-09T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker1, severity="medium", kind="edge_disappeared"),
    )
    evaluate_topology_incidents(storage, now=now)

    marker2 = "2026-09-10T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker2, include_signal=False),
    )
    evaluate_topology_incidents(storage, now=now + timedelta(days=1))
    assert list_topology_incidents(storage) == []


def test_incident_priority_distinguishes_evidence_without_changing_severity(monkeypatch, tmp_path):
    storage = _storage(tmp_path)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    marker = "2026-09-09T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker),
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_impact",
        lambda storage: {"nodes": [{"server_id": 1, "impact_score": 50.0}]},
    )
    evaluate_topology_incidents(storage, now=now)

    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_data_quality",
        lambda storage: _quality("good", 1.0, "fresh"),
    )
    high = list_topology_incidents(storage)[0]
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_data_quality",
        lambda storage: _quality("weak", 0.1, "very_stale"),
    )
    low = list_topology_incidents(storage)[0]

    assert high["severity"] == low["severity"] == "critical"
    assert high["evidence_level"] == "high"
    assert low["evidence_level"] == "low"
    assert high["triage_priority_score"] > low["triage_priority_score"]
    assert low["evidence_caution"] is True


def test_topology_incidents_api_and_web(monkeypatch, tmp_path):
    storage = _storage(tmp_path)
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    marker = "2026-09-09T00:00:00+00:00"
    monkeypatch.setattr(
        "nntpintel.propagation_topology_incidents.topology_anomalies",
        lambda storage: _anomaly_payload(marker),
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
        assert payload[0]["detail"]["evidence_history"]
        assert "evidence_level" in payload[0]
        assert "triage_priority_score" in payload[0]

        with urlopen(f"{base}/web/propagation/topology/incidents", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology incidents" in html
        assert "Inference only" in html
        assert "Triage" in html
        assert "Evidence" in html
        assert "a.example.test" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
