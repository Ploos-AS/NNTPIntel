from nntpintel.propagation_topology_compare import compare_evidence_bundles
from nntpintel.propagation_topology_semantic_changes import semantic_evidence_changes


def _bundle(*, risk: float, level: str, evidence: str, observations: list[int]) -> dict:
    return {
        "model": "nntpintel_topology_evidence_bundle",
        "schema_version": 1,
        "generated_at": "2026-09-09T12:00:00Z",
        "authoritative_topology": False,
        "conclusion": {"ref": "risk:server:4", "type": "risk_server", "why": "triage"},
        "related_refs": ["risk:server:4", "server:4"],
        "quality": {
            "evidence_level": evidence,
            "evidence_coverage": 100.0 if evidence == "high" else 75.0,
            "evidence_freshness": "fresh" if evidence == "high" else "stale",
        },
        "provenance": {
            "valid_presence_observation_ids": observations,
            "campaign_ids": [1, 2],
            "article_ids": [10, 11],
            "visible_article_ids": [10],
        },
        "analysis": {
            "risk": {
                "risk_score": risk,
                "risk_level": level,
                "evidence_level": evidence,
                "evidence_coverage": 100.0 if evidence == "high" else 75.0,
                "evidence_freshness": "fresh" if evidence == "high" else "stale",
            }
        },
        "limitations": ["inference only"],
        "integrity": {
            "algorithm": "sha256",
            "scope": "canonical_evidence_payload_v1",
            "fingerprint": "a" * 64 if risk < 50 else "b" * 64,
        },
    }


def test_semantic_changes_report_operator_meaningful_fields():
    before = _bundle(risk=42.0, level="moderate", evidence="high", observations=[1, 2])
    after = _bundle(risk=68.0, level="high", evidence="limited", observations=[1, 2, 3, 4])

    changes = semantic_evidence_changes(before, after)
    by_code = {item["code"]: item for item in changes}

    assert by_code["risk"]["summary"] == "Risk 42.0→68.0"
    assert by_code["risk"]["delta"] == 26.0
    assert by_code["risk_level"]["summary"] == "Risk level moderate→high"
    assert by_code["evidence_level"]["summary"] == "Evidence high→limited"
    assert by_code["coverage"]["summary"] == "Evidence coverage 100.0→75.0"
    assert by_code["freshness"]["summary"] == "Evidence freshness fresh→stale"
    assert by_code["presence_observations"]["summary"] == "+2 presence observations (2→4)"


def test_bundle_diff_includes_semantic_changes_and_significance():
    before = _bundle(risk=42.0, level="moderate", evidence="high", observations=[1, 2])
    after = _bundle(risk=68.0, level="high", evidence="limited", observations=[1, 2, 3, 4])
    after["generated_at"] = "2026-09-10T12:00:00Z"

    diff = compare_evidence_bundles(before, after)
    assert diff["changed"] is True
    assert diff["semantic_change_count"] >= 6
    assert any(item["code"] == "risk" for item in diff["semantic_changes"])
    assert all(item["path"] != "generated_at" for item in diff["semantic_changes"])
    assert diff["significance"]["level"] == "important"
    assert diff["significance"]["operator_confirmed"] is False


def test_same_fingerprint_has_no_semantic_changes():
    before = _bundle(risk=42.0, level="moderate", evidence="high", observations=[1, 2])
    after = _bundle(risk=42.0, level="moderate", evidence="high", observations=[1, 2])
    after["generated_at"] = "2026-09-10T12:00:00Z"

    diff = compare_evidence_bundles(before, after)
    assert diff["same_fingerprint"] is True
    assert diff["semantic_change_count"] == 0
    assert diff["semantic_changes"] == []
    assert diff["significance"]["level"] == "informational"
