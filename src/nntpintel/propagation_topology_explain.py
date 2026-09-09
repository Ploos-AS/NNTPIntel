from __future__ import annotations

from nntpintel.propagation_topology_evidence import topology_evidence
from nntpintel.propagation_topology_incidents import list_topology_incidents
from nntpintel.propagation_topology_quality import topology_data_quality
from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


def _base(evidence_ref: str, conclusion_type: str, why: str) -> dict:
    return {
        "model": "inferred_topology_conclusion_explanation",
        "evidence_ref": evidence_ref,
        "conclusion_type": conclusion_type,
        "authoritative_topology": False,
        "why": why,
    }


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
        result = _base(
            evidence_ref,
            "server",
            f'NNTPIntel has {len(item["campaign_ids"])} propagation campaign(s) targeting '
            f'{item["host"]}, covering {len(item["article_ids"])} article(s), with '
            f'{len(item["visible_article_ids"])} article(s) validly observed present.',
        )
        result.update(
            {
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
        )
        return result

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
        result = _base(
            evidence_ref,
            "edge",
            f'Across {item["directional_sample_count"]} directional sample(s), '
            f'{item["source_host"]} was repeatedly observed before {item["target_host"]}; '
            f'the inferred edge confidence is {item["edge_confidence"]}.',
        )
        result.update(
            {
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
        )
        return result

    if evidence_ref.startswith("risk:server:"):
        try:
            server_id = int(evidence_ref.rsplit(":", 1)[1])
        except ValueError:
            return None
        item = next((row for row in risk["servers"] if int(row["server_id"]) == server_id), None)
        if item is None:
            return None
        server_evidence = next((row for row in evidence["servers"] if int(row["server_id"]) == server_id), None)
        result = _base(
            evidence_ref,
            "risk_server",
            f'{item["host"]} has topology risk {item["risk_score"]} ({item["risk_level"]}) from '
            f'incident {item["incident_score"]}, resilience {item["resilience_score"]}, impact '
            f'{item["impact_score"]}, gateway {item["gateway_score"]}, and incident-scope inputs.',
        )
        result.update(
            {
                "server_id": server_id,
                "host": item["host"],
                "risk": item,
                "evidence": server_evidence,
                "limitations": [
                    "The risk score is a deterministic internal triage ranking, not a failure probability.",
                    "Evidence quality is reported separately and does not adjust the risk score.",
                    "Inputs depend on inferred topology and do not prove operational dependency.",
                ],
            }
        )
        return result

    if evidence_ref.startswith("incident:"):
        try:
            incident_id = int(evidence_ref.split(":", 1)[1])
        except ValueError:
            return None
        incidents = list_topology_incidents(storage)
        item = next((row for row in incidents if int(row["id"]) == incident_id), None)
        if item is None:
            return None
        server_id = int(item["server_id"])
        server_evidence = next((row for row in evidence["servers"] if int(row["server_id"]) == server_id), None)
        result = _base(
            evidence_ref,
            "incident",
            f'Incident {incident_id} is {item["severity"]}/{item["status"]} for {item["host"]}; '
            f'its triage priority is {item["triage_priority_score"]} with '
            f'{item["evidence_level"]} evidence.',
        )
        result.update(
            {
                "incident": item,
                "server_id": server_id,
                "host": item["host"],
                "evidence": server_evidence,
                "limitations": [
                    "Incident severity is not downgraded when evidence quality is weak.",
                    "Triage priority combines severity, evidence strength, status, and inferred impact.",
                    "Topology incidents describe NNTPIntel observations, not confirmed operator incidents.",
                ],
            }
        )
        return result

    if evidence_ref.startswith("community:"):
        try:
            community_id = int(evidence_ref.split(":", 1)[1])
        except ValueError:
            return None
        item = next(
            (row for row in risk["communities"] if int(row["community_id"]) == community_id),
            None,
        )
        if item is None:
            return None
        member_evidence = [
            row for row in evidence["servers"] if row["evidence_ref"] in set(item["evidence_refs"])
        ]
        result = _base(
            evidence_ref,
            "community",
            f'Community {community_id} groups {item["server_count"]} server(s) and has risk '
            f'{item["risk_score"]} ({item["risk_level"]}); the score reflects member risk, '
            "incident pressure, and gateway exposure.",
        )
        result.update(
            {
                "community_id": community_id,
                "community": item,
                "evidence": member_evidence,
                "limitations": [
                    "Communities are strong-edge connected components, not administrative domains.",
                    "Community risk is an aggregate triage ranking, not a reliability metric.",
                    "Membership depends on the current inferred graph and confidence threshold.",
                ],
            }
        )
        return result

    return None
