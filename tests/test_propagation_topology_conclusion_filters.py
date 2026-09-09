import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_conclusions import topology_conclusions
from nntpintel.storage import Storage


def _install_fixture(monkeypatch):
    monkeypatch.setattr(
        "nntpintel.propagation_topology_conclusions.topology_evidence",
        lambda storage: {
            "servers": [
                {
                    "evidence_ref": "server:1",
                    "host": "alpha.example.test",
                    "article_ids": [1, 2],
                    "visible_article_ids": [1],
                }
            ],
            "edges": [
                {
                    "evidence_ref": "edge:1->2",
                    "source_host": "alpha.example.test",
                    "target_host": "beta.example.test",
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
                    "host": "alpha.example.test",
                    "risk_score": 70.0,
                    "risk_level": "high",
                    "evidence_level": "limited",
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
                "host": "alpha.example.test",
                "severity": "critical",
                "status": "open",
                "triage_priority_score": 95.0,
                "evidence_level": "high",
            }
        ],
    )


def test_conclusion_filters_are_navigation_only(monkeypatch, tmp_path):
    _install_fixture(monkeypatch)
    storage = Storage(tmp_path / "nntpintel.db")

    all_rows = topology_conclusions(storage)
    assert all_rows["unfiltered_conclusion_count"] == 5

    incidents = topology_conclusions(storage, kind="incident")
    assert incidents["conclusion_count"] == 1
    assert incidents["conclusions"][0]["conclusion_ref"] == "incident:9"

    alpha = topology_conclusions(storage, query="alpha")
    assert alpha["conclusion_count"] == 4

    risk_ref = topology_conclusions(storage, conclusion_ref="risk:server")
    assert [item["conclusion_ref"] for item in risk_ref["conclusions"]] == ["risk:server:1"]

    try:
        topology_conclusions(storage, kind="not-a-kind")
    except ValueError as error:
        assert "invalid conclusion kind" in str(error)
    else:
        raise AssertionError("invalid kind must fail")


def test_conclusion_filter_api_and_web(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    payload = {
        "model": "inferred_topology_explainable_conclusion_index",
        "authoritative_topology": False,
        "disclaimer": "navigation only",
        "conclusion_count": 1,
        "unfiltered_conclusion_count": 5,
        "counts_by_kind": {"incident": 1},
        "filters": {"kind": "incident", "query": None, "conclusion_ref": None},
        "conclusions": [
            {
                "conclusion_ref": "incident:9",
                "kind": "incident",
                "label": "Incident 9: alpha.example.test",
                "summary": "critical/open",
            }
        ],
    }

    def fake_conclusions(storage, **kwargs):
        if kwargs.get("kind") == "bad":
            raise ValueError("invalid conclusion kind")
        return payload

    monkeypatch.setattr("nntpintel.api.topology_conclusions", fake_conclusions)
    monkeypatch.setattr(
        "nntpintel.propagation_topology_conclusions_web.topology_conclusions",
        fake_conclusions,
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        qs = urlencode({"kind": "incident"})
        with urlopen(f"{base}/propagation/topology/conclusions?{qs}", timeout=2) as response:
            api_payload = json.load(response)
        assert api_payload["conclusion_count"] == 1
        assert api_payload["conclusions"][0]["conclusion_ref"] == "incident:9"

        with urlopen(f"{base}/web/propagation/topology/conclusions?{qs}", timeout=2) as response:
            html = response.read().decode("utf-8")
        assert "Explainability search / filtering" in html
        assert "incident:9" in html
        assert "Showing <strong>1</strong> of 5" in html

        try:
            urlopen(f"{base}/propagation/topology/conclusions?kind=bad", timeout=2)
        except HTTPError as error:
            assert error.code == 400
        else:
            raise AssertionError("invalid kind must return 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
