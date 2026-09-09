import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.storage import Storage


def _impact_fixture() -> dict:
    return {
        "nodes": [
            {"server_id": 1, "host": "a.example.test", "impact_score": 80.0},
            {"server_id": 2, "host": "b.example.test", "impact_score": 70.0},
            {"server_id": 3, "host": "c.example.test", "impact_score": 50.0},
            {"server_id": 4, "host": "d.example.test", "impact_score": 40.0},
            {"server_id": 5, "host": "isolated.example.test", "impact_score": 0.0},
        ],
        "edges": [
            {
                "source_server_id": 1,
                "source_host": "a.example.test",
                "target_server_id": 2,
                "target_host": "b.example.test",
                "confidence": 0.9,
            },
            {
                "source_server_id": 3,
                "source_host": "c.example.test",
                "target_server_id": 4,
                "target_host": "d.example.test",
                "confidence": 0.8,
            },
        ],
    }


def test_topology_communities_separate_components_and_isolates(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_communities.topology_impact",
        lambda storage: _impact_fixture(),
    )
    result = topology_communities(storage)
    assert result["authoritative_topology"] is False
    assert result["community_count"] == 3
    assert result["isolated_server_count"] == 1
    assert result["communities_with_open_incidents"] == 0
    assert all(item["open_incident_count"] == 0 for item in result["communities"])
    sizes = sorted(item["server_count"] for item in result["communities"])
    assert sizes == [1, 2, 2]
    isolated = next(item for item in result["communities"] if item["server_count"] == 1)
    assert isolated["servers"][0]["host"] == "isolated.example.test"


def test_topology_communities_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/communities", timeout=2) as response:
            payload = json.load(response)
        assert payload["authoritative_topology"] is False
        assert "community_count" in payload
        assert "communities_with_open_incidents" in payload

        with urlopen(f"{base}/web/propagation/topology/communities", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology communities / clusters" in html
        assert "Inference only" in html
        assert "Open incidents" in html

        with urlopen(f"{base}/web/propagation/topology", timeout=2) as response:
            topology_html = response.read().decode("utf-8")
        assert "/web/propagation/topology/communities" in topology_html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
