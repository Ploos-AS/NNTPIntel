from __future__ import annotations

import json
from datetime import UTC, datetime

from nntpintel.propagation_topology_anomalies import topology_anomalies
from nntpintel.storage import Storage

TOPOLOGY_INCIDENT_PREFIX = "topology_"


def _now_iso(now: datetime | None) -> str:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _signals(anomaly_data: dict) -> dict[tuple[int, str], dict]:
    anomalies = anomaly_data["anomalies"]
    dated = [item for item in anomalies if item.get("source_server_id") is not None]
    if not dated:
        return {}
    latest_at = max(str(item["at"]) for item in dated)
    signals: dict[tuple[int, str], dict] = {}
    for item in dated:
        if str(item["at"]) != latest_at:
            continue
        server_id = int(item["source_server_id"])
        kind = f'{TOPOLOGY_INCIDENT_PREFIX}{item["kind"]}'
        key = (server_id, kind)
        severity = "critical" if item["severity"] == "high" else "warning"
        existing = signals.get(key)
        detail = {"anomaly": item, "inference_only": True}
        if existing is None or severity == "critical":
            signals[key] = {
                "severity": severity,
                "window": f'{anomaly_data["days"]}d_history',
                "metric_value": None,
                "baseline_value": None,
                "detail": detail,
            }
    return signals


def evaluate_topology_incidents(
    storage: Storage,
    *,
    now: datetime | None = None,
) -> dict:
    current = _now_iso(now)
    data = topology_anomalies(storage)
    signals = _signals(data)
    created = updated = resolved = 0

    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, server_id, kind
            FROM propagation_incidents
            WHERE resolved_at IS NULL AND kind LIKE 'topology_%'
            """
        ).fetchall()
        open_by_key = {
            (int(row["server_id"]), str(row["kind"])): int(row["id"])
            for row in rows
        }

        for key, signal in signals.items():
            server_id, kind = key
            incident_id = open_by_key.get(key)
            detail_json = json.dumps(signal["detail"], sort_keys=True)
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
                    SET severity = ?, updated_at = ?, window = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (
                        signal["severity"],
                        current,
                        signal["window"],
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
        "authoritative_topology": False,
    }


def list_topology_incidents(
    storage: Storage,
    *,
    include_resolved: bool = True,
    limit: int = 200,
) -> list[dict]:
    if limit < 1 or limit > 1000:
        raise ValueError("incident limit must be between 1 and 1000")
    resolved_clause = "" if include_resolved else "AND pi.resolved_at IS NULL"
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT pi.id, pi.server_id, s.host, pi.kind, pi.severity,
                   pi.started_at, pi.updated_at, pi.resolved_at, pi.window,
                   pi.detail_json
            FROM propagation_incidents pi
            JOIN servers s ON s.id = pi.server_id
            WHERE pi.kind LIKE 'topology_%' {resolved_clause}
            ORDER BY (pi.resolved_at IS NULL) DESC, pi.started_at DESC, pi.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["status"] = "open" if item["resolved_at"] is None else "resolved"
        item["detail"] = json.loads(item.pop("detail_json"))
        item["authoritative_topology"] = False
        result.append(item)
    return result
