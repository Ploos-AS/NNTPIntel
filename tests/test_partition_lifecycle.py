import datetime

import pytest

from nntpintel.partition_lifecycle import monthly_partition_name


def test_monthly_partition_name_is_stable_and_utc():
    value = datetime.datetime(
        2026,
        10,
        31,
        23,
        0,
        tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
    )
    assert monthly_partition_name("observations", value) == "observations_2026_10"


def test_monthly_partition_name_rejects_unknown_table():
    with pytest.raises(ValueError, match="unsupported partitioned table"):
        monthly_partition_name("unknown", datetime.datetime.now(datetime.UTC))
