from __future__ import annotations

from nntpintel.propagation_topology_evidence import topology_evidence
from nntpintel.propagation_topology_incidents import list_topology_incidents
from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


def topology_conclusions(storage: Storage) -> dict:
    evidence = topology_evidence(storage)
    risk = topology_risk(storage)
    incidents = list_topology_incidents(storage)

    rows: list[dict] = []
    for item in evidence["servers"]:
        rows.append(
            {
                "conclusion_ref": item["evidence_ref"],
                "kind": "server_evidence",
                "label": item["host"],
                "summary": (
                    f'{len(item["visible_article_ids"])} visible article(s) from '
                    f'{len(item["article_ids"])} targeted article(s)'
                ),
            }
        )
    for item in evidence["edges"]:
        rows.append(
            {
                "conclusion_ref": item["evidence_ref"],
                "kind": "inferred_edge",
                "label": f'{item["source_host"]} → {item["target_host"]}',
                "summary": (
                    f'confidence {item["edge_confidence"]}; '
                    f'{item["directional_sample_count"]} directional sample(s)'
                ),
            }
        )
    for item in risk["servers"]:
        rows.append(
            {
                "conclusion_ref": item["conclusion_ref"],
                "kind": "server_risk",
                "label": item["host"],
                "summary": (
                    f'risk {item["risk_score"]} ({item["risk_level"]}); '
                    f'evidence {item["evidence_level"]}'
                ),
            }
        )
    for item in risk["communities"]:
        rows.append(
            {
                "conclusion_ref": item["conclusion_ref"],
                "kind": "community",
                "label": f'Community {item["community_id"]}',
                "summary": (
                    f'{item["server_count"]} server(s); risk '
                    f'{item["risk_score"]} ({item["risk_level"]})'
                ),
            }
        )
    for item in incidents:
        rows.append(
            {
                "conclusion_ref": item["conclusion_ref"],
                "kind": "incident",
                "label": f'Incident {item["id"]}: {item["host"]}',
                "summary": (
                    f'{item["severity"]}/{item["status"]}; triage '
                    f'{item["triage_priority_score"]}; evidence {item["evidence_level"]}'
                ),
            }
        )

    kind_order = {
        "incident": 0,
        "server_risk": 1,
        "community": 2,
        "inferred_edge": 3,
        "server_evidence": 4,
    }
    rows.sort(key=lambda item: (kind_order[item["kind"]], item["label"], item["conclusion_ref"]))
    counts: dict[str, int] = {}
    for item in rows:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1

    return {
        "model": "inferred_topology_explainable_conclusion_index",
        "authoritative_topology": False,
        "disclaimer": (
            "This index lists explainable NNTPIntel conclusions and evidence references. "
            "It is a navigation surface, not an additional inference or scoring model."
        ),
        "conclusion_count": len(rows),
        "counts_by_kind": counts,
        "conclusions": rows,
    }
