from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nntpintel.candidates import (
    DEFAULT_PROMOTION_FRESHNESS_SECONDS,
    DEFAULT_REQUALIFICATION_AGE_SECONDS,
    list_candidates,
)
from nntpintel.storage import Storage


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def list_candidate_observability(
    storage: Storage,
    *,
    now: datetime | None = None,
    min_reachable: int = 2,
    freshness_seconds: int = DEFAULT_PROMOTION_FRESHNESS_SECONDS,
    requalification_age_seconds: int = DEFAULT_REQUALIFICATION_AGE_SECONDS,
) -> list[dict]:
    if min_reachable < 1:
        raise ValueError("min_reachable must be at least 1")
    current = now or datetime.now(UTC)
    rows = list_candidates(storage)

    with storage.connect() as conn:
        recent_rows = conn.execute(
            """
            SELECT e.server_id, cq.classification, cq.observed_at
            FROM candidate_qualifications cq
            JOIN endpoints e ON e.id = cq.endpoint_id
            ORDER BY cq.observed_at DESC, cq.id DESC
            """
        ).fetchall()

    by_server: dict[int, list] = {}
    for row in recent_rows:
        by_server.setdefault(int(row["server_id"]), []).append(row)

    result: list[dict] = []
    freshness_cutoff = current - timedelta(seconds=freshness_seconds)
    for row in rows:
        item = dict(row)
        server_id = int(item["server_id"])
        history = by_server.get(server_id, [])
        fresh = [entry for entry in history if _as_utc(str(entry["observed_at"])) >= freshness_cutoff]
        recent_reachable_count = sum(1 for entry in fresh if entry["classification"] == "reachable")

        latest_at_raw = item.get("latest_qualified_at")
        if latest_at_raw:
            latest_at = _as_utc(str(latest_at_raw))
            age_seconds = max(0, int((current - latest_at).total_seconds()))
            next_eligible = latest_at + timedelta(seconds=requalification_age_seconds)
            qualification_due = current >= next_eligible
            item["latest_age_seconds"] = age_seconds
            item["next_qualification_at"] = next_eligible.isoformat()
        else:
            qualification_due = True
            item["latest_age_seconds"] = None
            item["next_qualification_at"] = current.isoformat()

        status = str(item["status"])
        latest_recent = fresh[0]["classification"] if fresh else None
        blockers: list[str] = []
        if status != "pending":
            blockers.append(f"status:{status}")
        if recent_reachable_count < min_reachable:
            blockers.append(f"reachable:{recent_reachable_count}/{min_reachable}")
        if latest_recent != "reachable":
            blockers.append(f"latest:{latest_recent or 'none'}")

        item["qualification_due"] = qualification_due
        item["recent_reachable_count"] = recent_reachable_count
        item["promotion_required_reachable"] = min_reachable
        item["promotion_freshness_seconds"] = freshness_seconds
        item["promotion_ready"] = not blockers
        item["promotion_blockers"] = blockers
        result.append(item)
    return result
