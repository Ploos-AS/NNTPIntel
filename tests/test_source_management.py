# ruff: noqa: I001
from nntpintel.cycle import configure_cycle_schedule, list_cycle_schedules
from nntpintel.discovery import import_seeds
from nntpintel.source_management import (
    list_source_management,
    set_cycle_schedule_enabled,
    set_source_enabled,
)
from nntpintel.source_web import sources_page
from nntpintel.storage import Storage


SOURCE = "vivil-open-nntp"


def _storage(tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    import_seeds(storage, ["news.example.test"], source=SOURCE)
    configure_cycle_schedule(
        storage,
        SOURCE,
        interval_seconds=43200,
        candidate_limit=4,
        timeout_seconds=7.0,
    )
    return storage


def test_source_management_combines_discovery_and_schedule_state(tmp_path):
    storage = _storage(tmp_path)
    row = list_source_management(storage)[0]
    assert row["name"] == SOURCE
    assert row["enabled"] == 1
    assert row["schedule_enabled"] == 1
    assert row["interval_seconds"] == 43200
    assert row["candidate_limit"] == 4
    assert row["timeout_seconds"] == 7.0
    assert row["consecutive_failures"] == 0


def test_source_and_schedule_toggles_are_independent(tmp_path):
    storage = _storage(tmp_path)

    set_source_enabled(storage, SOURCE, False)
    row = list_source_management(storage)[0]
    assert row["enabled"] == 0
    assert row["schedule_enabled"] == 1

    before = list_cycle_schedules(storage)[0]
    set_cycle_schedule_enabled(storage, SOURCE, False)
    after = list_cycle_schedules(storage)[0]
    assert after["enabled"] == 0
    assert after["interval_seconds"] == before["interval_seconds"]
    assert after["candidate_limit"] == before["candidate_limit"]
    assert after["timeout_seconds"] == before["timeout_seconds"]
    assert after["next_cycle_at"] == before["next_cycle_at"]

    set_source_enabled(storage, SOURCE, True)
    set_cycle_schedule_enabled(storage, SOURCE, True, run_now=True)
    row = list_source_management(storage)[0]
    assert row["enabled"] == 1
    assert row["schedule_enabled"] == 1


def test_source_management_web_displays_schedule_health(tmp_path):
    storage = _storage(tmp_path)
    html = sources_page(storage)
    assert "Discovery source management" in html
    assert SOURCE in html
    assert "43200" in html
    assert "Failures" in html
