from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from nntpintel.propagation import normalize_message_id, propagation_summary
from nntpintel.propagation_probe import PresenceProbeResult, probe_and_record_presence, stat_message_id
from nntpintel.storage import Storage

MIN_PROPAGATION_INTERVAL_SECONDS = 60
MAX_PROPAGATION_INTERVAL_SECONDS = 86400
MAX_PROPAGATION_ENDPOINTS = 10
MAX_PROPAGATION_BACKOFF_SECONDS = 21600


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _endpoint_state(storage: Storage, message_id: str, endpoint_id: int) -> tuple[str | None, int]:
    with storage.connect() as conn:
        article = conn.execute(
            "SELECT id FROM propagation_articles WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if article is None:
            raise ValueError(f"unknown propagation article: {message_id}")
        rows = conn.execute(
            """
            SELECT observed_at, error
            FROM propagation_observations
            WHERE article_id = ? AND endpoint_id = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 16
            """,
            (article["id"], endpoint_id),
        ).fetchall()
    if not rows:
        return None, 0
    failures = 0
    for row in rows:
        if row["error"] is None:
            break
        failures += 1
    return str(rows[0]["observed_at"]), failures


def due_propagation_endpoints(
    storage: Storage,
    message_id: str,
    endpoint_ids: Sequence[int],
    *,
    interval_seconds: int = 300,
    max_backoff_seconds: int = MAX_PROPAGATION_BACKOFF_SECONDS,
    now: datetime | None = None,
) -> list[int]:
    message_id = normalize_message_id(message_id)
    unique_ids = list(dict.fromkeys(int(endpoint_id) for endpoint_id in endpoint_ids))
    if not unique_ids:
        raise ValueError("at least one endpoint is required")
    if len(unique_ids) > MAX_PROPAGATION_ENDPOINTS:
        raise ValueError(f"at most {MAX_PROPAGATION_ENDPOINTS} propagation endpoints are allowed per cycle")
    if interval_seconds < MIN_PROPAGATION_INTERVAL_SECONDS or interval_seconds > MAX_PROPAGATION_INTERVAL_SECONDS:
        raise ValueError(
            f"propagation interval must be between {MIN_PROPAGATION_INTERVAL_SECONDS} "
            f"and {MAX_PROPAGATION_INTERVAL_SECONDS} seconds"
        )
    if max_backoff_seconds < interval_seconds:
        raise ValueError("maximum propagation backoff must not be less than the interval")

    current = now or datetime.now(UTC)
    due: list[int] = []
    with storage.connect() as conn:
        valid = {
            int(row["id"])
            for row in conn.execute(
                """
                SELECT e.id
                FROM endpoints e
                JOIN servers s ON s.id = e.server_id
                WHERE e.enabled = 1 AND s.enabled = 1
                """
            ).fetchall()
        }
    for endpoint_id in unique_ids:
        if endpoint_id not in valid:
            raise ValueError(f"unknown or disabled endpoint: {endpoint_id}")
        last_at, failures = _endpoint_state(storage, message_id, endpoint_id)
        if last_at is None:
            due.append(endpoint_id)
            continue
        delay = interval_seconds
        if failures:
            delay = min(interval_seconds * (2 ** min(failures, 8)), max_backoff_seconds)
        if current >= _as_utc(last_at) + timedelta(seconds=delay):
            due.append(endpoint_id)
    return due


def run_propagation_cycle(
    storage: Storage,
    message_id: str,
    endpoint_ids: Sequence[int],
    *,
    interval_seconds: int = 300,
    timeout: float = 5.0,
    max_backoff_seconds: int = MAX_PROPAGATION_BACKOFF_SECONDS,
    now: datetime | None = None,
    probe_func: Callable[..., PresenceProbeResult] = stat_message_id,
) -> dict:
    if timeout <= 0 or timeout > 15:
        raise ValueError("timeout must be greater than zero and at most 15 seconds")
    message_id = normalize_message_id(message_id)
    due = due_propagation_endpoints(
        storage,
        message_id,
        endpoint_ids,
        interval_seconds=interval_seconds,
        max_backoff_seconds=max_backoff_seconds,
        now=now,
    )
    results: list[dict] = []
    for endpoint_id in due:
        results.append(
            probe_and_record_presence(
                storage,
                endpoint_id,
                message_id,
                timeout=timeout,
                probe_func=probe_func,
            )
        )
    return {
        "message_id": message_id,
        "requested_endpoint_count": len(dict.fromkeys(int(item) for item in endpoint_ids)),
        "due_endpoint_count": len(due),
        "measured_endpoint_count": len(results),
        "results": results,
        "summary": propagation_summary(storage, message_id),
    }
