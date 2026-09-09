from datetime import UTC, datetime

import pytest

from nntpintel.candidates import (
    classify_observation,
    due_candidates,
    list_candidate_qualifications,
    list_candidates,
    promote_candidate,
    qualify_candidates,
    set_candidate_status,
)
from nntpintel.discovery import import_seeds
from nntpintel.probe import ProbeObservation
from nntpintel.storage import Storage


def _observation(*, code=200, error=None):
    return ProbeObservation(
        observed_at="2026-09-09T01:00:00+00:00",
        host="news.example.test",
        port=119,
        transport="tcp",
        greeting_code=code,
        greeting=None if code is None else f"{code} test greeting",
        capabilities=["VERSION 2"] if error is None else [],
        error=error,
    )


def _add_qualification(storage, host, classification, observed_at):
    with storage.connect() as conn:
        endpoint_id = conn.execute(
            """
            SELECT e.id FROM endpoints e
            JOIN servers s ON s.id = e.server_id
            WHERE s.host = ?
            ORDER BY e.id LIMIT 1
            """,
            (host,),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO candidate_qualifications(endpoint_id, observed_at, classification)
            VALUES (?, ?, ?)
            """,
            (endpoint_id, observed_at, classification),
        )
        conn.commit()


def test_classify_observation():
    assert classify_observation(_observation())[0] == "reachable"
    assert classify_observation(_observation(code=480, error="NNTPProtocolError: unexpected greeting code 480"))[0] == "auth_required"
    assert classify_observation(_observation(code=None, error="NNTPProtocolError: invalid NNTP status line"))[0] == "not_nntp"
    assert classify_observation(_observation(code=None, error="ConnectionRefusedError: refused"))[0] == "unreachable"
    assert classify_observation(_observation(code=None, error="SSLError: certificate verify failed"))[0] == "tls_error"


def test_qualification_keeps_candidate_disabled(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")

    candidates = due_candidates(storage)
    assert len(candidates) == 1
    assert candidates[0]["host"] == "news.example.test"

    def fake_probe(*args, **kwargs):
        return _observation()

    results = qualify_candidates(storage, probe_func=fake_probe)
    assert results[0]["classification"] == "reachable"

    with storage.connect() as conn:
        enabled = conn.execute(
            "SELECT enabled FROM servers WHERE host = 'news.example.test'"
        ).fetchone()["enabled"]
    assert enabled == 0

    history = list_candidate_qualifications(storage)
    assert len(history) == 1
    assert history[0]["classification"] == "reachable"


def test_qualification_history_rotates_candidates(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(
        storage,
        ["one.example.test", "two.example.test"],
        source="test-source",
    )

    def fake_probe(host, **kwargs):
        return ProbeObservation(
            observed_at="2026-09-09T01:00:00+00:00",
            host=host,
            port=119,
            transport="tcp",
            greeting_code=200,
            greeting="200 ready",
        )

    first = qualify_candidates(storage, limit=1, probe_func=fake_probe)
    second = qualify_candidates(storage, limit=1, probe_func=fake_probe)
    assert first[0]["host"] != second[0]["host"]


def test_recent_qualification_is_not_immediately_due_again(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:00:00+00:00")

    now = datetime(2026, 9, 9, 2, 0, tzinfo=UTC)
    assert due_candidates(storage, now=now) == []
    assert len(due_candidates(storage, now=now, min_age_seconds=0)) == 1


def test_candidate_counts_are_not_multiplied_by_multiple_sources(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="source-one")
    import_seeds(storage, ["news.example.test"], source="source-two")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:00:00+00:00")
    _add_qualification(storage, "news.example.test", "unreachable", "2026-09-09T01:01:00+00:00")

    row = list_candidates(storage)[0]
    assert row["qualification_count"] == 2
    assert row["reachable_count"] == 1


def test_promotion_requires_two_recent_reachable_and_latest_reachable(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    now = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)

    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:00:00+00:00")
    with pytest.raises(ValueError, match="needs 2 recent reachable"):
        promote_candidate(storage, "news.example.test", now=now)

    _add_qualification(storage, "news.example.test", "unreachable", "2026-09-09T01:01:00+00:00")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:02:00+00:00")
    result = promote_candidate(storage, "news.example.test", now=now)
    assert result["status"] == "promoted"
    assert result["reachable_count"] == 2

    with storage.connect() as conn:
        enabled = conn.execute(
            "SELECT enabled FROM servers WHERE host = 'news.example.test'"
        ).fetchone()["enabled"]
    assert enabled == 1


def test_promotion_refuses_when_latest_result_is_not_reachable(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:00:00+00:00")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:01:00+00:00")
    _add_qualification(storage, "news.example.test", "unreachable", "2026-09-09T01:02:00+00:00")
    with pytest.raises(ValueError, match="latest recent qualification must be reachable"):
        promote_candidate(
            storage,
            "news.example.test",
            now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        )


def test_promotion_rejects_stale_reachable_history(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    _add_qualification(storage, "news.example.test", "reachable", "2026-08-01T01:00:00+00:00")
    _add_qualification(storage, "news.example.test", "reachable", "2026-08-01T02:00:00+00:00")

    with pytest.raises(ValueError, match="needs 2 recent reachable"):
        promote_candidate(
            storage,
            "news.example.test",
            now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        )


def test_rejected_candidate_must_be_reset_before_promotion(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:00:00+00:00")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:01:00+00:00")
    set_candidate_status(storage, "news.example.test", "rejected")

    with pytest.raises(ValueError, match="status must be pending"):
        promote_candidate(
            storage,
            "news.example.test",
            now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        )

    set_candidate_status(storage, "news.example.test", "pending")
    assert promote_candidate(
        storage,
        "news.example.test",
        now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
    )["status"] == "promoted"


def test_promotion_requires_active_enabled_source_provenance(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:00:00+00:00")
    _add_qualification(storage, "news.example.test", "reachable", "2026-09-09T01:01:00+00:00")
    with storage.connect() as conn:
        conn.execute("UPDATE discovery_sources SET enabled = 0 WHERE name = 'test-source'")
        conn.commit()

    with pytest.raises(ValueError, match="active provenance"):
        promote_candidate(
            storage,
            "news.example.test",
            now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        )


def test_rejected_and_ignored_candidates_leave_qualification_queue(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source="test-source")

    rejected = set_candidate_status(storage, "news.example.test", "rejected", note="not NNTP")
    assert rejected["status"] == "rejected"
    assert due_candidates(storage) == []
    assert list_candidates(storage)[0]["status"] == "rejected"

    set_candidate_status(storage, "news.example.test", "pending")
    assert len(due_candidates(storage)) == 1

    set_candidate_status(storage, "news.example.test", "ignored", note="operator request")
    assert due_candidates(storage) == []
    assert list_candidates(storage)[0]["status"] == "ignored"
