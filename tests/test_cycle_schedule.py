# ruff: noqa: I001
from datetime import UTC, datetime

import pytest

from nntpintel.cycle import (
    configure_cycle_schedule,
    due_cycle_schedules,
    list_cycle_schedules,
    run_due_candidate_cycles,
)
from nntpintel.storage import Storage


SOURCE = "vivil-open-nntp"


def test_cycle_schedule_is_persistent_and_only_due_when_enabled(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    configured = configure_cycle_schedule(
        storage,
        SOURCE,
        interval_seconds=21600,
        candidate_limit=2,
        timeout_seconds=4.0,
        run_now=True,
    )
    assert configured["source"] == SOURCE
    assert configured["enabled"] == 1
    assert configured["candidate_limit"] == 2
    assert configured["timeout_seconds"] == 4.0

    rows = list_cycle_schedules(storage)
    assert len(rows) == 1
    assert due_cycle_schedules(storage, now=datetime.now(UTC))[0]["source"] == SOURCE

    configure_cycle_schedule(
        storage,
        SOURCE,
        interval_seconds=21600,
        enabled=False,
        run_now=True,
    )
    assert due_cycle_schedules(storage, now=datetime.now(UTC)) == []


def test_due_cycle_success_resets_failures_and_advances_schedule(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    configure_cycle_schedule(storage, SOURCE, interval_seconds=3600, run_now=True)

    calls = []

    def fake_cycle(storage, source, *, limit, timeout):
        calls.append((source, limit, timeout))
        return {"source": source, "promotion_count": 0}

    result = run_due_candidate_cycles(storage, cycle_func=fake_cycle)
    assert result[0]["status"] == "success"
    assert calls == [(SOURCE, 3, 5.0)]

    schedule = list_cycle_schedules(storage)[0]
    assert schedule["consecutive_failures"] == 0
    assert schedule["last_cycle_at"] is not None
    assert schedule["next_cycle_at"] > schedule["last_cycle_at"]
    assert due_cycle_schedules(storage, now=datetime.now(UTC)) == []


def test_due_cycle_failure_is_contained_and_backed_off(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    configure_cycle_schedule(storage, SOURCE, interval_seconds=3600, run_now=True)

    def failed_cycle(*args, **kwargs):
        raise RuntimeError("source unavailable")

    result = run_due_candidate_cycles(
        storage,
        cycle_func=failed_cycle,
        max_backoff_seconds=7200,
    )
    assert result == [
        {
            "source": SOURCE,
            "status": "failed",
            "error": "RuntimeError: source unavailable",
        }
    ]

    schedule = list_cycle_schedules(storage)[0]
    assert schedule["consecutive_failures"] == 1
    delay = datetime.fromisoformat(schedule["next_cycle_at"]) - datetime.fromisoformat(
        schedule["last_cycle_at"]
    )
    assert delay.total_seconds() == 7200


def test_cycle_schedule_enforces_conservative_bounds(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")

    with pytest.raises(ValueError, match="between 3600"):
        configure_cycle_schedule(storage, SOURCE, interval_seconds=3599)
    with pytest.raises(ValueError, match="candidate limit"):
        configure_cycle_schedule(storage, SOURCE, candidate_limit=11)
    with pytest.raises(ValueError, match="at most 15"):
        configure_cycle_schedule(storage, SOURCE, timeout_seconds=16)
