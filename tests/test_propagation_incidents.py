from datetime import UTC, datetime

from nntpintel.propagation import record_presence
from nntpintel.propagation_campaigns import create_campaign
from nntpintel.propagation_incidents import (
    evaluate_propagation_incidents,
    list_propagation_incidents,
)
from nntpintel.storage import Storage


def _add_article(storage, fast, slow, index, base, slow_delay, *, slow_visible=True):
    message_id = f"<incident-{index}@example.test>"
    create_campaign(storage, message_id, [fast, slow], stop_after_visible=2)
    record_presence(
        storage,
        message_id,
        fast,
        observed_at=base.isoformat(),
        present=True,
        response_code=223,
    )
    if slow_visible:
        record_presence(
            storage,
            message_id,
            slow,
            observed_at=base.replace(
                minute=base.minute + slow_delay // 60,
                second=slow_delay % 60,
            ).isoformat(),
            present=True,
            response_code=223,
        )
    else:
        record_presence(
            storage,
            message_id,
            slow,
            observed_at=base.isoformat(),
            present=False,
            response_code=430,
        )


def test_incident_lifecycle_opens_updates_and_resolves_lagging(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    fast = storage.ensure_endpoint("fast.example.test")
    slow = storage.ensure_endpoint("slow.example.test")
    for index, delay in enumerate((60, 70, 80), start=1):
        _add_article(
            storage,
            fast,
            slow,
            index,
            datetime(2026, 9, 8, index, 0, tzinfo=UTC),
            delay,
        )

    first = evaluate_propagation_incidents(
        storage,
        now=datetime(2026, 9, 9, 6, 0, tzinfo=UTC),
    )
    assert first["created_count"] == 1
    assert first["open_incident_count"] == 1
    incidents = list_propagation_incidents(storage)
    assert len(incidents) == 1
    assert incidents[0]["host"] == "slow.example.test"
    assert incidents[0]["kind"] == "lagging"
    assert incidents[0]["status"] == "open"
    assert incidents[0]["severity"] == "warning"
    incident_id = incidents[0]["id"]

    second = evaluate_propagation_incidents(
        storage,
        now=datetime(2026, 9, 9, 6, 5, tzinfo=UTC),
    )
    assert second["created_count"] == 0
    assert second["updated_count"] == 1
    assert list_propagation_incidents(storage)[0]["id"] == incident_id

    resolved = evaluate_propagation_incidents(
        storage,
        now=datetime(2026, 9, 16, 6, 0, tzinfo=UTC),
    )
    assert resolved["resolved_count"] == 1
    assert resolved["open_incident_count"] == 0
    incident = list_propagation_incidents(storage)[0]
    assert incident["status"] == "resolved"
    assert incident["resolved_at"] == "2026-09-16T06:00:00+00:00"


def test_incidents_detect_coverage_drop_and_delay_spike(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    fast = storage.ensure_endpoint("fast.example.test")
    slow = storage.ensure_endpoint("slow.example.test")

    for index in range(1, 4):
        _add_article(
            storage,
            fast,
            slow,
            index,
            datetime(2026, 9, 4, index, 0, tzinfo=UTC),
            0,
        )
    for index in range(4, 7):
        _add_article(
            storage,
            fast,
            slow,
            index,
            datetime(2026, 9, 9, index, 0, tzinfo=UTC),
            120,
        )

    result = evaluate_propagation_incidents(
        storage,
        now=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
    )
    kinds = {item["kind"] for item in list_propagation_incidents(storage, include_resolved=False)}
    assert "delay_spike" in kinds
    assert "lagging" in kinds
    assert result["open_incident_count"] >= 2

    storage2 = Storage(tmp_path / "coverage.db")
    fast2 = storage2.ensure_endpoint("fast.example.test")
    slow2 = storage2.ensure_endpoint("slow.example.test")
    for index in range(1, 4):
        _add_article(
            storage2,
            fast2,
            slow2,
            index,
            datetime(2026, 9, 4, index, 0, tzinfo=UTC),
            0,
        )
    for index in range(4, 7):
        _add_article(
            storage2,
            fast2,
            slow2,
            index,
            datetime(2026, 9, 9, index, 0, tzinfo=UTC),
            0,
            slow_visible=False,
        )
    evaluate_propagation_incidents(
        storage2,
        now=datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
    )
    coverage = next(
        item
        for item in list_propagation_incidents(storage2, include_resolved=False)
        if item["kind"] == "coverage_drop"
    )
    assert coverage["severity"] == "critical"
    assert coverage["detail"]["coverage_24h_percent"] == 0.0
    assert coverage["detail"]["coverage_7d_percent"] == 50.0
