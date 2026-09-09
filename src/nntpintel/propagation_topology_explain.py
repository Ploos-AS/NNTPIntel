from __future__ import annotations

from nntpintel.propagation_topology_evidence import topology_evidence
from nntpintel.propagation_topology_quality import topology_data_quality
from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


def explain_topology_ref(storage: Storage, evidence_ref: str) -> dict | None:
    evidence = topology_evidence(storage)
    quality = topology_data_quality(storage)
    risk = topology_risk(storage)

    if evidence_ref.startswith("server:"):
        try:
            server_id = int(evidence_ref.split(":", 1)[1])
        except ValueError:
            return None
        item = next((row for row in evidence["servers"] if int(row["server_id"]) == server_id), None)
        if item is None:
            return None
        quality_row = next((row for row in quality["servers"] if int(row["server_id"]) == server_id), None)
        risk_row = next((row for row in risk["servers"] if int(row["server_id"]) == server_id), None)
        why = (
            f'NNTPIntel has {len(item["campaign_ids"])} propagation campaign(s) targeting '
            f'{item["host"]}, covering {len(item["article_ids"])} article(s), with '
            f'{len(item["visible_article_ids"])} article(s) validly observed present.'
        )
        return {
            "model": "inferred_topology_conclusion_explanation",
            "evidence_ref": evidence_ref,
            "conclusion_type": "server",
            "authoritative_topology": False,
            "why": why,
            "host": item["host"],
            "server_id": server_id,
            "risk": risk_row,
            "quality": quality_row,
            "evidence": item,
            "limitations": [
                "Presence observations show what NNTPIntel observed, not direct feed relationships.",
                "Risk scores are internal triage rankings and are not quality-adjusted.",
                "Missing observations may reflect coverage gaps rather than server behavior.",
            ],
        }

    if evidence_ref.startswith("edge:"):
        payload = evidence_ref.split(":", 1)[1]
        try:
            source_text, target_text = payload.split("->", 1)
            source_id = int(source_text)
            target_id = int(target_text)
        except (ValueError, TypeError):
            return None
        item = next(
            (
                row
                for row in evidence["edges"]
                if int(row["source_server_id"]) == source_id
                and int(row["target_server_id"]) == target_id
            ),
            None,
        )
        if item is None:
            return None
        why = (
            f'Across {item["directional_sample_count"]} directional sample(s), '
            f'{item["source_host"]} was repeatedly observed before {item["target_host"]}; '
            f'the inferred edge confidence is {item["edge_confidence"]}.'
        )
        return {
            "model": "inferred_topology_conclusion_explanation",
            "evidence_ref": evidence_ref,
            "conclusion_type": "edge",
            "authoritative_topology": False,
            "why": why,
            "source_server_id": source_id,
            "source_host": item["source_host"],
            "target_server_id": target_id,
            "target_host": item["target_host"],
            "edge_confidence": item["edge_confidence"],
            "directional_sample_count": item["directional_sample_count"],
            "evidence": item,
            "limitations": [
                "Observed first-seen precedence does not prove direct NNTP peering.",
                "The edge may reflect indirect propagation paths, polling cadence, or timing effects.",
                "Confidence summarizes repeated observed precedence, not physical-topology certainty.",
            ],
        }

    return None
