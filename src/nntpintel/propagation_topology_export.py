from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from nntpintel.propagation_topology_explain import explain_topology_ref
from nntpintel.storage import Storage

REF_PREFIXES = ("server:", "edge:", "risk:server:", "incident:", "community:")


def _collect_refs(value: object) -> list[str]:
    refs: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, str):
            if item.startswith(REF_PREFIXES):
                refs.add(item)
            return
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)

    visit(value)
    return sorted(refs)


def _quality_summary(explanation: dict) -> dict | None:
    if explanation.get("quality") is not None:
        return explanation["quality"]

    risk = explanation.get("risk")
    if isinstance(risk, dict):
        return {
            "evidence_level": risk.get("evidence_level"),
            "evidence_coverage": risk.get("evidence_coverage"),
            "evidence_freshness": risk.get("evidence_freshness"),
        }

    incident = explanation.get("incident")
    if isinstance(incident, dict):
        return {
            "evidence_level": incident.get("evidence_level"),
            "valid_presence_coverage": incident.get("valid_presence_coverage"),
            "freshness": incident.get("freshness"),
        }

    community = explanation.get("community")
    if isinstance(community, dict):
        return {
            "evidence_level": community.get("evidence_level"),
        }

    if explanation.get("conclusion_type") == "edge":
        return {
            "edge_confidence": explanation.get("edge_confidence"),
            "directional_sample_count": explanation.get("directional_sample_count"),
        }

    return None


def canonical_evidence_payload(bundle: dict) -> dict:
    return {
        "model": bundle["model"],
        "schema_version": bundle["schema_version"],
        "authoritative_topology": bundle["authoritative_topology"],
        "conclusion": bundle["conclusion"],
        "related_refs": bundle["related_refs"],
        "quality": bundle["quality"],
        "provenance": bundle["provenance"],
        "analysis": bundle["analysis"],
        "limitations": bundle["limitations"],
    }


def canonical_evidence_json(bundle: dict) -> str:
    return json.dumps(
        canonical_evidence_payload(bundle),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def evidence_fingerprint(bundle: dict) -> str:
    payload = canonical_evidence_json(bundle).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def topology_evidence_bundle(
    storage: Storage,
    evidence_ref: str,
    *,
    generated_at: str | None = None,
) -> dict | None:
    explanation = explain_topology_ref(storage, evidence_ref)
    if explanation is None:
        return None

    timestamp = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    related_refs = _collect_refs(explanation)
    if evidence_ref not in related_refs:
        related_refs.insert(0, evidence_ref)

    bundle = {
        "model": "nntpintel_topology_evidence_bundle",
        "schema_version": 1,
        "generated_at": timestamp,
        "authoritative_topology": False,
        "conclusion": {
            "ref": evidence_ref,
            "type": explanation["conclusion_type"],
            "why": explanation["why"],
        },
        "related_refs": related_refs,
        "quality": _quality_summary(explanation),
        "provenance": explanation.get("evidence"),
        "analysis": {
            key: value
            for key, value in explanation.items()
            if key
            not in {
                "model",
                "evidence_ref",
                "conclusion_type",
                "authoritative_topology",
                "why",
                "quality",
                "evidence",
                "limitations",
            }
        },
        "limitations": explanation["limitations"],
    }
    bundle["integrity"] = {
        "algorithm": "sha256",
        "scope": "canonical_evidence_payload_v1",
        "fingerprint": evidence_fingerprint(bundle),
    }
    return bundle
