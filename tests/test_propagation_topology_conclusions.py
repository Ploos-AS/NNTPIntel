from nntpintel.propagation_topology_conclusions import topology_conclusions
from nntpintel.storage import Storage


def test_conclusion_index_collects_all_supported_refs(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    monkeypatch.setattr(
        "nntpintel.propagation_topology_conclusions.topology_evidence",
        lambda storage: {
            "servers": [
                {
                    "evidence_ref": "server:1",
                    "host": "a.example.test",
                    "article_ids": [1, 2],
                    "visible_article_ids": [1],
                }
            ],
            "edges": [
                {
                    "evidence_ref": "edge:1->2",
                    "source_host": "a.example.test",
                    "target_host": "b.example.test",
                    "edge_confidence": 0.8,
                    "directional_sample_count": 3,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_conclusions.topology_risk",
        lambda storage: {
            "servers": [
                {
                    "conclusion_ref": "risk:server:1",
                    "host": "a.example.test",
                    "risk_score": 70.0,
                    "risk_level": "high",
                    "evidence_level": "high",
                }
            ],
            "communities": [
                {
                    "conclusion_ref": "community:1",
                    "community_id": 1,
                    "server_count": 2,
                    "risk_score": 55.0,
                    "risk_level": "high",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "nntpintel.propagation_topology_conclusions.list_topology_incidents",
        lambda storage: [
            {
                "conclusion_ref": "incident:9",
                "id": 9,
                "host": "a.example.test",
                "severity": "critical",
                "status": "open",
                "triage_priority_score": 95.0,
                "evidence_level": "high",
            }
        ],
    )

    result = topology_conclusions(storage)
    assert result["model"] == "inferred_topology_explainable_conclusion_index"
    assert result["conclusion_count"] == 5
    assert result["counts_by_kind"] == {
        "incident": 1,
        "server_risk": 1,
        "community": 1,
        "inferred_edge": 1,
        "server_evidence": 1,
    }
    refs = [item["conclusion_ref"] for item in result["conclusions"]]
    assert refs == [
        "incident:9",
        "risk:server:1",
        "community:1",
        "edge:1->2",
        "server:1",
    ]
