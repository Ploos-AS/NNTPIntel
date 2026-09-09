import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_overview import topology_overview
from nntpintel.storage import Storage


def test_topology_overview_prioritizes_current_attention(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.inferred_propagation_topology",
        lambda storage: {"node_count": 3, "edge_count": 2},
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.topology_anomalies",
        lambda storage: {"anomaly_count": 2},
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.list_topology_incidents",
        lambda storage, include_resolved=False: [
            {"severity": "critical", "status": "open"},
            {"severity": "warning", "status": "recovering"},
        ],
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.topology_communities",
        lambda storage: {"communities": [{"community_id": 1}, {"community_id": 2}]},
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.cross_cluster_intelligence",
        lambda storage: {
            "incident_scope": "multi_community",
            "gateway_servers": [{"server_id": 1}],
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.topology_resilience",
        lambda storage: {
            "nodes": [
                {"server_id": 1, "resilience_level": "critical"},
                {"server_id": 2, "resilience_level": "moderate"},
            ]
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_overview.topology_risk",
        lambda storage: {
            "data_quality_score": 45,
            "data_quality_level": "limited",
            "high_risk_low_evidence_server_count": 1,
            "servers": [
                {
                    "host": "a.example.test",
                    "risk_score": 82.0,
                    "risk_level": "critical",
                    "evidence_level": "limited",
                    "open_incident_count": 1,
                    "is_gateway": True,
                },
                {
                    "host": "b.example.test",
                    "risk_score": 35.0,
                    "risk_level": "moderate",
                    "evidence_level": "high",
                    "open_incident_count": 0,
                    "is_gateway": False,
                },
            ],
            "communities": [
                {
                    "community_id": 1,
                    "risk_score": 60.0,
                    "risk_level": "high",
                    "evidence_level": "limited",
                },
                {
                    "community_id": 2,
                    "risk_score": 20.0,
                    "risk_level": "low",
                    "evidence_level": "high",
                },
            ],
        },
    )

    result = topology_overview(storage)
    assert result["authoritative_topology"] is False
    assert result["posture"] == "critical"
    assert result["data_quality"]["score"] == 45
    assert result["data_quality"]["level"] == "limited"
    assert result["data_quality"]["risk_score_quality_adjusted"] is False
    assert result["signals"]["critical_incident_count"] == 1
    assert result["signals"]["recovering_incident_count"] == 1
    assert result["signals"]["incident_scope"] == "multi_community"
    assert result["attention"][0]["priority"] == 1
    assert any(item["evidence_caution"] for item in result["attention"])
    assert any(item["kind"] == "incident_scope" for item in result["attention"])


def test_topology_overview_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/overview", timeout=2) as response:
            payload = json.load(response)
        assert payload["model"] == "inferred_topology_executive_overview"
        assert payload["authoritative_topology"] is False
        assert "posture" in payload
        assert "data_quality" in payload
        assert "attention" in payload

        with urlopen(f"{base}/web/propagation/topology/overview", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology executive overview" in html
        assert "What needs attention now" in html
        assert "High-risk / weak evidence" in html
        assert "Risk scores are not quality-adjusted" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
