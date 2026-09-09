from nntpintel.scheduler import run_once
from nntpintel.storage import Storage


def test_scheduler_captures_snapshots_after_measured_campaign(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    calls: list[str] = []

    monkeypatch.setattr(storage, "due_endpoints", lambda now_iso, limit=100: [])
    monkeypatch.setattr("nntpintel.scheduler.run_group_inventories", lambda storage, config=None: 0)
    monkeypatch.setattr("nntpintel.scheduler.run_due_candidate_cycles", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "nntpintel.scheduler.run_due_campaigns",
        lambda storage, limit=2: [
            {"cycle": {"measured_endpoint_count": 1}, "terminal": None}
        ],
    )
    monkeypatch.setattr(
        "nntpintel.scheduler.evaluate_propagation_incidents",
        lambda storage: calls.append("propagation"),
    )
    monkeypatch.setattr(
        "nntpintel.scheduler.evaluate_topology_incidents",
        lambda storage: calls.append("topology"),
    )
    monkeypatch.setattr(
        "nntpintel.scheduler.capture_topology_snapshots",
        lambda storage: calls.append("snapshots"),
    )

    assert run_once(storage) == 0
    assert calls == ["propagation", "topology", "snapshots"]


def test_scheduler_skips_snapshots_without_topology_update(monkeypatch, tmp_path):
    storage = Storage(tmp_path / "nntpintel.db")
    calls: list[str] = []

    monkeypatch.setattr(storage, "due_endpoints", lambda now_iso, limit=100: [])
    monkeypatch.setattr("nntpintel.scheduler.run_group_inventories", lambda storage, config=None: 0)
    monkeypatch.setattr("nntpintel.scheduler.run_due_candidate_cycles", lambda *args, **kwargs: [])
    monkeypatch.setattr("nntpintel.scheduler.run_due_campaigns", lambda storage, limit=2: [])
    monkeypatch.setattr(
        "nntpintel.scheduler.capture_topology_snapshots",
        lambda storage: calls.append("snapshots"),
    )

    assert run_once(storage) == 0
    assert calls == []
