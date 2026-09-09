import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation import record_presence
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.propagation_topology_evidence import topology_evidence
from nntpintel.storage import Storage


def _fixture(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = storage.ensure_endpoint("a.example.test")
    second = storage.ensure_endpoint("b.example.test")
    start = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    campaign_ids = []
    observation_ids = []
    message_ids = []
    for index in range(3):
        message_id = f"<evidence-{index}@example.test>"
        message_ids.append(message_id)
        campaign = create_campaign(
            storage,
            message_id,
            [first, second],
            now=start + timedelta(minutes=index),
        )
        campaign_ids.append(campaign["id"])
        source_observation = record_presence(
            storage,
            message_id,
            first,
            observed_at=(start + timedelta(minutes=index, seconds=1)).isoformat(),
            present=True,
            response_code=223,
        )
        target_observation = record_presence(
            storage,
            message_id,
            second,
            observed_at=(start + timedelta(minutes=index, seconds=11)).isoformat(),
            present=True,
            response_code=223,
        )
        observation_ids.extend([source_observation, target_observation])
    return storage, campaign_ids, observation_ids, message_ids


def test_topology_evidence_traces_edge_to_campaigns_articles_and_observations(tmp_path):
    storage, campaign_ids, observation_ids, message_ids = _fixture(tmp_path)

    topology = inferred_propagation_topology(storage)
    assert topology["edge_count"] == 1
    edge = topology["edges"][0]
    assert edge["source_host"] == "a.example.test"
    assert edge["target_host"] == "b.example.test"
    assert edge["evidence_ref"].startswith("edge:")

    evidence = topology_evidence(storage)
    assert evidence["model"] == "inferred_topology_evidence_provenance"
    assert evidence["authoritative_topology"] is False
    assert evidence["edge_evidence_count"] == 1
    edge_evidence = evidence["edges"][0]
    assert edge_evidence["evidence_ref"] == edge["evidence_ref"]
    assert edge_evidence["supporting_article_count"] == 3
    assert {item["message_id"] for item in edge_evidence["supporting_articles"]} == set(message_ids)
    assert {
        campaign_id
        for item in edge_evidence["supporting_articles"]
        for campaign_id in item["source_campaign_ids"] + item["target_campaign_ids"]
    } == set(campaign_ids)
    assert {
        observation_id
        for item in edge_evidence["supporting_articles"]
        for observation_id in [item["source_observation_id"], item["target_observation_id"]]
    } == set(observation_ids)
    assert all(item["evidence_ref"].startswith("server:") for item in evidence["servers"])


def test_topology_evidence_api_and_web(tmp_path):
    storage, _, _, _ = _fixture(tmp_path)
    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        with urlopen(f"{base}/propagation/topology/evidence", timeout=2) as response:
            payload = json.load(response)
        assert payload["model"] == "inferred_topology_evidence_provenance"
        assert payload["edge_evidence_count"] == 1
        assert payload["edges"][0]["supporting_article_count"] == 3

        with urlopen(f"{base}/web/propagation/topology/evidence", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Topology evidence provenance" in html
        assert "Explainability only" in html
        assert "evidence-0@example.test" in html
        assert "a.example.test" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
