from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from statistics import median

from nntpintel.propagation_topology import MIN_TOPOLOGY_CONFIDENCE, MIN_TOPOLOGY_SAMPLES
from nntpintel.storage import Storage


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _snapshot(
    storage: Storage,
    *,
    start: datetime,
    end: datetime,
    min_samples: int,
    min_confidence: float,
) -> dict:
    with storage.connect() as conn:
        target_rows = conn.execute(
            """
            SELECT DISTINCT pc.article_id, s.id AS server_id, s.host
            FROM propagation_campaigns pc
            JOIN propagation_campaign_endpoints pce ON pce.campaign_id = pc.id
            JOIN endpoints e ON e.id = pce.endpoint_id
            JOIN servers s ON s.id = e.server_id
            WHERE pc.created_at >= ? AND pc.created_at < ?
            ORDER BY pc.article_id, s.id
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        visible_rows = conn.execute(
            """
            SELECT po.article_id, s.id AS server_id, s.host,
                   MIN(po.observed_at) AS first_seen_at
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN servers s ON s.id = e.server_id
            JOIN propagation_campaigns pc ON pc.article_id = po.article_id
            WHERE pc.created_at >= ? AND pc.created_at < ?
              AND po.present = 1 AND po.error IS NULL AND po.response_code = 223
            GROUP BY po.article_id, s.id, s.host
            ORDER BY po.article_id, s.id
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    hosts: dict[int, str] = {}
    targets: dict[int, set[int]] = defaultdict(set)
    first_seen: dict[int, dict[int, datetime]] = defaultdict(dict)
    for row in target_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        hosts[server_id] = str(row["host"])
        targets[article_id].add(server_id)
    for row in visible_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        hosts[server_id] = str(row["host"])
        first_seen[article_id][server_id] = _as_utc(str(row["first_seen_at"]))

    samples: dict[tuple[int, int], list[float]] = defaultdict(list)
    for article_id, article_targets in targets.items():
        visible = first_seen.get(article_id, {})
        present = sorted(article_targets & set(visible))
        for left, right in combinations(present, 2):
            samples[(left, right)].append(
                round((visible[right] - visible[left]).total_seconds(), 3)
            )

    edges: list[dict] = []
    for (left, right), deltas in samples.items():
        left_first = sum(value > 0 for value in deltas)
        right_first = sum(value < 0 for value in deltas)
        ties = sum(value == 0 for value in deltas)
        directional = left_first + right_first
        if directional < min_samples:
            continue
        if left_first >= right_first:
            source, target = left, right
            forward, reverse = left_first, right_first
            oriented = deltas
        else:
            source, target = right, left
            forward, reverse = right_first, left_first
            oriented = [-value for value in deltas]
        confidence = round(forward / directional, 3)
        if confidence < min_confidence:
            continue
        edges.append(
            {
                "source_server_id": source,
                "source_host": hosts[source],
                "target_server_id": target,
                "target_host": hosts[target],
                "sample_count": len(deltas),
                "directional_sample_count": directional,
                "forward_count": forward,
                "reverse_count": reverse,
                "tie_count": ties,
                "confidence": confidence,
                "median_lead_seconds": round(float(median(oriented)), 3),
            }
        )
    edges.sort(key=lambda item: (item["source_host"], item["target_host"]))
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "article_count": len(targets),
        "edge_count": len(edges),
        "edges": edges,
    }


def topology_history(
    storage: Storage,
    *,
    now: datetime | None = None,
    days: int = 30,
    min_samples: int = MIN_TOPOLOGY_SAMPLES,
    min_confidence: float = MIN_TOPOLOGY_CONFIDENCE,
) -> dict:
    if days < 2 or days > 90:
        raise ValueError("topology history days must be between 2 and 90")
    if min_samples < 1:
        raise ValueError("topology min_samples must be at least 1")
    if not 0.5 <= min_confidence <= 1.0:
        raise ValueError("topology min_confidence must be between 0.5 and 1.0")

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    day_end = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    snapshots = []
    for offset in range(days - 1, -1, -1):
        start = day_end - timedelta(days=offset + 1)
        end = start + timedelta(days=1)
        snapshots.append(
            _snapshot(
                storage,
                start=start,
                end=end,
                min_samples=min_samples,
                min_confidence=min_confidence,
            )
        )

    events: list[dict] = []
    previous: dict[tuple[int, int], dict] = {}
    stability: dict[tuple[int, int], dict] = {}
    for snapshot in snapshots:
        current_edges = {
            (int(edge["source_server_id"]), int(edge["target_server_id"])): edge
            for edge in snapshot["edges"]
        }
        for key, edge in current_edges.items():
            state = stability.setdefault(
                key,
                {
                    "source_server_id": key[0],
                    "source_host": edge["source_host"],
                    "target_server_id": key[1],
                    "target_host": edge["target_host"],
                    "observed_days": 0,
                    "confidence_values": [],
                },
            )
            state["observed_days"] += 1
            state["confidence_values"].append(float(edge["confidence"]))
            if key not in previous:
                events.append({"at": snapshot["start"], "event": "appeared", **edge})
            else:
                old = previous[key]
                if (
                    old["confidence"] != edge["confidence"]
                    or old["median_lead_seconds"] != edge["median_lead_seconds"]
                ):
                    events.append(
                        {
                            "at": snapshot["start"],
                            "event": "changed",
                            **edge,
                            "previous_confidence": old["confidence"],
                            "previous_median_lead_seconds": old["median_lead_seconds"],
                        }
                    )
        for key, edge in previous.items():
            if key not in current_edges:
                events.append({"at": snapshot["start"], "event": "disappeared", **edge})
        previous = current_edges

    stable_edges = []
    for state in stability.values():
        values = state.pop("confidence_values")
        stable_edges.append(
            {
                **state,
                "stability_percent": round((state["observed_days"] / days) * 100, 2),
                "median_confidence": round(float(median(values)), 3),
                "latest_present": (
                    (state["source_server_id"], state["target_server_id"]) in previous
                ),
            }
        )
    stable_edges.sort(key=lambda item: (-item["observed_days"], item["source_host"], item["target_host"]))

    return {
        "model": "inferred_observed_propagation_precedence_history",
        "authoritative_topology": False,
        "disclaimer": (
            "History tracks changes in inferred observed first-seen precedence only; "
            "it does not prove direct NNTP peering or feed relationships."
        ),
        "days": days,
        "min_samples": min_samples,
        "min_confidence": min_confidence,
        "snapshots": snapshots,
        "events": events,
        "edges": stable_edges,
    }
