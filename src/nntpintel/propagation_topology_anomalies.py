from __future__ import annotations

from collections import defaultdict

from nntpintel.propagation_topology_history import topology_history
from nntpintel.storage import Storage

MIN_CONFIDENCE_DROP = 0.2
MIN_CHURN_EVENTS = 3


def topology_anomalies(
    storage: Storage,
    *,
    days: int = 30,
    min_confidence_drop: float = MIN_CONFIDENCE_DROP,
    min_churn_events: int = MIN_CHURN_EVENTS,
) -> dict:
    if not 0.0 < min_confidence_drop <= 1.0:
        raise ValueError("min_confidence_drop must be between 0 and 1")
    if min_churn_events < 1:
        raise ValueError("min_churn_events must be at least 1")

    history = topology_history(storage, days=days)
    anomalies: list[dict] = []
    events = history["events"]

    # Reversal: A→B disappears while B→A appears at the same snapshot time.
    by_time: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by_time[str(event["at"])].append(event)

    for at, batch in by_time.items():
        appeared = {
            (int(item["source_server_id"]), int(item["target_server_id"])): item
            for item in batch
            if item["event"] == "appeared"
        }
        disappeared = {
            (int(item["source_server_id"]), int(item["target_server_id"])): item
            for item in batch
            if item["event"] == "disappeared"
        }
        seen_reversals: set[tuple[int, int]] = set()
        for (source, target), old in disappeared.items():
            reverse = (target, source)
            if reverse not in appeared:
                continue
            pair = tuple(sorted((source, target)))
            if pair in seen_reversals:
                continue
            seen_reversals.add(pair)
            new = appeared[reverse]
            anomalies.append(
                {
                    "at": at,
                    "kind": "edge_reversal",
                    "severity": "high",
                    "source_host": old["source_host"],
                    "target_host": old["target_host"],
                    "previous_confidence": old["confidence"],
                    "new_source_host": new["source_host"],
                    "new_target_host": new["target_host"],
                    "new_confidence": new["confidence"],
                }
            )

        churn_count = sum(item["event"] in {"appeared", "disappeared"} for item in batch)
        if churn_count >= min_churn_events:
            anomalies.append(
                {
                    "at": at,
                    "kind": "topology_churn",
                    "severity": "medium" if churn_count < min_churn_events * 2 else "high",
                    "event_count": churn_count,
                }
            )

    for event in events:
        if event["event"] == "changed" and "previous_confidence" in event:
            drop = float(event["previous_confidence"]) - float(event["confidence"])
            if drop >= min_confidence_drop:
                anomalies.append(
                    {
                        "at": event["at"],
                        "kind": "confidence_collapse",
                        "severity": "high" if drop >= min_confidence_drop * 2 else "medium",
                        "source_host": event["source_host"],
                        "target_host": event["target_host"],
                        "previous_confidence": event["previous_confidence"],
                        "confidence": event["confidence"],
                        "confidence_drop": round(drop, 3),
                    }
                )
        elif event["event"] == "disappeared":
            anomalies.append(
                {
                    "at": event["at"],
                    "kind": "edge_disappeared",
                    "severity": "medium",
                    "source_host": event["source_host"],
                    "target_host": event["target_host"],
                    "confidence": event["confidence"],
                }
            )

    anomalies.sort(key=lambda item: (item["at"], item["kind"], str(item.get("source_host", ""))))
    counts = {kind: sum(1 for item in anomalies if item["kind"] == kind) for kind in {
        "edge_reversal", "confidence_collapse", "edge_disappeared", "topology_churn"
    }}
    return {
        "model": "inferred_topology_anomalies",
        "authoritative_topology": False,
        "disclaimer": history["disclaimer"],
        "days": days,
        "min_confidence_drop": min_confidence_drop,
        "min_churn_events": min_churn_events,
        "anomaly_count": len(anomalies),
        "counts": counts,
        "anomalies": anomalies,
    }
