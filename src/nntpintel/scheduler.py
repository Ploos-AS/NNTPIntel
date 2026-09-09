from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nntpintel.cycle import run_due_candidate_cycles
from nntpintel.groups import inventory_groups
from nntpintel.probe import probe
from nntpintel.propagation_campaigns import run_due_campaigns
from nntpintel.propagation_incidents import evaluate_propagation_incidents
from nntpintel.storage import Storage


@dataclass(slots=True)
class SchedulerConfig:
    poll_seconds: float = 5.0
    batch_size: int = 20
    group_batch_size: int = 5
    cycle_batch_size: int = 1
    campaign_batch_size: int = 2
    max_backoff_seconds: int = 21600
    max_cycle_backoff_seconds: int = 86400


def _next_probe_time(
    *,
    now: datetime,
    interval_seconds: int,
    consecutive_failures: int,
    max_backoff_seconds: int,
) -> datetime:
    if consecutive_failures <= 0:
        delay = interval_seconds
    else:
        delay = min(interval_seconds * (2 ** min(consecutive_failures, 8)), max_backoff_seconds)
    return now + timedelta(seconds=delay)


def run_group_inventories(storage: Storage, *, config: SchedulerConfig | None = None) -> int:
    config = config or SchedulerConfig()
    now = datetime.now(UTC)
    rows = storage.due_group_endpoints(now.isoformat(), limit=config.group_batch_size)
    completed = 0

    for row in rows:
        last_inventory_at = row["last_inventory_at"]
        since = datetime.fromisoformat(last_inventory_at) if last_inventory_at else None
        inventory = inventory_groups(
            row["host"],
            port=int(row["port"]),
            implicit_tls=row["transport"] == "tls",
            starttls=bool(row["starttls"]),
            timeout=float(row["timeout_seconds"]),
            newgroups_since=since,
        )
        if inventory.error is None:
            storage.record_group_inventory(int(row["id"]), inventory)

        finished = datetime.now(UTC)
        next_at = finished + timedelta(seconds=int(row["group_interval_seconds"]))
        storage.update_group_schedule(
            int(row["id"]),
            last_inventory_at=finished.isoformat(),
            next_inventory_at=next_at.isoformat(),
        )
        completed += 1

    return completed


def run_once(storage: Storage, *, config: SchedulerConfig | None = None) -> int:
    config = config or SchedulerConfig()
    now = datetime.now(UTC)
    rows = storage.due_endpoints(now.isoformat(), limit=config.batch_size)

    completed = 0
    for row in rows:
        implicit_tls = row["transport"] == "tls"
        observation = probe(
            row["host"],
            port=row["port"],
            implicit_tls=implicit_tls,
            starttls=bool(row["starttls"]),
            timeout=float(row["timeout_seconds"]),
        )
        storage.record_observation(int(row["id"]), observation)

        failures = int(row["consecutive_failures"])
        failures = 0 if observation.error is None else failures + 1
        finished = datetime.now(UTC)
        next_at = _next_probe_time(
            now=finished,
            interval_seconds=int(row["interval_seconds"]),
            consecutive_failures=failures,
            max_backoff_seconds=config.max_backoff_seconds,
        )
        storage.update_schedule(
            int(row["id"]),
            last_probe_at=finished.isoformat(),
            next_probe_at=next_at.isoformat(),
            consecutive_failures=failures,
        )
        completed += 1

    run_group_inventories(storage, config=config)
    run_due_candidate_cycles(
        storage,
        limit=config.cycle_batch_size,
        max_backoff_seconds=config.max_cycle_backoff_seconds,
    )
    campaign_runs = run_due_campaigns(storage, limit=config.campaign_batch_size)
    if any(
        (row["cycle"] is not None and int(row["cycle"]["measured_endpoint_count"]) > 0)
        or row["terminal"] is not None
        for row in campaign_runs
    ):
        evaluate_propagation_incidents(storage)
    return completed


def run_forever(storage: Storage, *, config: SchedulerConfig | None = None) -> None:
    config = config or SchedulerConfig()
    while True:
        run_once(storage, config=config)
        time.sleep(config.poll_seconds)
