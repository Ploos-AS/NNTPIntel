from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median

from nntpintel.storage import Storage


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 3)


def _delay_stats(values: list[float]) -> dict:
    return {
        "sample_count": len(values),
        "median_delay_seconds": round(float(median(values)), 3) if values else None,
        "p95_delay_seconds": _percentile(values, 0.95),
        "max_delay_seconds": round(max(values), 3) if values else None,
    }


def propagation_analytics(storage: Storage) -> dict:
    with storage.connect() as conn:
        visible_rows = conn.execute(
            """
            WITH first_visible AS (
                SELECT po.article_id, po.endpoint_id, MIN(po.observed_at) AS first_seen_at
                FROM propagation_observations po
                WHERE po.present = 1
                  AND po.error IS NULL
                  AND po.response_code = 223
                GROUP BY po.article_id, po.endpoint_id
            ), baselines AS (
                SELECT article_id, MIN(first_seen_at) AS baseline_at
                FROM first_visible
                GROUP BY article_id
            )
            SELECT fv.article_id, fv.endpoint_id, fv.first_seen_at, b.baseline_at,
                   s.id AS server_id, s.host, e.port, e.transport, e.starttls
            FROM first_visible fv
            JOIN baselines b ON b.article_id = fv.article_id
            JOIN endpoints e ON e.id = fv.endpoint_id
            JOIN servers s ON s.id = e.server_id
            ORDER BY fv.article_id, fv.endpoint_id
            """
        ).fetchall()
        target_rows = conn.execute(
            """
            SELECT DISTINCT pc.article_id, pce.endpoint_id,
                   s.id AS server_id, s.host, e.port, e.transport, e.starttls
            FROM propagation_campaigns pc
            JOIN propagation_campaign_endpoints pce ON pce.campaign_id = pc.id
            JOIN endpoints e ON e.id = pce.endpoint_id
            JOIN servers s ON s.id = e.server_id
            ORDER BY pc.article_id, pce.endpoint_id
            """
        ).fetchall()
        article_count = int(conn.execute("SELECT COUNT(*) FROM propagation_articles").fetchone()[0])

    endpoint_meta: dict[int, dict] = {}
    endpoint_targets: dict[int, set[int]] = defaultdict(set)
    server_targets: dict[int, set[int]] = defaultdict(set)
    server_meta: dict[int, dict] = {}
    targeted_pairs: set[tuple[int, int]] = set()

    for row in target_rows:
        endpoint_id = int(row["endpoint_id"])
        server_id = int(row["server_id"])
        article_id = int(row["article_id"])
        endpoint_meta[endpoint_id] = {
            "endpoint_id": endpoint_id,
            "server_id": server_id,
            "host": row["host"],
            "port": int(row["port"]),
            "transport": row["transport"],
            "starttls": bool(row["starttls"]),
        }
        server_meta[server_id] = {"server_id": server_id, "host": row["host"]}
        endpoint_targets[endpoint_id].add(article_id)
        server_targets[server_id].add(article_id)
        targeted_pairs.add((article_id, endpoint_id))

    endpoint_visible: dict[int, set[int]] = defaultdict(set)
    endpoint_delays: dict[int, list[float]] = defaultdict(list)
    server_article_delays: dict[int, dict[int, float]] = defaultdict(dict)
    global_delays: list[float] = []
    visible_pairs: set[tuple[int, int]] = set()
    articles_with_visibility: set[int] = set()

    for row in visible_rows:
        endpoint_id = int(row["endpoint_id"])
        server_id = int(row["server_id"])
        article_id = int(row["article_id"])
        first_seen = datetime.fromisoformat(row["first_seen_at"])
        baseline = datetime.fromisoformat(row["baseline_at"])
        delay = round((first_seen - baseline).total_seconds(), 3)

        endpoint_meta.setdefault(
            endpoint_id,
            {
                "endpoint_id": endpoint_id,
                "server_id": server_id,
                "host": row["host"],
                "port": int(row["port"]),
                "transport": row["transport"],
                "starttls": bool(row["starttls"]),
            },
        )
        server_meta.setdefault(server_id, {"server_id": server_id, "host": row["host"]})
        endpoint_visible[endpoint_id].add(article_id)
        endpoint_delays[endpoint_id].append(delay)
        current = server_article_delays[server_id].get(article_id)
        if current is None or delay < current:
            server_article_delays[server_id][article_id] = delay
        global_delays.append(delay)
        visible_pairs.add((article_id, endpoint_id))
        articles_with_visibility.add(article_id)

    endpoints: list[dict] = []
    for endpoint_id, meta in endpoint_meta.items():
        targeted = endpoint_targets.get(endpoint_id, set())
        visible = endpoint_visible.get(endpoint_id, set())
        covered = targeted & visible
        coverage = round((len(covered) / len(targeted)) * 100, 2) if targeted else None
        endpoints.append(
            {
                **meta,
                "targeted_article_count": len(targeted),
                "visible_article_count": len(visible),
                "targeted_visible_article_count": len(covered),
                "coverage_percent": coverage,
                **_delay_stats(endpoint_delays.get(endpoint_id, [])),
            }
        )
    endpoints.sort(
        key=lambda item: (
            item["median_delay_seconds"] is None,
            -(item["median_delay_seconds"] or 0.0),
            item["host"],
            item["port"],
        )
    )

    servers: list[dict] = []
    for server_id, meta in server_meta.items():
        targeted = server_targets.get(server_id, set())
        article_delays = server_article_delays.get(server_id, {})
        visible = set(article_delays)
        covered = targeted & visible
        coverage = round((len(covered) / len(targeted)) * 100, 2) if targeted else None
        servers.append(
            {
                **meta,
                "targeted_article_count": len(targeted),
                "visible_article_count": len(visible),
                "targeted_visible_article_count": len(covered),
                "coverage_percent": coverage,
                **_delay_stats(list(article_delays.values())),
            }
        )
    servers.sort(
        key=lambda item: (
            item["median_delay_seconds"] is None,
            -(item["median_delay_seconds"] or 0.0),
            item["host"],
        )
    )

    targeted_visible_pairs = targeted_pairs & visible_pairs
    pair_coverage = (
        round((len(targeted_visible_pairs) / len(targeted_pairs)) * 100, 2)
        if targeted_pairs
        else None
    )
    return {
        "article_count": article_count,
        "articles_with_visibility": len(articles_with_visibility),
        "targeted_pair_count": len(targeted_pairs),
        "targeted_visible_pair_count": len(targeted_visible_pairs),
        "target_coverage_percent": pair_coverage,
        **_delay_stats(global_delays),
        "endpoints": endpoints,
        "servers": servers,
    }
