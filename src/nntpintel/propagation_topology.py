from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from statistics import median

from nntpintel.storage import Storage

MIN_TOPOLOGY_SAMPLES = 3
MIN_TOPOLOGY_CONFIDENCE = 0.67


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def inferred_propagation_topology(
    storage: Storage,
    *,
    min_samples: int = MIN_TOPOLOGY_SAMPLES,
    min_confidence: float = MIN_TOPOLOGY_CONFIDENCE,
) -> dict:
    if min_samples < 1:
        raise ValueError("topology min_samples must be at least 1")
    if not 0.5 <= min_confidence <= 1.0:
        raise ValueError("topology min_confidence must be between 0.5 and 1.0")

    with storage.connect() as conn:
        target_rows = conn.execute(
            """
            SELECT DISTINCT pc.article_id, s.id AS server_id, s.host
            FROM propagation_campaigns pc
            JOIN propagation_campaign_endpoints pce ON pce.campaign_id = pc.id
            JOIN endpoints e ON e.id = pce.endpoint_id
            JOIN servers s ON s.id = e.server_id
            ORDER BY pc.article_id, s.id
            """
        ).fetchall()
        visible_rows = conn.execute(
            """
            SELECT po.article_id, s.id AS server_id, s.host,
                   MIN(po.observed_at) AS first_seen_at
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN servers s ON s.id = e.server_id
            WHERE po.present = 1
              AND po.error IS NULL
              AND po.response_code = 223
            GROUP BY po.article_id, s.id, s.host
            ORDER BY po.article_id, s.id
            """
        ).fetchall()

    hosts: dict[int, str] = {}
    targets_by_article: dict[int, set[int]] = defaultdict(set)
    first_seen: dict[int, dict[int, datetime]] = defaultdict(dict)

    for row in target_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        hosts[server_id] = str(row["host"])
        targets_by_article[article_id].add(server_id)

    for row in visible_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        hosts[server_id] = str(row["host"])
        first_seen[article_id][server_id] = _as_utc(str(row["first_seen_at"]))

    pair_samples: dict[tuple[int, int], list[float]] = defaultdict(list)
    comparable_articles = 0
    for article_id, targets in targets_by_article.items():
        visible = first_seen.get(article_id, {})
        present_targets = sorted(targets & set(visible))
        if len(present_targets) >= 2:
            comparable_articles += 1
        for left, right in combinations(present_targets, 2):
            delta = (visible[right] - visible[left]).total_seconds()
            pair_samples[(left, right)].append(round(delta, 3))

    edges: list[dict] = []
    for (left, right), deltas in pair_samples.items():
        left_first = sum(1 for value in deltas if value > 0)
        right_first = sum(1 for value in deltas if value < 0)
        ties = sum(1 for value in deltas if value == 0)
        directional = left_first + right_first
        if directional < min_samples or directional == 0:
            continue

        if left_first >= right_first:
            source_id, target_id = left, right
            forward, reverse = left_first, right_first
            oriented = deltas
        else:
            source_id, target_id = right, left
            forward, reverse = right_first, left_first
            oriented = [-value for value in deltas]

        confidence = round(forward / directional, 3)
        if confidence < min_confidence:
            continue

        edges.append(
            {
                "source_server_id": source_id,
                "source_host": hosts[source_id],
                "target_server_id": target_id,
                "target_host": hosts[target_id],
                "relation": "observed_precedence",
                "inference": True,
                "sample_count": len(deltas),
                "directional_sample_count": directional,
                "forward_count": forward,
                "reverse_count": reverse,
                "tie_count": ties,
                "confidence": confidence,
                "median_lead_seconds": round(float(median(oriented)), 3),
            }
        )

    edges.sort(
        key=lambda item: (
            -item["confidence"],
            -item["directional_sample_count"],
            item["source_host"],
            item["target_host"],
        )
    )
    nodes = [
        {"server_id": server_id, "host": host}
        for server_id, host in sorted(hosts.items(), key=lambda item: item[1])
    ]
    return {
        "model": "inferred_observed_propagation_precedence",
        "authoritative_topology": False,
        "disclaimer": (
            "Edges describe repeated observed first-seen precedence only; "
            "they do not prove direct NNTP peering or feed relationships."
        ),
        "min_samples": min_samples,
        "min_confidence": min_confidence,
        "targeted_article_count": len(targets_by_article),
        "comparable_article_count": comparable_articles,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }
