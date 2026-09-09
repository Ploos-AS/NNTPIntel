from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.storage import Storage

STALE_HOURS = 24.0
VERY_STALE_HOURS = 168.0
STRONG_CONFIDENCE = 0.8


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def topology_data_quality(storage: Storage, *, now: datetime | None = None) -> dict:
    topology = inferred_propagation_topology(storage)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)

    with storage.connect() as conn:
        target_rows = conn.execute(
            """
            SELECT pc.article_id, s.id AS server_id, s.host
            FROM propagation_campaigns pc
            JOIN propagation_campaign_endpoints pce ON pce.campaign_id = pc.id
            JOIN endpoints e ON e.id = pce.endpoint_id
            JOIN servers s ON s.id = e.server_id
            GROUP BY pc.article_id, s.id, s.host
            """
        ).fetchall()
        visible_rows = conn.execute(
            """
            SELECT po.article_id, s.id AS server_id, s.host,
                   MAX(po.observed_at) AS latest_observed_at
            FROM propagation_observations po
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN servers s ON s.id = e.server_id
            WHERE po.present = 1 AND po.error IS NULL AND po.response_code = 223
            GROUP BY po.article_id, s.id, s.host
            """
        ).fetchall()

    targeted: dict[int, set[int]] = defaultdict(set)
    visible: dict[int, set[int]] = defaultdict(set)
    hosts: dict[int, str] = {}
    latest_by_server: dict[int, datetime] = {}
    for row in target_rows:
        server_id = int(row["server_id"])
        hosts[server_id] = str(row["host"])
        targeted[server_id].add(int(row["article_id"]))
    for row in visible_rows:
        server_id = int(row["server_id"])
        hosts[server_id] = str(row["host"])
        visible[server_id].add(int(row["article_id"]))
        observed = _as_utc(str(row["latest_observed_at"]))
        previous = latest_by_server.get(server_id)
        if previous is None or observed > previous:
            latest_by_server[server_id] = observed

    servers: list[dict] = []
    for server_id in sorted(hosts, key=lambda item: hosts[item]):
        target_count = len(targeted[server_id])
        visible_count = len(visible[server_id] & targeted[server_id])
        coverage = round(visible_count / target_count, 3) if target_count else 0.0
        latest = latest_by_server.get(server_id)
        age_hours = None
        freshness = "no_valid_presence"
        if latest is not None:
            age_hours = round(max(0.0, (current - latest).total_seconds() / 3600.0), 1)
            if age_hours >= VERY_STALE_HOURS:
                freshness = "very_stale"
            elif age_hours >= STALE_HOURS:
                freshness = "stale"
            else:
                freshness = "fresh"
        servers.append(
            {
                "server_id": server_id,
                "host": hosts[server_id],
                "targeted_article_count": target_count,
                "visible_article_count": visible_count,
                "valid_presence_coverage": coverage,
                "latest_valid_presence_at": latest.isoformat() if latest else None,
                "age_hours": age_hours,
                "freshness": freshness,
            }
        )

    edges = topology["edges"]
    confidence_buckets = {
        "strong": sum(1 for edge in edges if float(edge["confidence"]) >= STRONG_CONFIDENCE),
        "moderate": sum(
            1
            for edge in edges
            if float(topology["min_confidence"]) <= float(edge["confidence"]) < STRONG_CONFIDENCE
        ),
    }
    weak_sample_edges = sum(
        1
        for edge in edges
        if int(edge["directional_sample_count"]) <= int(topology["min_samples"])
    )
    stale_servers = sum(1 for item in servers if item["freshness"] in {"stale", "very_stale"})
    missing_servers = sum(1 for item in servers if item["freshness"] == "no_valid_presence")
    low_coverage_servers = sum(1 for item in servers if item["valid_presence_coverage"] < 0.5)
    targeted_articles = int(topology["targeted_article_count"])
    comparable_articles = int(topology["comparable_article_count"])
    comparable_ratio = round(comparable_articles / targeted_articles, 3) if targeted_articles else 0.0

    deductions = 0
    deductions += min(35, low_coverage_servers * 8)
    deductions += min(25, stale_servers * 6)
    deductions += min(20, missing_servers * 10)
    if targeted_articles and comparable_ratio < 0.5:
        deductions += 15
    if edges and confidence_buckets["strong"] / len(edges) < 0.5:
        deductions += 10
    quality_score = max(0, 100 - deductions)
    if quality_score >= 80:
        quality_level = "good"
    elif quality_score >= 60:
        quality_level = "usable"
    elif quality_score >= 40:
        quality_level = "limited"
    else:
        quality_level = "weak"

    servers.sort(
        key=lambda item: (
            item["freshness"] == "fresh",
            item["valid_presence_coverage"],
            item["host"],
        )
    )
    return {
        "model": "inferred_topology_data_quality",
        "authoritative_topology": False,
        "disclaimer": (
            "Quality scores describe NNTPIntel observation coverage, freshness, sample depth, and inferred "
            "edge confidence only; they do not validate the inferred topology as physical NNTP topology."
        ),
        "quality_score": quality_score,
        "quality_level": quality_level,
        "stale_after_hours": STALE_HOURS,
        "very_stale_after_hours": VERY_STALE_HOURS,
        "targeted_article_count": targeted_articles,
        "comparable_article_count": comparable_articles,
        "comparable_article_ratio": comparable_ratio,
        "edge_count": len(edges),
        "strong_edge_count": confidence_buckets["strong"],
        "moderate_edge_count": confidence_buckets["moderate"],
        "weak_sample_edge_count": weak_sample_edges,
        "server_count": len(servers),
        "low_coverage_server_count": low_coverage_servers,
        "stale_server_count": stale_servers,
        "missing_valid_presence_server_count": missing_servers,
        "servers": servers,
    }
