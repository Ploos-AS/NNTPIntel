from __future__ import annotations

from collections.abc import Iterable


SCALAR_FIELDS = (
    ("analysis.risk.risk_score", "risk", "Risk"),
    ("analysis.risk.risk_level", "risk_level", "Risk level"),
    ("analysis.risk.evidence_level", "evidence_level", "Evidence"),
    ("analysis.risk.evidence_coverage", "coverage", "Evidence coverage"),
    ("analysis.risk.evidence_freshness", "freshness", "Evidence freshness"),
    ("quality.evidence_level", "evidence_level", "Evidence"),
    ("quality.evidence_coverage", "coverage", "Evidence coverage"),
    ("quality.valid_presence_coverage", "coverage", "Presence coverage"),
    ("quality.freshness", "freshness", "Freshness"),
    ("analysis.incident.severity", "severity", "Incident severity"),
    ("analysis.incident.status", "status", "Incident status"),
    ("analysis.incident.triage_priority_score", "triage", "Triage priority"),
    ("analysis.incident.evidence_level", "evidence_level", "Evidence"),
    ("analysis.community.risk_score", "risk", "Community risk"),
    ("analysis.community.risk_level", "risk_level", "Community risk level"),
    ("analysis.community.evidence_level", "evidence_level", "Community evidence"),
    ("analysis.community.server_count", "member_count", "Community members"),
    ("analysis.edge_confidence", "edge_confidence", "Edge confidence"),
    ("analysis.directional_sample_count", "sample_count", "Directional samples"),
)

COUNT_FIELDS = (
    ("provenance.valid_presence_observation_ids", "presence_observations", "presence observations"),
    ("provenance.campaign_ids", "campaigns", "campaigns"),
    ("provenance.article_ids", "articles", "targeted articles"),
    ("provenance.visible_article_ids", "visible_articles", "visible articles"),
    ("provenance.supporting_observations", "supporting_observations", "supporting observations"),
)


def _get(bundle: dict, path: str) -> object | None:
    value: object = bundle
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _number_delta(before: object, after: object) -> float | int | None:
    if isinstance(before, bool) or isinstance(after, bool):
        return None
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        delta = after - before
        return round(delta, 4) if isinstance(delta, float) else delta
    return None


def _render_value(value: object) -> str:
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)


def _scalar_change(path: str, code: str, label: str, before: object, after: object) -> dict:
    delta = _number_delta(before, after)
    item = {
        "code": code,
        "path": path,
        "before": before,
        "after": after,
        "summary": f"{label} {_render_value(before)}→{_render_value(after)}",
    }
    if delta is not None:
        item["delta"] = delta
    return item


def _count_change(path: str, code: str, label: str, before: Iterable, after: Iterable) -> dict | None:
    before_count = len(list(before))
    after_count = len(list(after))
    if before_count == after_count:
        return None
    delta = after_count - before_count
    sign = "+" if delta > 0 else ""
    return {
        "code": code,
        "path": path,
        "before": before_count,
        "after": after_count,
        "delta": delta,
        "summary": f"{sign}{delta} {label} ({before_count}→{after_count})",
    }


def semantic_evidence_changes(before: dict, after: dict) -> list[dict]:
    changes: list[dict] = []
    seen_codes: set[str] = set()

    for path, code, label in SCALAR_FIELDS:
        before_value = _get(before, path)
        after_value = _get(after, path)
        if before_value is None or after_value is None or before_value == after_value:
            continue
        if code in seen_codes:
            continue
        changes.append(_scalar_change(path, code, label, before_value, after_value))
        seen_codes.add(code)

    for path, code, label in COUNT_FIELDS:
        before_value = _get(before, path)
        after_value = _get(after, path)
        if not isinstance(before_value, list) or not isinstance(after_value, list):
            continue
        item = _count_change(path, code, label, before_value, after_value)
        if item is not None:
            changes.append(item)

    return changes
