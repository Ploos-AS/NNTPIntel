from __future__ import annotations

from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.propagation_topology_anomalies import topology_anomalies
from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.propagation_topology_cross_cluster import cross_cluster_intelligence
from nntpintel.propagation_topology_incidents import list_topology_incidents
from nntpintel.propagation_topology_resilience import topology_resilience
from nntpintel.propagation_topology_risk import topology_risk
from nntpintel.storage import Storage


def topology_overview(storage: Storage) -> dict:
    topology = inferred_propagation_topology(storage)
    anomalies = topology_anomalies(storage)
    incidents = list_topology_incidents(storage, include_resolved=False)
    communities = topology_communities(storage)
    cross_cluster = cross_cluster_intelligence(storage)
    resilience = topology_resilience(storage)
    risk = topology_risk(storage)

    critical_incidents = sum(1 for item in incidents if item["severity"] == "critical")
    recovering_incidents = sum(1 for item in incidents if item["status"] == "recovering")
    high_risk_servers = [item for item in risk["servers"] if item["risk_score"] >= 50.0]
    high_risk_communities = [
        item for item in risk["communities"] if item["risk_score"] >= 50.0
    ]
    critical_nodes = [
        item for item in resilience["nodes"] if item.get("resilience_level") == "critical"
    ]

    attention: list[dict] = []
    for item in high_risk_servers[:5]:
        evidence = str(item["evidence_level"])
        attention.append(
            {
                "priority": 1 if item["risk_score"] >= 75.0 else 2,
                "kind": "server_risk",
                "label": item["host"],
                "detail": (
                    f'Risk {item["risk_score"]} ({item["risk_level"]}); '
                    f'evidence {evidence}'
                ),
                "score": item["risk_score"],
                "evidence_level": evidence,
                "evidence_caution": evidence in {"low", "limited"},
            }
        )
    for item in high_risk_communities[:3]:
        evidence = str(item["evidence_level"])
        attention.append(
            {
                "priority": 2,
                "kind": "community_risk",
                "label": f'Community {item["community_id"]}',
                "detail": (
                    f'Risk {item["risk_score"]} ({item["risk_level"]}); '
                    f'evidence {evidence}'
                ),
                "score": item["risk_score"],
                "evidence_level": evidence,
                "evidence_caution": evidence in {"low", "limited"},
            }
        )
    if cross_cluster["incident_scope"] == "multi_community":
        attention.append(
            {
                "priority": 1,
                "kind": "incident_scope",
                "label": "Multi-community incident scope",
                "detail": "Open inferred topology incidents span multiple communities.",
                "score": 100.0,
                "evidence_level": risk["data_quality_level"],
                "evidence_caution": risk["data_quality_level"] in {"weak", "limited"},
            }
        )
    attention.sort(key=lambda item: (item["priority"], -float(item["score"]), item["label"]))

    if critical_incidents or any(item["risk_score"] >= 75.0 for item in risk["servers"]):
        posture = "critical"
    elif incidents or high_risk_servers or cross_cluster["incident_scope"] == "multi_community":
        posture = "attention"
    elif anomalies["anomaly_count"]:
        posture = "watch"
    else:
        posture = "nominal"

    return {
        "model": "inferred_topology_executive_overview",
        "authoritative_topology": False,
        "disclaimer": (
            "This overview is an operator triage summary of NNTPIntel's inferred observations. "
            "Risk posture is not quality-adjusted; evidence confidence is shown separately so weak or "
            "stale data lowers certainty without inflating or suppressing observed risk signals."
        ),
        "posture": posture,
        "data_quality": {
            "score": risk["data_quality_score"],
            "level": risk["data_quality_level"],
            "risk_score_quality_adjusted": False,
            "high_risk_low_evidence_server_count": risk[
                "high_risk_low_evidence_server_count"
            ],
        },
        "topology": {
            "node_count": topology["node_count"],
            "edge_count": topology["edge_count"],
            "community_count": len(communities["communities"]),
            "gateway_server_count": len(cross_cluster["gateway_servers"]),
        },
        "signals": {
            "anomaly_count": anomalies["anomaly_count"],
            "open_incident_count": len(incidents),
            "critical_incident_count": critical_incidents,
            "recovering_incident_count": recovering_incidents,
            "incident_scope": cross_cluster["incident_scope"],
            "high_risk_server_count": len(high_risk_servers),
            "high_risk_community_count": len(high_risk_communities),
            "critical_resilience_node_count": len(critical_nodes),
        },
        "attention": attention[:8],
        "top_servers": risk["servers"][:5],
        "top_communities": risk["communities"][:5],
    }
