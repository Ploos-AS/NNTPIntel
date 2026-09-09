from datetime import UTC, datetime, timedelta

from nntpintel.probe import ProbeObservation
from nntpintel.scheduler import _next_probe_time
from nntpintel.storage import Storage


def test_storage_creates_endpoint_and_records_observation(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test", interval_seconds=60)

    observation = ProbeObservation(
        observed_at=datetime.now(UTC).isoformat(),
        host="news.example.test",
        port=119,
        transport="tcp",
        greeting_code=200,
        greeting="200 test server",
        posting_allowed=True,
        capabilities=["VERSION 2", "READER"],
        mode_reader_code=200,
        mode_reader_response="200 reader mode",
    )
    storage.record_observation(endpoint_id, observation)

    assert storage.observation_count() == 1
    endpoints = list(storage.list_endpoints())
    assert len(endpoints) == 1
    assert endpoints[0]["host"] == "news.example.test"


def test_due_endpoint_is_returned(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    storage.ensure_endpoint("news.example.test")

    due = storage.due_endpoints(datetime.now(UTC).isoformat())
    assert len(due) == 1
    assert due[0]["host"] == "news.example.test"


def test_success_schedule_uses_base_interval():
    now = datetime(2026, 9, 9, tzinfo=UTC)
    result = _next_probe_time(
        now=now,
        interval_seconds=60,
        consecutive_failures=0,
        max_backoff_seconds=3600,
    )
    assert result == now + timedelta(seconds=60)


def test_failure_schedule_uses_exponential_backoff_and_cap():
    now = datetime(2026, 9, 9, tzinfo=UTC)
    result = _next_probe_time(
        now=now,
        interval_seconds=60,
        consecutive_failures=3,
        max_backoff_seconds=3600,
    )
    assert result == now + timedelta(seconds=480)

    capped = _next_probe_time(
        now=now,
        interval_seconds=60,
        consecutive_failures=20,
        max_backoff_seconds=3600,
    )
    assert capped == now + timedelta(seconds=3600)
