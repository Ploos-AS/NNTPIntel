SIGNIFICANCE_ORDER = {
    "informational": 0,
    "notable": 1,
    "important": 2,
    "critical": 3,
}


def _promote(current: str, candidate: str) -> str:
    if SIGNIFICANCE_ORDER[candidate] > SIGNIFICANCE_ORDER[current]:
        return candidate
    return current


def classify_change_significance(semantic_changes: list[dict]) -> dict:
    level = "informational"
    reasons: list[str] = []

    for change in semantic_changes:
        code = str(change.get("code", ""))
        before = change.get("before")
        after = change.get("after")
        delta = change.get("delta")

        if code == "risk_level":
            if after == "critical" and before != "critical":
                level = _promote(level, "critical")
                reasons.append("risk level entered critical")
            elif after == "high" and before not in {"high", "critical"}:
                level = _promote(level, "important")
                reasons.append("risk level entered high")
            elif before in {"critical", "high"} and after not in {"critical", "high"}:
                level = _promote(level, "notable")
                reasons.append("risk level improved from elevated state")

        elif code == "risk" and isinstance(before, (int, float)) and isinstance(after, (int, float)):
            if before < 75 <= after:
                level = _promote(level, "critical")
                reasons.append("risk score crossed critical threshold")
            elif before < 50 <= after:
                level = _promote(level, "important")
                reasons.append("risk score crossed high threshold")
            elif isinstance(delta, (int, float)) and abs(delta) >= 25:
                level = _promote(level, "important")
                reasons.append("risk score changed by at least 25 points")
            elif isinstance(delta, (int, float)) and abs(delta) >= 10:
                level = _promote(level, "notable")
                reasons.append("risk score changed by at least 10 points")

        elif code == "severity":
            if after == "critical" and before != "critical":
                level = _promote(level, "critical")
                reasons.append("incident severity entered critical")
            elif after in {"high", "warning"} and before != after:
                level = _promote(level, "important")
                reasons.append(f"incident severity changed to {after}")

        elif code == "status":
            if after == "open" and before != "open":
                level = _promote(level, "important")
                reasons.append("incident became open")
            elif after in {"resolved", "recovering"} and before != after:
                level = _promote(level, "notable")
                reasons.append(f"incident status changed to {after}")

        elif code == "evidence_level":
            if after == "low" and before != "low":
                level = _promote(level, "important")
                reasons.append("evidence level collapsed to low")
            elif after == "limited" and before not in {"limited", "low"}:
                level = _promote(level, "notable")
                reasons.append("evidence level degraded to limited")

        elif code == "freshness":
            if after in {"very_stale", "no_valid_presence"} and before != after:
                level = _promote(level, "important")
                reasons.append(f"evidence freshness degraded to {after}")
            elif after == "stale" and before != "stale":
                level = _promote(level, "notable")
                reasons.append("evidence became stale")

        elif code == "edge_confidence" and isinstance(delta, (int, float)):
            if delta <= -0.20:
                level = _promote(level, "important")
                reasons.append("edge confidence dropped by at least 0.20")
            elif delta <= -0.10:
                level = _promote(level, "notable")
                reasons.append("edge confidence dropped by at least 0.10")

        elif code in {"coverage", "triage"} and isinstance(delta, (int, float)):
            if delta <= -25 or (code == "triage" and delta >= 25):
                level = _promote(level, "important")
                reasons.append(f"{code} changed materially")
            elif abs(delta) >= 10:
                level = _promote(level, "notable")
                reasons.append(f"{code} changed notably")

        elif code in {
            "presence_observations",
            "campaigns",
            "articles",
            "visible_articles",
            "supporting_observations",
            "sample_count",
            "member_count",
        }:
            reasons.append(str(change.get("summary", code)))

    if not semantic_changes:
        level = "informational"
        reasons = ["no recognized semantic field changes"]
    elif not reasons:
        reasons = ["evidence content changed without a higher-significance recognized transition"]

    return {
        "level": level,
        "rank": SIGNIFICANCE_ORDER[level],
        "reasons": reasons,
        "rule_model": "deterministic_topology_change_significance_v1",
        "operator_confirmed": False,
    }
