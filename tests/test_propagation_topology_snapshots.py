import json
import threading
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_snapshots import (
    capture_evidence_snapshot,
    compare_evidence_snapshots,
    get_evidence_snapshot,
    list_evidence_snapshots,
)
from nntpintel.storage import Storage


def _bundle(ref: str, fingerprint: str, observation_ids: list[int]) -> dict:
    return {
        "model": "nntpintel_topology_evidence_bundle",
        "schema_version": 1,
        "generated_at": "2026-09-09T12:00:00Z",
        "authoritative_topology": False,
        "conclusion": {"ref": ref, "type": "server", "why": "observed evidence"},
        "related_refs": [ref],
        "quality": {"evidence_level": "high"},
        "provenance": {"valid_presence_observation_ids": observation_ids},
        "analysis": {"server_id": 1},
        "limitations": ["inference only"],
        "integrity": {
            "algorithm": "sha256",
            "scope": "canonical_evidence_payload_v1",
            "fingerprint": fingerprint,
        },
    }


def test_snapshot_deduplicates_same_fingerprint(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    bundle = _bundle("server:1", "a" * 64, [10])
    monkeypatch.setattr(
        "nntpintel.propagation_topology_snapshots.topology_evidence_bundle",
        lambda storage, conclusion_ref, generated_at=None: {**bundle, "generated_at": generated_at},
    )

    first = capture_evidence_snapshot(
        storage, "server:1", captured_at="2026-09-09T12:00:00Z"
    )
    second = capture_evidence_snapshot(
        storage, "server:1", captured_at="2026-09-09T13:00:00Z"
    )

    assert first is not None and first["created"] is True
    assert second is not None and second["created"] is False
    assert second["snapshot_id"] == first["snapshot_id"]
    history = list_evidence_snapshots(storage, "server:1")
    assert history["snapshot_count"] == 1


def test_snapshot_history_and_diff(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    bundles = [
        _bundle("server:1", "a" * 64, [10]),
        _bundle("server:1", "b" * 64, [10, 11]),
    ]

    def fake_bundle(storage, conclusion_ref, generated_at=None):
        bundle = bundles.pop(0)
        return {**bundle, "generated_at": generated_at}

    monkeypatch.setattr(
        "nntpintel.propagation_topology_snapshots.topology_evidence_bundle", fake_bundle
    )
    first = capture_evidence_snapshot(
        storage, "server:1", captured_at="2026-09-09T12:00:00Z"
    )
    second = capture_evidence_snapshot(
        storage, "server:1", captured_at="2026-09-09T13:00:00Z"
    )
    assert first is not None and second is not None

    history = list_evidence_snapshots(storage, "server:1")
    assert [row["id"] for row in history["snapshots"]] == [
        second["snapshot_id"],
        first["snapshot_id"],
    ]
    stored = get_evidence_snapshot(storage, int(second["snapshot_id"]))
    assert stored is not None
    assert stored["bundle"]["provenance"]["valid_presence_observation_ids"] == [10, 11]

    diff = compare_evidence_snapshots(
        storage, int(first["snapshot_id"]), int(second["snapshot_id"])
    )
    assert diff is not None
    assert diff["changed"] is True
    assert "provenance" in diff["changed_sections"]
    assert diff["snapshot_ids"] == {
        "before": first["snapshot_id"],
        "after": second["snapshot_id"],
    }


def test_snapshot_api_history_detail_and_diff(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    bundles = [
        _bundle("server:1", "a" * 64, [10]),
        _bundle("server:1", "b" * 64, [10, 11]),
    ]

    def fake_bundle(storage, conclusion_ref, generated_at=None):
        bundle = bundles.pop(0)
        return {**bundle, "generated_at": generated_at}

    monkeypatch.setattr(
        "nntpintel.propagation_topology_snapshots.topology_evidence_bundle", fake_bundle
    )
    first = capture_evidence_snapshot(storage, "server:1", captured_at="one")
    second = capture_evidence_snapshot(storage, "server:1", captured_at="two")
    assert first is not None and second is not None

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{host}:{port}"
    try:
        ref = quote("server:1", safe="")
        with urlopen(f"{base}/propagation/topology/snapshots?ref={ref}", timeout=2) as response:
            history = json.load(response)
        assert history["snapshot_count"] == 2

        with urlopen(
            f"{base}/propagation/topology/snapshots/{second['snapshot_id']}", timeout=2
        ) as response:
            detail = json.load(response)
        assert detail["fingerprint"] == "b" * 64

        with urlopen(
            f"{base}/propagation/topology/snapshot-diff?before={first['snapshot_id']}&after={second['snapshot_id']}",
            timeout=2,
        ) as response:
            diff = json.load(response)
        assert diff["changed"] is True
        assert "provenance" in diff["changed_sections"]

        try:
            urlopen(f"{base}/propagation/topology/snapshots/99999", timeout=2)
        except HTTPError as error:
            assert error.code == 404
        else:
            raise AssertionError("unknown snapshot must return 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
