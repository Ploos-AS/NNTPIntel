from __future__ import annotations

from collections import defaultdict

from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.propagation_topology_cross_cluster import cross_cluster_intelligence
from nntpintel.propagation_topology_incidents import list_topology_incidents
from nntpintel.propagation_topology_quality import topology_data_quality
from nntpintel.propagation_topology_resilience import topology_resilience
from nntpintel.storage import Storage


def _risk_level(score: float) -> str:
    if score >= 75.0:
        return "critical"
    if score >= 50.0:
        return "high"
    if score >= 25.0:
        return "moderate"
    return "low"


def _evidence_level(coverage: float, freshness: str, global_quality: int) -> str:
    if freshness in {"very_stale", "no_valid_presence"} or coverage < 0.5 or global_quality < 40:
        return "low"
    if freshness == "stale" or coverage < 0.75 or global_quality < 60:
        return "limited"
    if coverage >= 0.9 and freshness == "fresh" and global_quality >= 80:
        return "high"
    return "moderate"


def topology_risk(storage: Storage) -> dict:
    communities = topology_communities(storage)
    resilience = topology_resilience(storage)
    cross_cluster = cross_cluster_intelligence(storage)
    incidents = list_topology_incidents(storage, include_resolved=False)
    quality = topology_data_quality(storage)

    community_by_server = {
        int(server_id): int(community_id)
        for server_id, community_id in communities["server_community"].items()
    }
    gateway_by_server = {
        int(item["server_id"]): item for item in cross_cluster["gateway_servers"]
    }
    quality_by_server = {
        int(item["server_id"]): item for item in quality["servers"]
    }
    incidents_by_server: dict[int, list[dict]] = defaultdict(list)
    for incident in incidents:
        incidents_by_server[int(incident["server_id"])].append(incident)

    max_gateway_edges = max(
        (int(item["cross_edge_count"]) for item in cross_cluster["gateway_servers"]),
        default=0,
    )
    scope_score = {
        "none": 0.0,
        "single_community": 45.0,
        "multi_community": 100.0,
    }.get(str(cross_cluster["incident_scope"]), 0.0)

    server_rows: list[dict] = []
    for node in resilience["nodes"]:
        server_id = int(node["server_id"])
        server_incidents = incidents_by_server[server_id]
        critical = sum(1 for item in server_incidents if item["severity"] == "critical")
        warning = sum(1 for item in server_incidents if item["severity"] == "warning")
        recovering = sum(1 for item in server_incidents if item["status"] == "recovering")
        incident_score = 0.0
        if critical:
            incident_score = min(100.0, 85.0 + 5.0 * (critical - 1) + 3.0 * warning)
        elif warning:
            incident_score = min(80.0, 55.0 + 5.0 * (warning - 1))
        if recovering and incident_score:
            incident_score = max(25.0, incident_score - 15.0)

        gateway = gateway_by_server.get(server_id)
        gateway_score = 0.0
        if gateway is not None and max_gateway_edges:
            edge_ratio = int(gateway["cross_edge_count"]) / max_gateway_edges
            confidence = float(gateway["max_edge_confidence"])
            gateway_score = round((0.65 * edge_ratio + 0.35 * confidence) * 100, 1)

        impact_score = float(node["impact_score"])
        resilience_score = float(node["resilience_score"])
        risk_score = round(
            0.4 * incident_score
            + 0.2 * resilience_score
            + 0.2 * impact_score
            + 0.15 * gateway_score
            + 0.05 * scope_score,
            1,
        )
        server_quality = quality_by_server.get(server_id)
        coverage = float(server_quality["valid_presence_coverage"]) if server_quality else 0.0
        freshness = str(server_quality["freshness"]) if server_quality else "no_valid_presence"
        evidence_level = _evidence_level(coverage, freshness, int(quality["quality_score"]))
        server_rows.append(
            {
                "server_id": server_id,
                "host": node["host"],
                "community_id": community_by_server.get(server_id),
                "risk_score": risk_score,
                "risk_level": _risk_level(risk_score),
                "evidence_ref": f"server:{server_id}",
                "evidence_level": evidence_level,
                "evidence_quality_score": int(quality["quality_score"]),
                "evidence_coverage": round(coverage, 3),
                "evidence_freshness": freshness,
                "risk_score_quality_adjusted": False,
                "incident_score": round(incident_score, 1),
                "open_incident_count": len(server_incidents),
                "critical_incident_count": critical,
                "warning_incident_count": warning,
                "recovering_incident_count": recovering,
                "impact_score": round(impact_score, 1),
                "resilience_score": round(resilience_score, 1),
                "gateway_score": round(gateway_score, 1),
                "is_gateway": gateway is not None,
                "incident_scope": cross_cluster["incident_scope"],
                "inference": True,
            }
        )

    server_rows.sort(key=lambda item: (-item["risk_score"], item["host"]))
    rows_by_community: dict[int, list[dict]] = defaultdict(list)
    for row in server_rows:
        if row["community_id"] is not None:
            rows_by_community[int(row["community_id"])].append(row)

    evidence_rank = {"low": 0, "limited": 1, "moderate": 2, "high": 3}
    community_rows: list[dict] = []
    for community in communities["communities"]:
        community_id = int(community["community_id"])
        members = rows_by_community[community_id]
        max_risk = max((float(item["risk_score"]) for item in members), default=0.0)
        average_risk = (
            sum(float(item["risk_score"]) for item in members) / len(members)
            if members
            else 0.0
        )
        incident_pressure = min(
            100.0,
            35.0 * int(community["open_incident_count"])
            + 15.0 * int(community["affected_server_count"]),
        )
        gateway_count = sum(1 for item in members if item["is_gateway"])
        gateway_exposure = 0.0 if not members else (gateway_count / len(members)) * 100.0
        risk_score = round(
            0.55 * max_risk
            + 0.2 * average_risk
            + 0.15 * incident_pressure
            + 0.1 * gateway_exposure,
            1,
        )
        community_evidence = min(
            (str(item["evidence_level"]) for item in members),
            key=lambda value: evidence_rank[value],
            default="low",
        )
        community_rows.append(
            {
                "community_id": community_id,
                "risk_score": risk_score,
                "risk_level": _risk_level(risk_score),
                "evidence_refs": [str(item["evidence_ref"]) for item in members],
                "evidence_level": community_evidence,
                "risk_score_quality_adjusted": False,
                "server_count": int(community["server_count"]),
                "open_incident_count": int(community["open_incident_count"]),
                "affected_server_count": int(community["affected_server_count"]),
                "gateway_server_count": gateway_count,
                "max_server_risk_score": round(max_risk, 1),
                "average_server_risk_score": round(average_risk, 1),
                "members": [item["host"] for item in members],
                "inference": True,
            }
        )

    community_rows.sort(key=lambda item: (-item["risk_score"], item["community_id"]))

    return {
        "model": "inferred_topology_risk_synthesis",
        "authoritative_topology": False,
        "disclaimer": (
            "Risk scores are internal triage rankings synthesized from NNTPIntel's inferred topology, "
            "incidents, impact, resilience, communities, and gateway observations. Evidence quality is "
            "reported separately and never increases or decreases the risk score."
        ),
        "evidence_model": "inferred_topology_evidence_provenance",
        "incident_scope": cross_cluster["incident_scope"],
        "data_quality_score": int(quality["quality_score"]),
        "data_quality_level": quality["quality_level"],
        "risk_score_quality_adjusted": False,
        "server_count": len(server_rows),
        "community_count": len(community_rows),
        "high_risk_server_count": sum(1 for item in server_rows if item["risk_score"] >= 50.0),
        "high_risk_low_evidence_server_count": sum(
            1
            for item in server_rows
            if item["risk_score"] >= 50.0 and item["evidence_level"] in {"low", "limited"}
        ),
        "high_risk_community_count": sum(
            1 for item in community_rows if item["risk_score"] >= 50.0
        ),
        "servers": server_rows,
        "communities": community_rows,
    }
