from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nntpintel.probe import probe
from nntpintel.storage import Storage


@dataclass(slots=True)
class SchedulerConfig:
    poll_seconds: float = 5.0
    batch_size: int = 20
    max_backoff_seconds: int = 21600


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

    return completed


def run_forever(storage: Storage, *, config: SchedulerConfig | None = None) -> None:
    config = config or SchedulerConfig()
    while True:
        run_once(storage, config=config)
        time.sleep(config.poll_seconds)
