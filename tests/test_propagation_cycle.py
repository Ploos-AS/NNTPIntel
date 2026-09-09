from datetime import UTC, datetime

import pytest

from nntpintel.propagation import register_article
from nntpintel.propagation_cycle import due_propagation_endpoints, run_propagation_cycle
from nntpintel.propagation_probe import PresenceProbeResult
from nntpintel.storage import Storage


def _result(host: str, message_id: str, *, present: bool, observed_at: str, error: str | None = None):
    return PresenceProbeResult(
        observed_at=observed_at,
        host=host,
        port=119,
        transport="tcp",
        message_id=message_id,
        present=present,
        response_code=223 if present else 430 if error is None else None,
        response=None,
        error=error,
    )


def test_cycle_measures_only_due_endpoints_and_observes_transition(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    a = storage.ensure_endpoint("news-a.example.test")
    b = storage.ensure_endpoint("news-b.example.test")
    message_id = "<cycle@example.test>"
    register_article(storage, message_id)

    calls: list[str] = []
    results = iter(
        [
            _result("news-a.example.test", message_id, present=False, observed_at="2026-09-09T03:00:00+00:00"),
            _result("news-b.example.test", message_id, present=True, observed_at="2026-09-09T03:00:01+00:00"),
            _result("news-a.example.test", message_id, present=True, observed_at="2026-09-09T03:05:00+00:00"),
            _result("news-b.example.test", message_id, present=True, observed_at="2026-09-09T03:05:01+00:00"),
        ]
    )

    def fake_probe(host, message_id, **kwargs):
        calls.append(host)
        return next(results)

    first = run_propagation_cycle(
        storage,
        message_id,
        [a, b],
        interval_seconds=300,
        now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        probe_func=fake_probe,
    )
    assert first["measured_endpoint_count"] == 2
    assert first["summary"]["visible_endpoint_count"] == 1

    not_due = run_propagation_cycle(
        storage,
        message_id,
        [a, b],
        interval_seconds=300,
        now=datetime(2026, 9, 9, 3, 4, 59, tzinfo=UTC),
        probe_func=fake_probe,
    )
    assert not_due["measured_endpoint_count"] == 0

    second = run_propagation_cycle(
        storage,
        message_id,
        [a, b],
        interval_seconds=300,
        now=datetime(2026, 9, 9, 3, 5, 2, tzinfo=UTC),
        probe_func=fake_probe,
    )
    assert second["measured_endpoint_count"] == 2
    assert second["summary"]["visible_endpoint_count"] == 2
    assert calls == ["news-a.example.test", "news-b.example.test", "news-a.example.test", "news-b.example.test"]


def test_cycle_applies_exponential_backoff_only_to_probe_errors(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")
    message_id = "<backoff@example.test>"
    register_article(storage, message_id)

    def failed_probe(host, message_id, **kwargs):
        return _result(
            host,
            message_id,
            present=False,
            observed_at="2026-09-09T03:00:00+00:00",
            error="TimeoutError: timed out",
        )

    run_propagation_cycle(
        storage,
        message_id,
        [endpoint_id],
        interval_seconds=300,
        now=datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        probe_func=failed_probe,
    )

    assert due_propagation_endpoints(
        storage,
        message_id,
        [endpoint_id],
        interval_seconds=300,
        now=datetime(2026, 9, 9, 3, 9, 59, tzinfo=UTC),
    ) == []
    assert due_propagation_endpoints(
        storage,
        message_id,
        [endpoint_id],
        interval_seconds=300,
        now=datetime(2026, 9, 9, 3, 10, tzinfo=UTC),
    ) == [endpoint_id]


def test_cycle_enforces_conservative_bounds_and_enabled_endpoints(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    endpoint_id = storage.ensure_endpoint("news.example.test")
    message_id = "<bounds@example.test>"
    register_article(storage, message_id)

    with pytest.raises(ValueError, match="at least one"):
        due_propagation_endpoints(storage, message_id, [])
    with pytest.raises(ValueError, match="between 60 and 86400"):
        due_propagation_endpoints(storage, message_id, [endpoint_id], interval_seconds=30)
    with pytest.raises(ValueError, match="at most 10"):
        due_propagation_endpoints(storage, message_id, list(range(1, 12)))

    with storage.connect() as conn:
        conn.execute("UPDATE endpoints SET enabled = 0 WHERE id = ?", (endpoint_id,))
        conn.commit()
    with pytest.raises(ValueError, match="unknown or disabled endpoint"):
        due_propagation_endpoints(storage, message_id, [endpoint_id])
