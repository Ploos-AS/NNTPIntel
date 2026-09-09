from __future__ import annotations

import json
from datetime import UTC, datetime

from nntpintel.propagation_topology_anomalies import topology_anomalies
from nntpintel.storage import Storage

TOPOLOGY_INCIDENT_PREFIX = "topology_"
WARNING_OPEN_STREAK = 2
RECOVERY_STREAK = 2
MAX_EVIDENCE = 20


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
        if existing is None or severity == "critical":
            signals[key] = {
                "severity": severity,
                "window": f'{anomaly_data["days"]}d_history',
                "marker": str(anomaly_data.get("snapshot_marker") or item["at"]),
                "anomaly": item,
            }
    return signals


def _decode_detail(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _append_evidence(detail: dict, *, at: str, state: str, anomaly: dict | None) -> dict:
    history = list(detail.get("evidence_history") or [])
    history.append({"at": at, "state": state, "anomaly": anomaly})
    detail["evidence_history"] = history[-MAX_EVIDENCE:]
    return detail


def evaluate_topology_incidents(
    storage: Storage,
    *,
    now: datetime | None = None,
) -> dict:
    current = _now_iso(now)
    data = topology_anomalies(storage)
    marker = str(data.get("snapshot_marker") or current)
    signals = _signals(data)
    created = updated = resolved = pending = 0

    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, server_id, kind, severity, resolved_at, detail_json
            FROM propagation_incidents
            WHERE resolved_at IS NULL AND kind LIKE 'topology_%'
            """
        ).fetchall()
        open_by_key = {
            (int(row["server_id"]), str(row["kind"])): row
            for row in rows
        }

        for key, signal in signals.items():
            server_id, kind = key
            row = open_by_key.get(key)
            if row is None:
                detail = {
                    "lifecycle_state": "open" if signal["severity"] == "critical" else "pending",
                    "signal_streak": 1,
                    "recovery_streak": 0,
                    "last_signal_marker": signal["marker"],
                    "last_evaluated_marker": marker,
                    "opened_at": current if signal["severity"] == "critical" else None,
                    "inference_only": True,
                }
                _append_evidence(
                    detail,
                    at=current,
                    state=detail["lifecycle_state"],
                    anomaly=signal["anomaly"],
                )
                conn.execute(
                    """
                    INSERT INTO propagation_incidents(
                        server_id, kind, severity, started_at, updated_at,
                        window, metric_value, baseline_value, detail_json
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                    """,
                    (
                        server_id,
                        kind,
                        signal["severity"],
                        current,
                        current,
                        signal["window"],
                        json.dumps(detail, sort_keys=True),
                    ),
                )
                if detail["lifecycle_state"] == "open":
                    created += 1
                else:
                    pending += 1
                continue

            incident_id = int(row["id"])
            detail = _decode_detail(row["detail_json"])
            lifecycle_state = str(detail.get("lifecycle_state") or "open")
            last_signal_marker = detail.get("last_signal_marker")
            signal_streak = int(detail.get("signal_streak") or 0)
            if signal["marker"] != last_signal_marker:
                signal_streak += 1
                detail["last_signal_marker"] = signal["marker"]
                _append_evidence(detail, at=current, state="signal", anomaly=signal["anomaly"])
            detail["signal_streak"] = signal_streak
            detail["recovery_streak"] = 0
            detail["last_evaluated_marker"] = marker

            should_open = signal["severity"] == "critical" or signal_streak >= WARNING_OPEN_STREAK
            if lifecycle_state == "pending" and should_open:
                lifecycle_state = "open"
                detail["opened_at"] = current
                created += 1
            elif lifecycle_state in {"open", "recovering"}:
                lifecycle_state = "open"
                updated += 1
            else:
                pending += 1
            detail["lifecycle_state"] = lifecycle_state

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
                    json.dumps(detail, sort_keys=True),
                    incident_id,
                ),
            )

        for key, row in open_by_key.items():
            if key in signals:
                continue
            incident_id = int(row["id"])
            detail = _decode_detail(row["detail_json"])
            lifecycle_state = str(detail.get("lifecycle_state") or "open")
            if detail.get("last_evaluated_marker") == marker:
                continue
            detail["last_evaluated_marker"] = marker

            if lifecycle_state == "pending":
                detail["lifecycle_state"] = "suppressed"
                _append_evidence(detail, at=current, state="suppressed", anomaly=None)
                conn.execute(
                    """
                    UPDATE propagation_incidents
                    SET updated_at = ?, resolved_at = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (current, current, json.dumps(detail, sort_keys=True), incident_id),
                )
                continue

            recovery_streak = int(detail.get("recovery_streak") or 0) + 1
            detail["recovery_streak"] = recovery_streak
            if recovery_streak >= RECOVERY_STREAK:
                detail["lifecycle_state"] = "resolved"
                _append_evidence(detail, at=current, state="resolved", anomaly=None)
                conn.execute(
                    """
                    UPDATE propagation_incidents
                    SET updated_at = ?, resolved_at = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (current, current, json.dumps(detail, sort_keys=True), incident_id),
                )
                resolved += 1
            else:
                detail["lifecycle_state"] = "recovering"
                _append_evidence(detail, at=current, state="recovering", anomaly=None)
                conn.execute(
                    """
                    UPDATE propagation_incidents
                    SET updated_at = ?, detail_json = ?
                    WHERE id = ?
                    """,
                    (current, json.dumps(detail, sort_keys=True), incident_id),
                )
                updated += 1
        conn.commit()

    return {
        "evaluated_at": current,
        "snapshot_marker": marker,
        "signal_count": len(signals),
        "created_count": created,
        "updated_count": updated,
        "resolved_count": resolved,
        "pending_count": pending,
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
        item["detail"] = _decode_detail(item.pop("detail_json"))
        lifecycle_state = str(item["detail"].get("lifecycle_state") or "open")
        if lifecycle_state in {"pending", "suppressed"}:
            continue
        item["status"] = lifecycle_state if item["resolved_at"] is None else "resolved"
        item["authoritative_topology"] = False
        result.append(item)
    return result
