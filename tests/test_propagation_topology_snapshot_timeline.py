import json
import threading
from urllib.parse import urlencode
from urllib.request import urlopen

from nntpintel.api import make_server
from nntpintel.propagation_topology_snapshots import evidence_snapshot_timeline
from nntpintel.storage import Storage


def _insert_snapshot(storage, *, ref, snapshot_id, captured_at, fingerprint, quality_score):
    bundle = {
        "model": "nntpintel_topology_evidence_bundle",
        "schema_version": 1,
        "generated_at": captured_at,
        "authoritative_topology": False,
        "conclusion": {"ref": ref, "type": "server", "why": "test"},
        "related_refs": [ref],
        "quality": {"quality_score": quality_score},
        "provenance": {"valid_presence_observation_ids": [snapshot_id]},
        "analysis": {},
        "limitations": [],
        "integrity": {
            "algorithm": "sha256",
            "scope": "canonical_evidence_payload_v1",
            "fingerprint": fingerprint,
        },
    }
    from nntpintel.propagation_topology_snapshots import _ensure_schema

    _ensure_schema(storage)
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO topology_evidence_snapshots(
                id, conclusion_ref, conclusion_type, fingerprint, captured_at, bundle_json
            ) VALUES (?, ?, 'server', ?, ?, ?)
            """,
            (
                snapshot_id,
                ref,
                fingerprint,
                captured_at,
                json.dumps(bundle, sort_keys=True, separators=(",", ":")),
            ),
        )
        conn.commit()


def test_snapshot_timeline_reports_meaningful_changes(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    ref = "server:4"
    _insert_snapshot(
        storage,
        ref=ref,
        snapshot_id=1,
        captured_at="2026-09-08T10:00:00Z",
        fingerprint="a" * 64,
        quality_score=90,
    )
    _insert_snapshot(
        storage,
        ref=ref,
        snapshot_id=2,
        captured_at="2026-09-09T10:00:00Z",
        fingerprint="b" * 64,
        quality_score=60,
    )

    result = evidence_snapshot_timeline(storage, ref)
    assert result["timeline_count"] == 2
    assert result["timeline"][0]["change_from_previous"] is None
    change = result["timeline"][1]["change_from_previous"]
    assert change["change_count"] > 0
    assert "quality" in change["changed_sections"]
    assert "provenance" in change["changed_sections"]


def test_snapshot_timeline_since_and_limit(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    ref = "risk:server:4"
    for snapshot_id, day in enumerate((7, 8, 9), start=1):
        _insert_snapshot(
            storage,
            ref=ref,
            snapshot_id=snapshot_id,
            captured_at=f"2026-09-{day:02d}T12:00:00Z",
            fingerprint=str(snapshot_id) * 64,
            quality_score=90 - snapshot_id,
        )

    result = evidence_snapshot_timeline(
        storage,
        ref,
        since="2026-09-08T00:00:00Z",
        limit=1,
    )
    assert result["timeline_count"] == 1
    assert result["has_more"] is True
    assert result["timeline"][0]["captured_at"] == "2026-09-08T12:00:00Z"


def test_snapshot_timeline_api(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    ref = "server:9"
    _insert_snapshot(
        storage,
        ref=ref,
        snapshot_id=1,
        captured_at="2026-09-09T09:00:00Z",
        fingerprint="c" * 64,
        quality_score=80,
    )

    server = make_server(storage, "127.0.0.1", 0)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        query = urlencode({"ref": ref, "since": "2026-09-09T00:00:00Z"})
        with urlopen(
            f"http://{host}:{port}/propagation/topology/snapshot-timeline?{query}",
            timeout=2,
        ) as response:
            payload = json.load(response)
        assert payload["model"] == "nntpintel_topology_evidence_snapshot_timeline"
        assert payload["conclusion_ref"] == ref
        assert payload["timeline_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
