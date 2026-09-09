import json
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_explain import explain_topology_ref
from nntpintel.storage import Storage


def test_explain_server_and_edge_refs(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    evidence = {
        "servers": [
            {
                "evidence_ref": "server:1",
                "server_id": 1,
                "host": "a.example.test",
                "campaign_ids": [10, 11],
                "article_ids": [20, 21],
                "message_ids": ["<a@test>", "<b@test>"],
                "visible_article_ids": [20, 21],
                "valid_presence_observation_ids": [30, 31],
            }
        ],
        "edges": [
            {
                "evidence_ref": "edge:1->2",
                "source_server_id": 1,
                "source_host": "a.example.test",
                "target_server_id": 2,
                "target_host": "b.example.test",
                "edge_confidence": 0.9,
                "directional_sample_count": 3,
                "supporting_article_count": 3,
                "supporting_articles": [
                    {
                        "article_id": 20,
                        "message_id": "<a@test>",
                        "source_campaign_ids": [10],
                        "target_campaign_ids": [10],
                        "source_endpoint_ids": [1],
                        "target_endpoint_ids": [2],
                        "source_observation_id": 30,
                        "target_observation_id": 40,
                        "source_first_seen_at": "2026-09-09T12:00:00+00:00",
                        "target_first_seen_at": "2026-09-09T12:00:10+00:00",
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        "nntpintel.propagation_topology_explain.topology_evidence",
        lambda storage: evidence,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_explain.topology_data_quality",
        lambda storage: {
            "servers": [
                {
                    "server_id": 1,
                    "valid_presence_coverage": 1.0,
                    "freshness": "fresh",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_explain.topology_risk",
        lambda storage: {
            "servers": [
                {
                    "server_id": 1,
                    "risk_score": 72.0,
                    "risk_level": "high",
                    "evidence_level": "high",
                }
            ]
        },
    )

    server = explain_topology_ref(storage, "server:1")
    assert server is not None
    assert server["conclusion_type"] == "server"
    assert server["risk"]["risk_score"] == 72.0
    assert "2 propagation campaign" in server["why"]

    edge = explain_topology_ref(storage, "edge:1->2")
    assert edge is not None
    assert edge["conclusion_type"] == "edge"
    assert edge["edge_confidence"] == 0.9
    assert edge["evidence"]["supporting_articles"][0]["source_observation_id"] == 30
    assert "does not prove direct NNTP peering" in edge["limitations"][0]

    assert explain_topology_ref(storage, "server:not-an-int") is None
    assert explain_topology_ref(storage, "edge:1-nope-2") is None
    assert explain_topology_ref(storage, "unknown:1") is None


def test_explain_api_and_web_routes(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    explanation = {
        "model": "inferred_topology_conclusion_explanation",
        "evidence_ref": "edge:1->2",
        "conclusion_type": "edge",
        "authoritative_topology": False,
        "why": "a.example.test was repeatedly observed before b.example.test.",
        "source_server_id": 1,
        "source_host": "a.example.test",
        "target_server_id": 2,
        "target_host": "b.example.test",
        "edge_confidence": 0.9,
        "directional_sample_count": 3,
        "evidence": {
            "supporting_article_count": 1,
            "supporting_articles": [],
        },
        "limitations": ["Observed first-seen precedence does not prove direct NNTP peering."],
    }
    monkeypatch.setattr(
        "nntpintel.api.explain_topology_ref",
        lambda storage, evidence_ref: explanation if evidence_ref == "edge:1->2" else None,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_explain_web.explain_topology_ref",
        lambda storage, evidence_ref: explanation if evidence_ref == "edge:1->2" else None,
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    ref = quote("edge:1->2", safe="")
    try:
        with urlopen(f"{base}/propagation/topology/explain/{ref}", timeout=2) as response:
            payload = json.load(response)
        assert payload["evidence_ref"] == "edge:1->2"
        assert payload["conclusion_type"] == "edge"

        with urlopen(f"{base}/web/propagation/topology/explain/{ref}", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Why does NNTPIntel believe this?" in html
        assert "edge:1-&gt;2" in html
        assert "direct NNTP peering" in html

        try:
            urlopen(f"{base}/propagation/topology/explain/server%3A999", timeout=2)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("unknown evidence ref must return 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
