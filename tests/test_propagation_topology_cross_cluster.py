import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.propagation_topology_cross_cluster import cross_cluster_intelligence
from nntpintel.storage import Storage


def _impact_fixture() -> dict:
    return {
        "nodes": [
            {"server_id": 1, "host": "a.example.test", "impact_score": 80.0},
            {"server_id": 2, "host": "b.example.test", "impact_score": 75.0},
            {"server_id": 3, "host": "c.example.test", "impact_score": 70.0},
            {"server_id": 4, "host": "d.example.test", "impact_score": 60.0},
        ],
        "edges": [
            {
                "source_server_id": 1,
                "source_host": "a.example.test",
                "target_server_id": 2,
                "target_host": "b.example.test",
                "confidence": 0.9,
                "impact_score": 72.0,
            },
            {
                "source_server_id": 3,
                "source_host": "c.example.test",
                "target_server_id": 4,
                "target_host": "d.example.test",
                "confidence": 0.85,
                "impact_score": 59.5,
            },
            {
                "source_server_id": 2,
                "source_host": "b.example.test",
                "target_server_id": 3,
                "target_host": "c.example.test",
                "confidence": 0.72,
                "impact_score": 54.0,
            },
        ],
    }


def test_strong_edge_communities_keep_weak_boundary_separate(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_communities.topology_impact",
        lambda storage: _impact_fixture(),
    )
    result = topology_communities(storage)
    assert result["min_confidence"] == 0.8
    assert result["community_count"] == 2
    assert result["server_community"]["1"] == result["server_community"]["2"]
    assert result["server_community"]["3"] == result["server_community"]["4"]
    assert result["server_community"]["2"] != result["server_community"]["3"]


def test_cross_cluster_gateways_links_and_multi_community_scope(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    communities = {
        "min_confidence": 0.8,
        "community_count": 2,
        "server_community": {"1": 1, "2": 1, "3": 2, "4": 2},
        "communities": [
            {"community_id": 1, "open_incident_count": 1},
            {"community_id": 2, "open_incident_count": 2},
        ],
    }
    monkeypatch.setattr(
        "nntpintel.propagation_topology_cross_cluster.topology_communities",
        lambda storage: communities,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_cross_cluster.topology_impact",
        lambda storage: _impact_fixture(),
    )
    result = cross_cluster_intelligence(storage)
    assert result["authoritative_topology"] is False
    assert result["cross_community_edge_count"] == 1
    assert result["gateway_server_count"] == 2
    assert result["community_link_count"] == 1
    assert result["incident_scope"] == "multi_community"
    edge = result["cross_community_edges"][0]
    assert edge["source_host"] == "b.example.test"
    assert edge["target_host"] == "c.example.test"
    assert edge["source_community_id"] == 1
    assert edge["target_community_id"] == 2


def test_cross_cluster_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/cross-cluster", timeout=2) as response:
            payload = json.load(response)
        assert payload["authoritative_topology"] is False
        assert "cross_community_edge_count" in payload
        assert "incident_scope" in payload

        with urlopen(f"{base}/web/propagation/topology/cross-cluster", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Cross-cluster propagation intelligence" in html
        assert "Inference only" in html

        with urlopen(f"{base}/web/propagation/topology", timeout=2) as response:
            topology_html = response.read().decode("utf-8")
        assert "/web/propagation/topology/cross-cluster" in topology_html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
