import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


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

    result = topology_risk(storage)
    assert result["authoritative_topology"] is False
    assert result["incident_scope"] == "multi_community"
    assert result["servers"][0]["host"] == "a.example.test"
    assert result["servers"][0]["risk_score"] > result["servers"][1]["risk_score"]
    assert result["servers"][0]["is_gateway"] is True
    assert result["communities"][0]["risk_score"] >= result["communities"][1]["risk_score"]


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
        assert "high_risk_server_count" in payload

        with urlopen(f"{base}/web/propagation/topology/risk", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology risk synthesis" in html
        assert "Triage only" in html
        assert "High-risk servers" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
