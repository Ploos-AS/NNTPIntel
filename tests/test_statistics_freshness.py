from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nntpintel.statistics_freshness import rollup_freshness_token


class _Connection:
    def __init__(self, values):
        self.values = iter(values)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        assert "MAX(generated_at)" in query
        value = next(self.values)
        return _Result(value)


class _Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return {"generated_at": self.value}


class _Storage:
    backend_name = "postgresql"

    def __init__(self, values):
        self.values = values

    def connect(self):
        return _Connection(self.values)


def test_freshness_token_changes_with_generated_at():
    first = rollup_freshness_token(
        _Storage([datetime(2026, 9, 16, 8, tzinfo=timezone.utc)]), "servers"
    )
    second = rollup_freshness_token(
        _Storage([datetime(2026, 9, 16, 9, tzinfo=timezone.utc)]), "servers"
    )
    assert first != second
    assert "2026-09-16T08:00:00Z" in first


def test_freshness_token_covers_all_family_tables():
    token = rollup_freshness_token(_Storage([None, None, None]), "propagation")
    assert "server_propagation_rollups=empty" in token
    assert "server_propagation_value_rollups=empty" in token
    assert "propagation_campaign_rollups=empty" in token


def test_freshness_rejects_unknown_family():
    with pytest.raises(ValueError, match="unknown statistics rollup family"):
        rollup_freshness_token(_Storage([]), "unknown")
