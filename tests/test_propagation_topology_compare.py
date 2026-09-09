import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_compare import compare_evidence_bundles
from nntpintel.storage import Storage


def _bundle(ref: str, fingerprint: str, *, generated_at: str, observation_ids: list[int]) -> dict:
    return {
        "model": "nntpintel_topology_evidence_bundle",
        "schema_version": 1,
        "generated_at": generated_at,
        "authoritative_topology": False,
        "conclusion": {"ref": ref, "type": "risk_server", "why": "why"},
        "related_refs": [ref, "server:4"],
        "quality": {"evidence_level": "high", "evidence_coverage": 1.0},
        "provenance": {"valid_presence_observation_ids": observation_ids},
        "analysis": {"risk": {"risk_score": 72.0}},
        "limitations": ["inference only"],
        "integrity": {
            "algorithm": "sha256",
            "scope": "canonical_evidence_payload_v1",
            "fingerprint": fingerprint,
        },
    }


def test_compare_ignores_export_timestamp_when_fingerprint_matches():
    before = _bundle("risk:server:4", "a" * 64, generated_at="one", observation_ids=[1])
    after = _bundle("risk:server:4", "a" * 64, generated_at="two", observation_ids=[1])

    result = compare_evidence_bundles(before, after)
    assert result["same_fingerprint"] is True
    assert result["changed"] is False
    assert result["change_count"] == 0
    assert result["changed_sections"] == []


def test_compare_reports_structured_evidence_and_quality_changes():
    before = _bundle("risk:server:4", "a" * 64, generated_at="one", observation_ids=[1])
    after = _bundle("risk:server:4", "b" * 64, generated_at="two", observation_ids=[1, 2])
    after["quality"]["evidence_level"] = "limited"
    after["analysis"]["risk"]["risk_score"] = 80.0

    result = compare_evidence_bundles(before, after)
    assert result["changed"] is True
    assert result["same_fingerprint"] is False
    assert "provenance" in result["changed_sections"]
    assert "quality" in result["changed_sections"]
    assert "analysis" in result["changed_sections"]
    paths = {item["path"] for item in result["changes"]}
    assert "$.provenance.valid_presence_observation_ids" in paths
    assert "$.quality.evidence_level" in paths
    assert "$.analysis.risk.risk_score" in paths
    assert "$.generated_at" not in paths


def test_compare_api(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    payload = {
        "model": "nntpintel_topology_evidence_bundle_diff",
        "schema_version": 1,
        "before": {"ref": "server:1", "fingerprint": "a" * 64},
        "after": {"ref": "server:2", "fingerprint": "b" * 64},
        "same_fingerprint": False,
        "changed": True,
        "change_count": 1,
        "changed_sections": ["conclusion"],
        "changes": [],
        "limitations": [],
    }
    monkeypatch.setattr(
        "nntpintel.api.compare_topology_refs",
        lambda storage, before_ref, after_ref: (
            payload if (before_ref, after_ref) == ("server:1", "server:2") else None
        ),
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        qs = urlencode({"before": "server:1", "after": "server:2"})
        with urlopen(f"{base}/propagation/topology/compare?{qs}", timeout=2) as response:
            result = json.load(response)
        assert result["changed"] is True
        assert result["before"]["ref"] == "server:1"
        assert result["after"]["ref"] == "server:2"

        try:
            urlopen(f"{base}/propagation/topology/compare?before=server%3A1", timeout=2)
        except HTTPError as error:
            assert error.code == 400
        else:
            raise AssertionError("missing comparison ref must return 400")

        missing = urlencode({"before": "server:9", "after": "server:10"})
        try:
            urlopen(f"{base}/propagation/topology/compare?{missing}", timeout=2)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("unknown refs must return 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
