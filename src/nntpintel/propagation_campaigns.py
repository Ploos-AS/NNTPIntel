from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from nntpintel.propagation import normalize_message_id, register_article
from nntpintel.propagation_cycle import (
    MAX_PROPAGATION_BACKOFF_SECONDS,
    MAX_PROPAGATION_ENDPOINTS,
    MAX_PROPAGATION_INTERVAL_SECONDS,
    MIN_PROPAGATION_INTERVAL_SECONDS,
    run_propagation_cycle,
)
from nntpintel.propagation_probe import PresenceProbeResult, stat_message_id
from nntpintel.storage import SCHEMA_VERSION, Storage

MIN_CAMPAIGN_TTL_SECONDS = 300
MAX_CAMPAIGN_TTL_SECONDS = 604800
MAX_CAMPAIGNS_PER_SCHEDULER_PASS = 5


def ensure_campaign_schema(storage: Storage) -> None:
    """Verify that the central Storage schema owns the campaign tables."""
    with storage.connect() as conn:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None or int(row["version"]) != SCHEMA_VERSION:
        raise RuntimeError("propagation campaign schema is not initialized")


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def create_campaign(
    storage: Storage,
    message_id: str,
    endpoint_ids: Sequence[int],
    *,
    interval_seconds: int = 300,
    timeout_seconds: float = 5.0,
    max_backoff_seconds: int = MAX_PROPAGATION_BACKOFF_SECONDS,
    ttl_seconds: int = 86400,
    stop_after_visible: int | None = None,
    now: datetime | None = None,
) -> dict:
    ensure_campaign_schema(storage)
    message_id = normalize_message_id(message_id)
    endpoint_ids = list(dict.fromkeys(int(item) for item in endpoint_ids))
    if not endpoint_ids:
        raise ValueError("at least one campaign endpoint is required")
    if len(endpoint_ids) > MAX_PROPAGATION_ENDPOINTS:
        raise ValueError(f"at most {MAX_PROPAGATION_ENDPOINTS} campaign endpoints are allowed")
    if not MIN_PROPAGATION_INTERVAL_SECONDS <= interval_seconds <= MAX_PROPAGATION_INTERVAL_SECONDS:
        raise ValueError(
            f"campaign interval must be between {MIN_PROPAGATION_INTERVAL_SECONDS} "
            f"and {MAX_PROPAGATION_INTERVAL_SECONDS} seconds"
        )
    if timeout_seconds <= 0 or timeout_seconds > 15:
        raise ValueError("campaign timeout must be greater than zero and at most 15 seconds")
    if max_backoff_seconds < interval_seconds:
        raise ValueError("campaign maximum backoff must not be less than the interval")
    if not MIN_CAMPAIGN_TTL_SECONDS <= ttl_seconds <= MAX_CAMPAIGN_TTL_SECONDS:
        raise ValueError(
            f"campaign TTL must be between {MIN_CAMPAIGN_TTL_SECONDS} "
            f"and {MAX_CAMPAIGN_TTL_SECONDS} seconds"
        )
    target = len(endpoint_ids) if stop_after_visible is None else int(stop_after_visible)
    if target < 1 or target > len(endpoint_ids):
        raise ValueError("stop_after_visible must be between 1 and the endpoint count")

    current = now or datetime.now(UTC)
    expires_at = current + timedelta(seconds=ttl_seconds)
    article_id = register_article(storage, message_id)

    with storage.connect() as conn:
        enabled = {
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
        for endpoint_id in endpoint_ids:
            if endpoint_id not in enabled:
                raise ValueError(f"unknown or disabled endpoint: {endpoint_id}")
        existing = conn.execute(
            "SELECT id FROM propagation_campaigns WHERE article_id = ? AND status = 'active'",
            (article_id,),
        ).fetchone()
        if existing is not None:
            raise ValueError(f"active campaign already exists for {message_id}")
        cursor = conn.execute(
            """
            INSERT INTO propagation_campaigns(
                article_id, status, interval_seconds, timeout_seconds,
                max_backoff_seconds, stop_after_visible, created_at, expires_at
            ) VALUES (?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                interval_seconds,
                timeout_seconds,
                max_backoff_seconds,
                target,
                current.isoformat(),
                expires_at.isoformat(),
            ),
        )
        campaign_id = int(cursor.lastrowid)
        conn.executemany(
            "INSERT INTO propagation_campaign_endpoints(campaign_id, endpoint_id) VALUES (?, ?)",
            [(campaign_id, endpoint_id) for endpoint_id in endpoint_ids],
        )
        conn.commit()

    return get_campaign(storage, campaign_id)


def get_campaign(storage: Storage, campaign_id: int) -> dict:
    ensure_campaign_schema(storage)
    with storage.connect() as conn:
        row = conn.execute(
            """
            SELECT pc.*, pa.message_id
            FROM propagation_campaigns pc
            JOIN propagation_articles pa ON pa.id = pc.article_id
            WHERE pc.id = ?
            """,
            (campaign_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown propagation campaign: {campaign_id}")
        endpoint_ids = [
            int(item["endpoint_id"])
            for item in conn.execute(
                """
                SELECT endpoint_id FROM propagation_campaign_endpoints
                WHERE campaign_id = ? ORDER BY endpoint_id
                """,
                (campaign_id,),
            ).fetchall()
        ]
    result = dict(row)
    result["endpoint_ids"] = endpoint_ids
    return result


def list_campaigns(storage: Storage, *, status: str | None = None, limit: int = 100) -> list[dict]:
    ensure_campaign_schema(storage)
    if limit < 1 or limit > 1000:
        raise ValueError("campaign list limit must be between 1 and 1000")
    if status is not None and status not in {"active", "completed", "expired", "disabled"}:
        raise ValueError("invalid campaign status")
    with storage.connect() as conn:
        if status is None:
            rows = conn.execute(
                """
                SELECT pc.id FROM propagation_campaigns pc
                ORDER BY pc.created_at DESC, pc.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT pc.id FROM propagation_campaigns pc
                WHERE pc.status = ?
                ORDER BY pc.created_at DESC, pc.id DESC LIMIT ?
                """,
                (status, limit),
            ).fetchall()
    return [get_campaign(storage, int(row["id"])) for row in rows]


def set_campaign_enabled(storage: Storage, campaign_id: int, enabled: bool) -> dict:
    ensure_campaign_schema(storage)
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT status FROM propagation_campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown propagation campaign: {campaign_id}")
        status = str(row["status"])
        if status in {"completed", "expired"}:
            raise ValueError(f"cannot change terminal campaign status: {status}")
        conn.execute(
            "UPDATE propagation_campaigns SET status = ? WHERE id = ?",
            ("active" if enabled else "disabled", campaign_id),
        )
        conn.commit()
    return get_campaign(storage, campaign_id)


def run_campaign(
    storage: Storage,
    campaign_id: int,
    *,
    now: datetime | None = None,
    probe_func: Callable[..., PresenceProbeResult] = stat_message_id,
) -> dict:
    campaign = get_campaign(storage, campaign_id)
    if campaign["status"] != "active":
        return {"campaign": campaign, "cycle": None, "terminal": campaign["status"]}

    current = now or datetime.now(UTC)
    if current >= _as_utc(str(campaign["expires_at"])):
        with storage.connect() as conn:
            conn.execute(
                "UPDATE propagation_campaigns SET status = 'expired', completed_at = ? WHERE id = ?",
                (current.isoformat(), campaign_id),
            )
            conn.commit()
        campaign = get_campaign(storage, campaign_id)
        return {"campaign": campaign, "cycle": None, "terminal": "expired"}

    cycle = run_propagation_cycle(
        storage,
        str(campaign["message_id"]),
        campaign["endpoint_ids"],
        interval_seconds=int(campaign["interval_seconds"]),
        timeout=float(campaign["timeout_seconds"]),
        max_backoff_seconds=int(campaign["max_backoff_seconds"]),
        now=current,
        probe_func=probe_func,
    )
    visible = int(cycle["summary"]["visible_endpoint_count"])
    terminal = None
    if visible >= int(campaign["stop_after_visible"]):
        terminal = "completed"
        with storage.connect() as conn:
            conn.execute(
                "UPDATE propagation_campaigns SET status = 'completed', completed_at = ? WHERE id = ?",
                (current.isoformat(), campaign_id),
            )
            conn.commit()
    return {"campaign": get_campaign(storage, campaign_id), "cycle": cycle, "terminal": terminal}


def run_due_campaigns(
    storage: Storage,
    *,
    limit: int = MAX_CAMPAIGNS_PER_SCHEDULER_PASS,
    now: datetime | None = None,
    probe_func: Callable[..., PresenceProbeResult] = stat_message_id,
) -> list[dict]:
    ensure_campaign_schema(storage)
    if limit < 1 or limit > MAX_CAMPAIGNS_PER_SCHEDULER_PASS:
        raise ValueError(
            f"campaign scheduler limit must be between 1 and {MAX_CAMPAIGNS_PER_SCHEDULER_PASS}"
        )
    current = now or datetime.now(UTC)
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT id FROM propagation_campaigns
            WHERE status = 'active'
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        run_campaign(storage, int(row["id"]), now=current, probe_func=probe_func)
        for row in rows
    ]
