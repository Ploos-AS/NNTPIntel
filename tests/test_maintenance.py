import datetime

import pytest

from nntpintel.maintenance import RetentionPolicy, retention_cutoff


def test_retention_policy_validates_positive_values():
    with pytest.raises(ValueError):
        RetentionPolicy(raw_days=0)
    with pytest.raises(ValueError):
        RetentionPolicy(safety_lag_hours=0)


def test_retention_cutoff_is_utc_and_deterministic():
    now = datetime.datetime(2026, 9, 11, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    cutoff = retention_cutoff(now, RetentionPolicy(raw_days=90))
    assert cutoff == datetime.datetime(2026, 6, 13, 10, 0, tzinfo=datetime.UTC)
