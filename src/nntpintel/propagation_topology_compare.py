from __future__ import annotations

from copy import deepcopy

from nntpintel.propagation_topology_export import topology_evidence_bundle
from nntpintel.propagation_topology_semantic_changes import semantic_evidence_changes
from nntpintel.storage import Storage


def _fingerprint(bundle: dict) -> str | None:
    integrity = bundle.get("integrity")
    if not isinstance(integrity, dict):
        return None
    value = integrity.get("fingerprint")
    return str(value) if value is not None else None


def _diff_values(before: object, after: object, path: str = "$") -> list[dict]:
    if type(before) is not type(after):
        return [{"path": path, "change": "changed", "before": before, "after": after}]

    if isinstance(before, dict):
        changes: list[dict] = []
        before_keys = set(before)
        after_keys = set(after)
        for key in sorted(before_keys - after_keys):
            changes.append(
                {"path": f"{path}.{key}", "change": "removed", "before": before[key], "after": None}
            )
        for key in sorted(after_keys - before_keys):
            changes.append(
                {"path": f"{path}.{key}", "change": "added", "before": None, "after": after[key]}
            )
        for key in sorted(before_keys & after_keys):
            changes.extend(_diff_values(before[key], after[key], f"{path}.{key}"))
        return changes

    if isinstance(before, list):
        if before == after:
            return []
        return [{"path": path, "change": "changed", "before": before, "after": after}]

    if before != after:
        return [{"path": path, "change": "changed", "before": before, "after": after}]
    return []


def compare_evidence_bundles(before: dict, after: dict) -> dict:
    before_copy = deepcopy(before)
    after_copy = deepcopy(after)
    before_copy.pop("generated_at", None)
    after_copy.pop("generated_at", None)

    before_fp = _fingerprint(before)
    after_fp = _fingerprint(after)
    unchanged = before_fp is not None and before_fp == after_fp
    changes = [] if unchanged else _diff_values(before_copy, after_copy)
    semantic_changes = [] if unchanged else semantic_evidence_changes(before, after)

    sections = sorted(
        {
            item["path"].split(".", 2)[1]
            for item in changes
            if item["path"].startswith("$.") and len(item["path"].split(".", 2)) >= 2
        }
    )
    return {
        "model": "nntpintel_topology_evidence_bundle_diff",
        "schema_version": 1,
        "before": {
            "ref": before.get("conclusion", {}).get("ref"),
            "fingerprint": before_fp,
        },
        "after": {
            "ref": after.get("conclusion", {}).get("ref"),
            "fingerprint": after_fp,
        },
        "same_fingerprint": unchanged,
        "changed": not unchanged,
        "change_count": len(changes),
        "changed_sections": sections,
        "semantic_change_count": len(semantic_changes),
        "semantic_changes": semantic_changes,
        "changes": changes,
        "limitations": [
            "This diff compares bundle content; it does not prove a real-world NNTP topology change.",
            "generated_at is ignored so export timing alone does not create a change.",
            "Semantic summaries are deterministic field interpretations, not operator-confirmed events.",
            "List changes are reported at list granularity in schema version 1.",
        ],
    }


def compare_topology_refs(storage: Storage, before_ref: str, after_ref: str) -> dict | None:
    before = topology_evidence_bundle(storage, before_ref)
    after = topology_evidence_bundle(storage, after_ref)
    if before is None or after is None:
        return None
    return compare_evidence_bundles(before, after)
