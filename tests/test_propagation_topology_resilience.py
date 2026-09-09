import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_resilience import topology_resilience
from nntpintel.storage import Storage


def _communities_fixture() -> dict:
    return {
        "min_confidence": 0.8,
        "server_community": {"1": 1, "2": 1, "3": 1, "4": 2, "5": 2},
        "communities": [],
    }


def _impact_fixture() -> dict:
    nodes = [
        {"server_id": 1, "host": "a.example.test", "impact_score": 30.0},
        {"server_id": 2, "host": "b.example.test", "impact_score": 90.0},
        {"server_id": 3, "host": "c.example.test", "impact_score": 70.0},
        {"server_id": 4, "host": "d.example.test", "impact_score": 60.0},
        {"server_id": 5, "host": "e.example.test", "impact_score": 30.0},
    ]
    edges = [
        {
            "source_server_id": 1,
            "source_host": "a.example.test",
            "target_server_id": 2,
            "target_host": "b.example.test",
            "confidence": 0.95,
            "impact_score": 85.0,
        },
        {
            "source_server_id": 2,
            "source_host": "b.example.test",
            "target_server_id": 3,
            "target_host": "c.example.test",
            "confidence": 0.93,
            "impact_score": 83.0,
        },
        {
            "source_server_id": 4,
            "source_host": "d.example.test",
            "target_server_id": 5,
            "target_host": "e.example.test",
            "confidence": 0.91,
            "impact_score": 55.0,
        },
        {
            "source_server_id": 3,
            "source_host": "c.example.test",
            "target_server_id": 4,
            "target_host": "d.example.test",
            "confidence": 0.72,
            "impact_score": 50.0,
        },
    ]
    return {"nodes": nodes, "edges": edges}


def test_topology_resilience_detects_articulation_and_boundary(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_resilience.topology_communities",
        lambda storage: _communities_fixture(),
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_resilience.topology_impact",
        lambda storage: _impact_fixture(),
    )

    result = topology_resilience(storage)
    assert result["authoritative_topology"] is False
    assert result["cross_community_edge_count"] == 1

    b = next(item for item in result["nodes"] if item["host"] == "b.example.test")
    assert b["fragmentation_delta"] == 1
    assert b["resilience_score"] >= 50.0

    c = next(item for item in result["nodes"] if item["host"] == "c.example.test")
    assert c["lost_cross_community_edges"] == 1
    assert c["cross_community_edge_loss_ratio"] == 1.0

    strong_edge = next(
        item
        for item in result["edges"]
        if item["source_host"] == "a.example.test" and item["target_host"] == "b.example.test"
    )
    assert strong_edge["fragmentation_delta"] == 1
    assert strong_edge["resilience_score"] >= 50.0

    boundary = next(item for item in result["edges"] if item["cross_community"])
    assert boundary["source_community_id"] == 1
    assert boundary["target_community_id"] == 2


def test_topology_resilience_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/resilience", timeout=2) as response:
            payload = json.load(response)
        assert payload["authoritative_topology"] is False
        assert payload["model"] == "inferred_topology_resilience"

        with urlopen(f"{base}/web/propagation/topology/resilience", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology resilience / critical paths" in html
        assert "Inference only" in html

        with urlopen(f"{base}/web/propagation/topology", timeout=2) as response:
            topology_html = response.read().decode("utf-8")
        assert "/web/propagation/topology/resilience" in topology_html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
