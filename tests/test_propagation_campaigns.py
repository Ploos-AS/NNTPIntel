from datetime import UTC, datetime, timedelta

import pytest

from nntpintel.propagation_campaigns import (
    create_campaign,
    get_campaign,
    list_campaigns,
    run_campaign,
    run_due_campaigns,
    set_campaign_enabled,
)
from nntpintel.propagation_probe import PresenceProbeResult
from nntpintel.storage import Storage


def _result(host: str, message_id: str, *, present: bool, observed_at: str) -> PresenceProbeResult:
    return PresenceProbeResult(
        observed_at=observed_at,
        host=host,
        port=119,
        transport="tcp",
        message_id=message_id,
        present=present,
        response_code=223 if present else 430,
        response=None,
        error=None,
    )


def test_campaign_persists_explicit_targets_and_bounds(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = storage.ensure_endpoint("news-a.example.test")
    second = storage.ensure_endpoint("news-b.example.test")
    now = datetime(2026, 9, 9, 4, 0, tzinfo=UTC)

    campaign = create_campaign(
        storage,
        "<campaign@example.test>",
        [first, second, first],
        interval_seconds=300,
        ttl_seconds=3600,
        stop_after_visible=2,
        now=now,
    )

    assert campaign["status"] == "active"
    assert campaign["endpoint_ids"] == [first, second]
    assert campaign["stop_after_visible"] == 2
    assert campaign["expires_at"] == (now + timedelta(seconds=3600)).isoformat()
    assert list_campaigns(storage, status="active")[0]["id"] == campaign["id"]

    with pytest.raises(ValueError, match="already exists"):
        create_campaign(storage, "<campaign@example.test>", [first], now=now)


def test_campaign_completes_when_visibility_target_is_reached(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    first = storage.ensure_endpoint("news-a.example.test")
    second = storage.ensure_endpoint("news-b.example.test")
    message_id = "<complete@example.test>"
    now = datetime(2026, 9, 9, 4, 0, tzinfo=UTC)
    campaign = create_campaign(
        storage,
        message_id,
        [first, second],
        stop_after_visible=2,
        now=now,
    )

    calls = []

    def probe(host, current_message_id, **kwargs):
        calls.append(host)
        return _result(
            host,
            current_message_id,
            present=True,
            observed_at=(now + timedelta(seconds=len(calls))).isoformat(),
        )

    result = run_campaign(storage, campaign["id"], now=now, probe_func=probe)
    assert result["terminal"] == "completed"
    assert result["cycle"]["summary"]["visible_endpoint_count"] == 2
    assert get_campaign(storage, campaign["id"])["status"] == "completed"

    second_run = run_campaign(storage, campaign["id"], now=now + timedelta(minutes=5), probe_func=probe)
    assert second_run["cycle"] is None
    assert len(calls) == 2


def test_campaign_expires_without_probing_after_ttl(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")
    start = datetime(2026, 9, 9, 4, 0, tzinfo=UTC)
    campaign = create_campaign(
        storage,
        "<expire@example.test>",
        [endpoint_id],
        ttl_seconds=300,
        now=start,
    )

    def should_not_probe(*args, **kwargs):
        raise AssertionError("expired campaign must not probe")

    result = run_campaign(
        storage,
        campaign["id"],
        now=start + timedelta(seconds=300),
        probe_func=should_not_probe,
    )
    assert result["terminal"] == "expired"
    assert result["cycle"] is None
    assert result["campaign"]["status"] == "expired"


def test_disabled_campaign_is_not_run_by_scheduler_pass(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")
    now = datetime(2026, 9, 9, 4, 0, tzinfo=UTC)
    campaign = create_campaign(storage, "<disabled@example.test>", [endpoint_id], now=now)
    disabled = set_campaign_enabled(storage, campaign["id"], False)
    assert disabled["status"] == "disabled"

    def should_not_probe(*args, **kwargs):
        raise AssertionError("disabled campaign must not probe")

    assert run_due_campaigns(storage, now=now, probe_func=should_not_probe) == []
    enabled = set_campaign_enabled(storage, campaign["id"], True)
    assert enabled["status"] == "active"


def test_campaign_endpoint_and_ttl_limits_are_conservative(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoints = [storage.ensure_endpoint(f"news-{index}.example.test") for index in range(11)]
    now = datetime(2026, 9, 9, 4, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="at most 10"):
        create_campaign(storage, "<too-many@example.test>", endpoints, now=now)
    with pytest.raises(ValueError, match="TTL"):
        create_campaign(storage, "<too-short@example.test>", endpoints[:1], ttl_seconds=60, now=now)
