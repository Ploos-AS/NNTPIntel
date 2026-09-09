import pytest

from nntpintel.cycle import list_cycle_runs, run_candidate_cycle
from nntpintel.discovery import import_seeds
from nntpintel.probe import ProbeObservation
from nntpintel.storage import Storage


def _fake_refresh(storage, source, *, activate=False, content=None):
    assert activate is False
    return import_seeds(
        storage,
        ["one.example.test", "two.example.test", "three.example.test"],
        source=source,
        source_ref="https://example.test/list",
        activate=activate,
        snapshot=True,
    )


def _fake_probe(host, *, port, implicit_tls, starttls, timeout):
    return ProbeObservation(
        observed_at=f"2026-09-09T02:00:0{len(host) % 10}+00:00",
        host=host,
        port=port,
        transport="tls" if implicit_tls else "tcp",
        greeting_code=200,
        greeting="200 ready",
        capabilities=["VERSION 2", "READER"],
    )


def test_candidate_cycle_refreshes_and_qualifies_small_batch_without_promotion(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")

    result = run_candidate_cycle(
        storage,
        "test-source",
        limit=2,
        timeout=4.0,
        probe_func=_fake_probe,
        refresh_func=_fake_refresh,
    )

    assert result["run_id"] > 0
    assert result["source"] == "test-source"
    assert result["status"] == "success"
    assert result["refresh"]["accepted"] == 3
    assert result["qualification_count"] == 2
    assert result["classifications"] == {"reachable": 2}
    assert result["promotion_count"] == 0
    assert all(row["classification"] == "reachable" for row in result["qualifications"])

    with storage.connect() as conn:
        enabled = [
            row["enabled"]
            for row in conn.execute("SELECT enabled FROM servers ORDER BY host").fetchall()
        ]
        qualification_count = conn.execute(
            "SELECT COUNT(*) AS count FROM candidate_qualifications"
        ).fetchone()["count"]
    assert enabled == [0, 0, 0]
    assert qualification_count == 2

    history = list_cycle_runs(storage)
    assert len(history) == 1
    assert history[0]["id"] == result["run_id"]
    assert history[0]["source"] == "test-source"
    assert history[0]["status"] == "success"
    assert history[0]["added"] == 3
    assert history[0]["missing"] == 0
    assert history[0]["qualification_count"] == 2
    assert history[0]["classifications"] == {"reachable": 2}
    assert history[0]["promotion_count"] == 0
    assert history[0]["started_at"]
    assert history[0]["finished_at"]


def test_candidate_cycle_does_not_requalify_rejected_candidate(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    _fake_refresh(storage, "test-source")

    from nntpintel.candidates import set_candidate_status

    set_candidate_status(storage, "one.example.test", "rejected", note="operator decision")

    result = run_candidate_cycle(
        storage,
        "test-source",
        limit=3,
        probe_func=_fake_probe,
        refresh_func=_fake_refresh,
    )
    hosts = {row["host"] for row in result["qualifications"]}
    assert "one.example.test" not in hosts
    assert hosts == {"two.example.test", "three.example.test"}


def test_candidate_cycle_records_failed_run(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")

    def failing_refresh(*args, **kwargs):
        raise RuntimeError("source unavailable")

    with pytest.raises(RuntimeError, match="source unavailable"):
        run_candidate_cycle(storage, "broken-source", refresh_func=failing_refresh)

    history = list_cycle_runs(storage, source="broken-source")
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert history[0]["finished_at"]
    assert "RuntimeError: source unavailable" in history[0]["error"]
    assert history[0]["qualification_count"] == 0
    assert history[0]["classifications"] == {}


def test_cycle_history_filters_source_and_validates_limit(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    run_candidate_cycle(
        storage,
        "source-a",
        limit=0,
        refresh_func=_fake_refresh,
    )
    run_candidate_cycle(
        storage,
        "source-b",
        limit=0,
        refresh_func=_fake_refresh,
    )

    assert [row["source"] for row in list_cycle_runs(storage, source="source-a")] == ["source-a"]
    with pytest.raises(ValueError, match="between 1 and 1000"):
        list_cycle_runs(storage, limit=0)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        list_cycle_runs(storage, limit=1001)


def test_candidate_cycle_enforces_conservative_bounds(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")

    with pytest.raises(ValueError, match="cannot exceed 10"):
        run_candidate_cycle(storage, "test-source", limit=11, refresh_func=_fake_refresh)

    with pytest.raises(ValueError, match="at most 15"):
        run_candidate_cycle(storage, "test-source", timeout=16, refresh_func=_fake_refresh)
