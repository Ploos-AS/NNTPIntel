import json
import threading
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_impact import topology_impact
from nntpintel.storage import Storage


def test_topology_impact_ranks_middle_node(monkeypatch, tmp_path):
    topology = {
        "nodes": [
            {"server_id": 1, "host": "a.example.test"},
            {"server_id": 2, "host": "b.example.test"},
            {"server_id": 3, "host": "c.example.test"},
        ],
        "edges": [
            {
                "source_server_id": 1,
                "source_host": "a.example.test",
                "target_server_id": 2,
                "target_host": "b.example.test",
                "confidence": 1.0,
            },
            {
                "source_server_id": 2,
                "source_host": "b.example.test",
                "target_server_id": 3,
                "target_host": "c.example.test",
                "confidence": 1.0,
            },
        ],
    }
    monkeypatch.setattr(
        "nntpintel.propagation_topology_impact.inferred_propagation_topology",
        lambda storage: topology,
    )
    result = topology_impact(Storage(tmp_path / "nntpintel.db"))
    assert result["authoritative_topology"] is False
    assert result["nodes"][0]["host"] == "b.example.test"
    assert result["nodes"][0]["degree"] == 2
    assert result["nodes"][0]["bridge_score"] == 0.5
    assert result["nodes"][0]["impact_score"] > result["nodes"][1]["impact_score"]
    assert result["edges"][0]["impact_score"] == result["nodes"][0]["impact_score"]


def test_topology_impact_api_and_web(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/impact", timeout=2) as response:
            payload = json.load(response)
        assert payload["model"] == "inferred_topology_impact"
        assert payload["authoritative_topology"] is False

        with urlopen(f"{base}/web/propagation/topology/impact", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology impact / centrality" in html
        assert "Inference only" in html

        with urlopen(f"{base}/web/propagation/topology", timeout=2) as response:
            topology_html = response.read().decode("utf-8")
        assert "/web/propagation/topology/impact" in topology_html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
