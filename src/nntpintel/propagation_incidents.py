from __future__ import annotations

import json
from datetime import UTC, datetime

from nntpintel.propagation_trends import propagation_trends
from nntpintel.storage import Storage

COVERAGE_DROP_POINTS = 25.0
DELAY_SPIKE_SECONDS = 60.0
MIN_INCIDENT_SAMPLES = 3
INCIDENT_KINDS = {"lagging", "coverage_drop", "delay_spike"}


def _now_iso(now: datetime | None) -> str:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _signals(trends: dict) -> dict[tuple[int, str], dict]:
    seven = trends["windows"]["7d"]
    day = trends["windows"]["24h"]
    seven_by_id = {int(item["server_id"]): item for item in seven["servers"]}
    day_by_id = {int(item["server_id"]): item for item in day["servers"]}
    signals: dict[tuple[int, str], dict] = {}

    for server_id, seven_row in seven_by_id.items():
        host = str(seven_row["host"])
        day_row = day_by_id.get(server_id)

        if seven_row["lagging"]:
            delta = float(seven_row["median_delta_seconds"])
            signals[(server_id, "lagging")] = {
                "severity": "critical" if delta >= 120.0 else "warning",
                "window": "7d",
                "metric_value": delta,
                "baseline_value": 0.0,
                "detail": {
                    "host": host,
                    "sample_count": int(seven_row["sample_count"]),
                    "median_delay_seconds": seven_row["median_delay_seconds"],
                    "network_median_delay_seconds": seven["median_delay_seconds"],
                    "median_delta_seconds": delta,
                },
            }

        if day_row is None:
            continue
        day_coverage = day_row["coverage_percent"]
        seven_coverage = seven_row["coverage_percent"]
        if (
            int(day_row["targeted_article_count"]) >= MIN_INCIDENT_SAMPLES
            and int(seven_row["targeted_article_count"]) >= MIN_INCIDENT_SAMPLES
            and day_coverage is not None
            and seven_coverage is not None
        ):
            drop = round(float(seven_coverage) - float(day_coverage), 2)
            if drop >= COVERAGE_DROP_POINTS:
                signals[(server_id, "coverage_drop")] = {
                    "severity": "critical" if drop >= 50.0 else "warning",
                    "window": "24h_vs_7d",
                    "metric_value": float(day_coverage),
                    "baseline_value": float(seven_coverage),
                    "detail": {
                        "host": host,
                        "coverage_24h_percent": day_coverage,
                        "coverage_7d_percent": seven_coverage,
                        "drop_points": drop,
                        "targeted_24h": int(day_row["targeted_article_count"]),
                    },
                }

        day_median = day_row["median_delay_seconds"]
        seven_median = seven_row["median_delay_seconds"]
        if (
            int(day_row["sample_count"]) >= MIN_INCIDENT_SAMPLES
            and int(seven_row["sample_count"]) >= MIN_INCIDENT_SAMPLES
            and day_median is not None
            and seven_median is not None
        ):
            spike = round(float(day_median) - float(seven_median), 3)
            if spike >= DELAY_SPIKE_SECONDS:
                signals[(server_id, "delay_spike")] = {
                    "severity": "critical" if spike >= 180.0 else "warning",
                    "window": "24h_vs_7d",
                    "metric_value": float(day_median),
                    "baseline_value": float(seven_median),
                    "detail": {
                        "host": host,
                        "median_24h_seconds": day_median,
                        "median_7d_seconds": seven_median,
                        "increase_seconds": spike,
                        "sample_count_24h": int(day_row["sample_count"]),
                    },
                }
    return signals


def evaluate_propagation_incidents(
    storage: Storage,
    *,
    now: datetime | None = None,
) -> dict:
    current = _now_iso(now)
    trends = propagation_trends(storage, now=now)
    signals = _signals(trends)
    created = 0
    updated = 0
    resolved = 0

    with storage.connect() as conn:
        open_rows = conn.execute(
            "SELECT id, server_id, kind FROM propagation_incidents WHERE resolved_at IS NULL"
        ).fetchall()
        open_by_key = {(int(row["server_id"]), str(row["kind"])): int(row["id"]) for row in open_rows}

        for key, signal in signals.items():
            server_id, kind = key
            detail_json = json.dumps(signal["detail"], sort_keys=True)
            incident_id = open_by_key.get(key)
            if incident_id is None:
                conn.execute(
                    """
                    INSERT INTO propagation_incidents(
                        server_id, kind, severity, started_at, updated_at,
                        window, metric_value, baseline_value, detail_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        server_id,
                        kind,
                        signal["severity"],
                        current,
                        current,
                        signal["window"],
                        signal["metric_value"],
                        signal["baseline_value"],
                        detail_json,
                    ),
                )
                created += 1
            else:
                conn.execute(
                    """
                    UPDATE propagation_incidents
                    SET severity = ?, updated_at = ?, window = ?,
                        metric_value = ?, baseline_value = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (
                        signal["severity"],
                        current,
                        signal["window"],
                        signal["metric_value"],
                        signal["baseline_value"],
                        detail_json,
                        incident_id,
                    ),
                )
                updated += 1

        for key, incident_id in open_by_key.items():
            if key not in signals:
                conn.execute(
                    """
                    UPDATE propagation_incidents
                    SET updated_at = ?, resolved_at = ?
                    WHERE id = ?
                    """,
                    (current, current, incident_id),
                )
                resolved += 1
        conn.commit()

    return {
        "evaluated_at": current,
        "signal_count": len(signals),
        "created_count": created,
        "updated_count": updated,
        "resolved_count": resolved,
        "open_incident_count": len(signals),
    }


def list_propagation_incidents(
    storage: Storage,
    *,
    include_resolved: bool = True,
    limit: int = 200,
) -> list[dict]:
    if limit < 1 or limit > 1000:
        raise ValueError("incident limit must be between 1 and 1000")
    where = "" if include_resolved else "WHERE pi.resolved_at IS NULL"
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT pi.id, pi.server_id, s.host, pi.kind, pi.severity,
                   pi.started_at, pi.updated_at, pi.resolved_at, pi.window,
                   pi.metric_value, pi.baseline_value, pi.detail_json
            FROM propagation_incidents pi
            JOIN servers s ON s.id = pi.server_id
            {where}
            ORDER BY (pi.resolved_at IS NULL) DESC, pi.started_at DESC, pi.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        item["status"] = "open" if item["resolved_at"] is None else "resolved"
        item["detail"] = json.loads(item.pop("detail_json"))
        result.append(item)
    return result
