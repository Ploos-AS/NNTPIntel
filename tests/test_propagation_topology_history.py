from datetime import UTC, datetime, timedelta

import pytest

from nntpintel.propagation import record_presence
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_topology_history import topology_history
from nntpintel.propagation_topology_history_web import history_page
from nntpintel.storage import Storage


def _day(storage, early, late, day, *, delays=(30, 40, 50)):
    for index, delay in enumerate(delays, start=1):
        message_id = f"<history-{day}-{index}@example.test>"
        create_campaign(storage, message_id, [early, late], stop_after_visible=2)
        base = datetime(2026, 9, day, index, 0, tzinfo=UTC)
        with storage.connect() as conn:
            article_id = conn.execute(
                "SELECT id FROM propagation_articles WHERE message_id = ?", (message_id,)
            ).fetchone()["id"]
            conn.execute(
                "UPDATE propagation_campaigns SET created_at = ? WHERE article_id = ?",
                (base.isoformat(), article_id),
            )
            conn.commit()
        record_presence(
            storage,
            message_id,
            early,
            observed_at=base.isoformat(),
            present=True,
            response_code=223,
        )
        record_presence(
            storage,
            message_id,
            late,
            observed_at=(base + timedelta(seconds=delay)).isoformat(),
            present=True,
            response_code=223,
        )


def test_history_tracks_stability_and_change_events(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    early = storage.ensure_endpoint("early.example.test")
    late = storage.ensure_endpoint("late.example.test")
    _day(storage, early, late, 7)
    _day(storage, early, late, 8)
    _day(storage, early, late, 9, delays=(60, 70, 80))

    history = topology_history(
        storage,
        now=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        days=3,
    )
    assert history["authoritative_topology"] is False
    assert len(history["snapshots"]) == 3
    assert [item["edge_count"] for item in history["snapshots"]] == [1, 1, 1]
    assert len(history["edges"]) == 1
    edge = history["edges"][0]
    assert edge["source_host"] == "early.example.test"
    assert edge["target_host"] == "late.example.test"
    assert edge["observed_days"] == 3
    assert edge["stability_percent"] == 100.0
    assert edge["latest_present"] is True
    assert history["events"][0]["event"] == "appeared"
    assert any(item["event"] == "changed" for item in history["events"])


def test_history_emits_disappeared_when_edge_drops_out(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    early = storage.ensure_endpoint("early.example.test")
    late = storage.ensure_endpoint("late.example.test")
    _day(storage, early, late, 8)

    history = topology_history(
        storage,
        now=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        days=2,
    )
    assert [item["edge_count"] for item in history["snapshots"]] == [1, 0]
    assert any(item["event"] == "disappeared" for item in history["events"])
    assert history["edges"][0]["stability_percent"] == 50.0
    assert history["edges"][0]["latest_present"] is False


def test_history_web_keeps_inference_disclaimer(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    html = history_page(storage)
    assert "Topology history / stability" in html
    assert "Inference only" in html
    assert "does not prove direct NNTP peering" in html


def test_history_validates_window(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    with pytest.raises(ValueError, match="days"):
        topology_history(storage, days=1)
