import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


def _quality(level: str, score: int, freshness: str, coverage: float) -> dict:
    return {
        "quality_level": level,
        "quality_score": score,
        "servers": [
            {
                "server_id": 1,
                "valid_presence_coverage": coverage,
                "freshness": freshness,
            },
            {
                "server_id": 2,
                "valid_presence_coverage": 1.0,
                "freshness": "fresh",
            },
            {
                "server_id": 3,
                "valid_presence_coverage": 1.0,
                "freshness": "fresh",
            },
        ],
    }


def test_topology_risk_prioritizes_incident_resilience_and_gateway(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    communities = {
        "server_community": {"1": 1, "2": 1, "3": 2},
        "communities": [
            {
                "community_id": 1,
                "server_count": 2,
                "open_incident_count": 1,
                "affected_server_count": 1,
            },
            {
                "community_id": 2,
                "server_count": 1,
                "open_incident_count": 1,
                "affected_server_count": 1,
            },
        ],
    }
    resilience = {
        "nodes": [
            {
                "server_id": 1,
                "host": "a.example.test",
                "impact_score": 80.0,
                "resilience_score": 70.0,
            },
            {
                "server_id": 2,
                "host": "b.example.test",
                "impact_score": 20.0,
                "resilience_score": 10.0,
            },
            {
                "server_id": 3,
                "host": "c.example.test",
                "impact_score": 60.0,
                "resilience_score": 40.0,
            },
        ]
    }
    cross_cluster = {
        "incident_scope": "multi_community",
        "gateway_servers": [
            {
                "server_id": 1,
                "cross_edge_count": 2,
                "max_edge_confidence": 0.9,
            },
            {
                "server_id": 3,
                "cross_edge_count": 2,
                "max_edge_confidence": 0.8,
            },
        ],
    }
    incidents = [
        {
            "server_id": 1,
            "severity": "critical",
            "status": "open",
        },
        {
            "server_id": 3,
            "severity": "warning",
            "status": "open",
        },
    ]
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_communities",
        lambda storage: communities,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_resilience",
        lambda storage: resilience,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.cross_cluster_intelligence",
        lambda storage: cross_cluster,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.list_topology_incidents",
        lambda storage, include_resolved=False: incidents,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_data_quality",
        lambda storage: _quality("good", 90, "fresh", 1.0),
    )

    result = topology_risk(storage)
    assert result["authoritative_topology"] is False
    assert result["incident_scope"] == "multi_community"
    assert result["servers"][0]["host"] == "a.example.test"
    assert result["servers"][0]["risk_score"] > result["servers"][1]["risk_score"]
    assert result["servers"][0]["is_gateway"] is True
    assert result["servers"][0]["evidence_level"] == "high"
    assert result["risk_score_quality_adjusted"] is False
    assert result["communities"][0]["risk_score"] >= result["communities"][1]["risk_score"]


def test_topology_risk_quality_changes_confidence_not_score(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_communities",
        lambda storage: {
            "server_community": {"1": 1},
            "communities": [
                {
                    "community_id": 1,
                    "server_count": 1,
                    "open_incident_count": 1,
                    "affected_server_count": 1,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_resilience",
        lambda storage: {
            "nodes": [
                {
                    "server_id": 1,
                    "host": "a.example.test",
                    "impact_score": 80.0,
                    "resilience_score": 70.0,
                }
            ]
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.cross_cluster_intelligence",
        lambda storage: {"incident_scope": "single_community", "gateway_servers": []},
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.list_topology_incidents",
        lambda storage, include_resolved=False: [
            {"server_id": 1, "severity": "critical", "status": "open"}
        ],
    )

    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_data_quality",
        lambda storage: _quality("good", 90, "fresh", 1.0),
    )
    good = topology_risk(storage)
    monkeypatch.setattr(
        "nntpintel.propagation_topology_risk.topology_data_quality",
        lambda storage: _quality("weak", 30, "very_stale", 0.2),
    )
    weak = topology_risk(storage)

    assert good["servers"][0]["risk_score"] == weak["servers"][0]["risk_score"]
    assert good["servers"][0]["evidence_level"] == "high"
    assert weak["servers"][0]["evidence_level"] == "low"
    assert weak["high_risk_low_evidence_server_count"] == 1


def test_topology_risk_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/risk", timeout=2) as response:
            payload = json.load(response)
        assert payload["model"] == "inferred_topology_risk_synthesis"
        assert payload["authoritative_topology"] is False
        assert payload["risk_score_quality_adjusted"] is False
        assert "data_quality_level" in payload

        with urlopen(f"{base}/web/propagation/topology/risk", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology risk synthesis" in html
        assert "Triage only" in html
        assert "High-risk / weak evidence" in html
        assert "Risk scores are not quality-adjusted" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
