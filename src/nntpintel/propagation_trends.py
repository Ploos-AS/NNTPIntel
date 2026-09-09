from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median

from nntpintel.propagation_analytics import _percentile
from nntpintel.storage import Storage

WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
MIN_LAGGING_SAMPLES = 3
MIN_LAGGING_DELTA_SECONDS = 30.0


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stats(values: list[float]) -> dict:
    return {
        "sample_count": len(values),
        "median_delay_seconds": round(float(median(values)), 3) if values else None,
        "p95_delay_seconds": _percentile(values, 0.95),
    }


def propagation_trends(storage: Storage, *, now: datetime | None = None) -> dict:
    current = (now or datetime.now(UTC)).astimezone(UTC)
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
                   s.id AS server_id, s.host
            FROM first_visible fv
            JOIN baselines b ON b.article_id = fv.article_id
            JOIN endpoints e ON e.id = fv.endpoint_id
            JOIN servers s ON s.id = e.server_id
            ORDER BY b.baseline_at, fv.article_id, s.id
            """
        ).fetchall()
        target_rows = conn.execute(
            """
            SELECT DISTINCT pc.article_id, s.id AS server_id, s.host
            FROM propagation_campaigns pc
            JOIN propagation_campaign_endpoints pce ON pce.campaign_id = pc.id
            JOIN endpoints e ON e.id = pce.endpoint_id
            JOIN servers s ON s.id = e.server_id
            """
        ).fetchall()

    article_baselines: dict[int, datetime] = {}
    server_article_delays: dict[int, dict[int, float]] = defaultdict(dict)
    server_hosts: dict[int, str] = {}
    global_article_delays: dict[int, list[float]] = defaultdict(list)
    for row in visible_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        baseline = _as_utc(str(row["baseline_at"]))
        first_seen = _as_utc(str(row["first_seen_at"]))
        delay = round((first_seen - baseline).total_seconds(), 3)
        article_baselines[article_id] = baseline
        server_hosts[server_id] = str(row["host"])
        existing = server_article_delays[server_id].get(article_id)
        if existing is None or delay < existing:
            server_article_delays[server_id][article_id] = delay
        global_article_delays[article_id].append(delay)

    server_targets: dict[int, set[int]] = defaultdict(set)
    for row in target_rows:
        server_id = int(row["server_id"])
        server_hosts[server_id] = str(row["host"])
        server_targets[server_id].add(int(row["article_id"]))

    windows: dict[str, dict] = {}
    for label, width in WINDOWS.items():
        cutoff = current - width
        eligible_articles = {
            article_id
            for article_id, baseline in article_baselines.items()
            if baseline >= cutoff and baseline <= current
        }
        global_values = [
            delay
            for article_id in eligible_articles
            for delay in global_article_delays.get(article_id, [])
        ]
        global_stats = _stats(global_values)
        baseline_median = global_stats["median_delay_seconds"]

        servers: list[dict] = []
        for server_id, host in server_hosts.items():
            targeted = server_targets.get(server_id, set()) & eligible_articles
            delays_by_article = server_article_delays.get(server_id, {})
            visible = targeted & set(delays_by_article)
            values = [delays_by_article[article_id] for article_id in sorted(visible)]
            coverage = round((len(visible) / len(targeted)) * 100, 2) if targeted else None
            stats = _stats(values)
            delta = (
                round(stats["median_delay_seconds"] - baseline_median, 3)
                if stats["median_delay_seconds"] is not None and baseline_median is not None
                else None
            )
            lagging = bool(
                stats["sample_count"] >= MIN_LAGGING_SAMPLES
                and delta is not None
                and delta >= MIN_LAGGING_DELTA_SECONDS
            )
            servers.append(
                {
                    "server_id": server_id,
                    "host": host,
                    "targeted_article_count": len(targeted),
                    "visible_article_count": len(visible),
                    "coverage_percent": coverage,
                    **stats,
                    "median_delta_seconds": delta,
                    "lagging": lagging,
                }
            )
        servers.sort(
            key=lambda item: (
                not item["lagging"],
                -(item["median_delta_seconds"] or 0.0),
                item["host"],
            )
        )
        windows[label] = {
            "start_at": cutoff.isoformat(),
            "end_at": current.isoformat(),
            "article_count": len(eligible_articles),
            "targeted_server_count": sum(1 for item in servers if item["targeted_article_count"]),
            "lagging_server_count": sum(1 for item in servers if item["lagging"]),
            **global_stats,
            "servers": servers,
        }

    daily: dict[str, list[float]] = defaultdict(list)
    for article_id, baseline in article_baselines.items():
        if baseline > current or baseline < current - WINDOWS["30d"]:
            continue
        day = baseline.date().isoformat()
        daily[day].extend(global_article_delays.get(article_id, []))
    history = [
        {"date": day, **_stats(values)}
        for day, values in sorted(daily.items())
    ]
    return {
        "generated_at": current.isoformat(),
        "lagging_min_samples": MIN_LAGGING_SAMPLES,
        "lagging_min_delta_seconds": MIN_LAGGING_DELTA_SECONDS,
        "windows": windows,
        "daily": history,
    }
