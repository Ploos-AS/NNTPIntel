import json
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_export import topology_evidence_bundle
from nntpintel.storage import Storage


def test_evidence_bundle_is_versioned_and_compact(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_export.explain_topology_ref",
        lambda storage, evidence_ref: {
            "model": "inferred_topology_conclusion_explanation",
            "evidence_ref": evidence_ref,
            "conclusion_type": "risk_server",
            "authoritative_topology": False,
            "why": "risk explanation",
            "server_id": 4,
            "host": "alpha.example.test",
            "risk": {
                "conclusion_ref": "risk:server:4",
                "evidence_ref": "server:4",
                "risk_score": 72.0,
                "risk_level": "high",
                "evidence_level": "limited",
                "evidence_coverage": 0.5,
                "evidence_freshness": "stale",
            },
            "evidence": {
                "evidence_ref": "server:4",
                "campaign_ids": [1, 2],
                "message_ids": ["<a@test>"],
                "valid_presence_observation_ids": [10],
            },
            "limitations": ["inference only"],
        },
    )

    bundle = topology_evidence_bundle(
        storage,
        "risk:server:4",
        generated_at="2026-09-09T12:00:00Z",
    )
    assert bundle is not None
    assert bundle["model"] == "nntpintel_topology_evidence_bundle"
    assert bundle["schema_version"] == 1
    assert bundle["generated_at"] == "2026-09-09T12:00:00Z"
    assert bundle["conclusion"] == {
        "ref": "risk:server:4",
        "type": "risk_server",
        "why": "risk explanation",
    }
    assert bundle["quality"] == {
        "evidence_level": "limited",
        "evidence_coverage": 0.5,
        "evidence_freshness": "stale",
    }
    assert bundle["related_refs"] == ["risk:server:4", "server:4"]
    assert bundle["provenance"]["campaign_ids"] == [1, 2]
    assert bundle["analysis"]["risk"]["risk_score"] == 72.0
    assert bundle["limitations"] == ["inference only"]


def test_evidence_bundle_edge_quality(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_export.explain_topology_ref",
        lambda storage, evidence_ref: {
            "model": "inferred_topology_conclusion_explanation",
            "evidence_ref": evidence_ref,
            "conclusion_type": "edge",
            "authoritative_topology": False,
            "why": "observed precedence",
            "source_server_id": 1,
            "target_server_id": 2,
            "edge_confidence": 0.8,
            "directional_sample_count": 3,
            "evidence": {"evidence_ref": "edge:1->2", "supporting_article_count": 3},
            "limitations": ["not direct peering"],
        },
    )

    bundle = topology_evidence_bundle(storage, "edge:1->2", generated_at="fixed")
    assert bundle is not None
    assert bundle["quality"] == {
        "edge_confidence": 0.8,
        "directional_sample_count": 3,
    }
    assert bundle["related_refs"] == ["edge:1->2"]


def test_evidence_export_api_and_not_found(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    payload = {
        "model": "nntpintel_topology_evidence_bundle",
        "schema_version": 1,
        "generated_at": "fixed",
        "authoritative_topology": False,
        "conclusion": {"ref": "edge:1->2", "type": "edge", "why": "why"},
        "related_refs": ["edge:1->2"],
        "quality": {"edge_confidence": 0.8},
        "provenance": {},
        "analysis": {},
        "limitations": [],
    }
    monkeypatch.setattr(
        "nntpintel.api.topology_evidence_bundle",
        lambda storage, evidence_ref: payload if evidence_ref == "edge:1->2" else None,
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        ref = quote("edge:1->2", safe="")
        with urlopen(f"{base}/propagation/topology/export/{ref}", timeout=2) as response:
            exported = json.load(response)
        assert exported["schema_version"] == 1
        assert exported["conclusion"]["ref"] == "edge:1->2"

        missing = quote("edge:9->10", safe="")
        try:
            urlopen(f"{base}/propagation/topology/export/{missing}", timeout=2)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("unknown export ref must return 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
