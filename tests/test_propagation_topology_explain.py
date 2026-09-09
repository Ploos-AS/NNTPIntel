import json
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_explain import explain_topology_ref
from nntpintel.storage import Storage


def _patch_models(monkeypatch):
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
    risk = {
        "servers": [
            {
                "server_id": 1,
                "host": "a.example.test",
                "conclusion_ref": "risk:server:1",
                "risk_score": 72.0,
                "risk_level": "high",
                "evidence_level": "high",
                "incident_score": 70.0,
                "resilience_score": 60.0,
                "impact_score": 50.0,
                "gateway_score": 40.0,
            }
        ],
        "communities": [
            {
                "community_id": 1,
                "conclusion_ref": "community:1",
                "risk_score": 64.0,
                "risk_level": "high",
                "evidence_level": "moderate",
                "server_count": 1,
                "open_incident_count": 1,
                "gateway_server_count": 1,
                "members": ["a.example.test"],
                "evidence_refs": ["server:1"],
            }
        ],
    }
    incident = {
        "id": 7,
        "conclusion_ref": "incident:7",
        "server_id": 1,
        "host": "a.example.test",
        "kind": "topology_edge_reversal",
        "severity": "critical",
        "status": "open",
        "triage_priority_score": 95.0,
        "evidence_level": "high",
        "impact_score": 50.0,
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
        lambda storage: risk,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_explain.list_topology_incidents",
        lambda storage: [incident],
    )


def test_explain_server_edge_and_higher_level_refs(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    _patch_models(monkeypatch)

    server = explain_topology_ref(storage, "server:1")
    assert server is not None
    assert server["conclusion_type"] == "server"
    assert server["risk"]["risk_score"] == 72.0

    edge = explain_topology_ref(storage, "edge:1->2")
    assert edge is not None
    assert edge["conclusion_type"] == "edge"
    assert edge["edge_confidence"] == 0.9

    risk = explain_topology_ref(storage, "risk:server:1")
    assert risk is not None
    assert risk["conclusion_type"] == "risk_server"
    assert risk["risk"]["risk_score"] == 72.0
    assert "incident 70.0" in risk["why"]

    incident = explain_topology_ref(storage, "incident:7")
    assert incident is not None
    assert incident["conclusion_type"] == "incident"
    assert incident["incident"]["severity"] == "critical"
    assert incident["incident"]["triage_priority_score"] == 95.0

    community = explain_topology_ref(storage, "community:1")
    assert community is not None
    assert community["conclusion_type"] == "community"
    assert community["community"]["risk_score"] == 64.0
    assert community["evidence"][0]["evidence_ref"] == "server:1"

    assert explain_topology_ref(storage, "risk:server:nope") is None
    assert explain_topology_ref(storage, "incident:nope") is None
    assert explain_topology_ref(storage, "community:nope") is None
    assert explain_topology_ref(storage, "unknown:1") is None


def test_explain_api_and_web_routes(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    explanation = {
        "model": "inferred_topology_conclusion_explanation",
        "evidence_ref": "risk:server:1",
        "conclusion_type": "risk_server",
        "authoritative_topology": False,
        "why": "a.example.test has topology risk 72.0 (high).",
        "server_id": 1,
        "host": "a.example.test",
        "risk": {
            "risk_score": 72.0,
            "risk_level": "high",
            "evidence_level": "high",
            "incident_score": 70.0,
            "resilience_score": 60.0,
            "impact_score": 50.0,
            "gateway_score": 40.0,
        },
        "evidence": None,
        "limitations": ["The risk score is a deterministic internal triage ranking."],
    }
    monkeypatch.setattr(
        "nntpintel.api.explain_topology_ref",
        lambda storage, evidence_ref: explanation if evidence_ref == "risk:server:1" else None,
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_explain_web.explain_topology_ref",
        lambda storage, evidence_ref: explanation if evidence_ref == "risk:server:1" else None,
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    ref = quote("risk:server:1", safe="")
    try:
        with urlopen(f"{base}/propagation/topology/explain/{ref}", timeout=2) as response:
            payload = json.load(response)
        assert payload["evidence_ref"] == "risk:server:1"
        assert payload["conclusion_type"] == "risk_server"

        with urlopen(f"{base}/web/propagation/topology/explain/{ref}", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Why does NNTPIntel believe this?" in html
        assert "risk:server:1" in html
        assert "Incident input" in html

        try:
            urlopen(f"{base}/propagation/topology/explain/incident%3A999", timeout=2)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("unknown conclusion ref must return 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
