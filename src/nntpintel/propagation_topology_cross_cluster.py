from __future__ import annotations

from collections import defaultdict

from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.propagation_topology_impact import topology_impact
from nntpintel.storage import Storage


def cross_cluster_intelligence(storage: Storage) -> dict:
    communities = topology_communities(storage)
    impact = topology_impact(storage)
    server_community = {
        int(server_id): int(community_id)
        for server_id, community_id in communities["server_community"].items()
    }

    cross_edges: list[dict] = []
    gateways: dict[int, dict] = {}
    links: dict[tuple[int, int], list[dict]] = defaultdict(list)

    for edge in impact["edges"]:
        source_id = int(edge["source_server_id"])
        target_id = int(edge["target_server_id"])
        source_community = server_community.get(source_id)
        target_community = server_community.get(target_id)
        if source_community is None or target_community is None:
            continue
        if source_community == target_community:
            continue

        enriched = {
            **edge,
            "source_community_id": source_community,
            "target_community_id": target_community,
            "relation": "observed_cross_community_precedence",
            "inference": True,
        }
        cross_edges.append(enriched)
        links[(source_community, target_community)].append(enriched)

        for server_id, host, own, peer in (
            (source_id, edge["source_host"], source_community, target_community),
            (target_id, edge["target_host"], target_community, source_community),
        ):
            item = gateways.setdefault(
                server_id,
                {
                    "server_id": server_id,
                    "host": host,
                    "community_id": own,
                    "peer_community_ids": set(),
                    "cross_edge_count": 0,
                    "max_edge_impact_score": 0.0,
                    "max_edge_confidence": 0.0,
                },
            )
            item["peer_community_ids"].add(peer)
            item["cross_edge_count"] += 1
            item["max_edge_impact_score"] = max(
                float(item["max_edge_impact_score"]), float(edge.get("impact_score", 0.0))
            )
            item["max_edge_confidence"] = max(
                float(item["max_edge_confidence"]), float(edge["confidence"])
            )

    cross_edges.sort(
        key=lambda item: (
            -float(item.get("impact_score", 0.0)),
            -float(item["confidence"]),
            str(item["source_host"]),
            str(item["target_host"]),
        )
    )

    gateway_rows: list[dict] = []
    for item in gateways.values():
        gateway_rows.append(
            {
                **item,
                "peer_community_ids": sorted(item["peer_community_ids"]),
                "max_edge_impact_score": round(float(item["max_edge_impact_score"]), 1),
                "max_edge_confidence": round(float(item["max_edge_confidence"]), 3),
            }
        )
    gateway_rows.sort(
        key=lambda item: (
            -item["cross_edge_count"],
            -item["max_edge_impact_score"],
            str(item["host"]),
        )
    )

    community_links: list[dict] = []
    for (source_community, target_community), edges in links.items():
        community_links.append(
            {
                "source_community_id": source_community,
                "target_community_id": target_community,
                "edge_count": len(edges),
                "average_confidence": round(
                    sum(float(edge["confidence"]) for edge in edges) / len(edges), 3
                ),
                "max_impact_score": round(
                    max(float(edge.get("impact_score", 0.0)) for edge in edges), 1
                ),
                "source_gateway_hosts": sorted({str(edge["source_host"]) for edge in edges}),
                "target_gateway_hosts": sorted({str(edge["target_host"]) for edge in edges}),
            }
        )
    community_links.sort(
        key=lambda item: (
            -item["edge_count"],
            -item["max_impact_score"],
            item["source_community_id"],
            item["target_community_id"],
        )
    )

    affected = sorted(
        int(item["community_id"])
        for item in communities["communities"]
        if int(item["open_incident_count"]) > 0
    )
    if not affected:
        incident_scope = "none"
    elif len(affected) == 1:
        incident_scope = "single_community"
    else:
        incident_scope = "multi_community"

    return {
        "model": "inferred_cross_community_propagation",
        "authoritative_topology": False,
        "disclaimer": (
            "Cross-community edges and gateways are derived from observed inferred precedence and "
            "strong-edge community boundaries; they do not prove direct NNTP peering, physical gateways, "
            "or operational dependency."
        ),
        "community_min_confidence": communities["min_confidence"],
        "community_count": communities["community_count"],
        "cross_community_edge_count": len(cross_edges),
        "gateway_server_count": len(gateway_rows),
        "community_link_count": len(community_links),
        "incident_scope": incident_scope,
        "affected_community_ids": affected,
        "cross_community_edges": cross_edges,
        "gateway_servers": gateway_rows,
        "community_links": community_links,
    }
