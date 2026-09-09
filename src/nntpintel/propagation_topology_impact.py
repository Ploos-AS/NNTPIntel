from __future__ import annotations

from collections import defaultdict

from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.storage import Storage


def topology_impact(storage: Storage) -> dict:
    topology = inferred_propagation_topology(storage)
    nodes = {int(item["server_id"]): dict(item) for item in topology["nodes"]}
    outgoing: dict[int, list[dict]] = defaultdict(list)
    incoming: dict[int, list[dict]] = defaultdict(list)

    for edge in topology["edges"]:
        source = int(edge["source_server_id"])
        target = int(edge["target_server_id"])
        outgoing[source].append(edge)
        incoming[target].append(edge)

    max_degree = max(
        (len(outgoing[server_id]) + len(incoming[server_id]) for server_id in nodes),
        default=0,
    )
    max_weight = max(
        (
            sum(float(edge["confidence"]) for edge in outgoing[server_id])
            + sum(float(edge["confidence"]) for edge in incoming[server_id])
            for server_id in nodes
        ),
        default=0.0,
    )

    scored_nodes: list[dict] = []
    for server_id, node in nodes.items():
        out_edges = outgoing[server_id]
        in_edges = incoming[server_id]
        out_degree = len(out_edges)
        in_degree = len(in_edges)
        degree = out_degree + in_degree
        weighted = round(
            sum(float(edge["confidence"]) for edge in out_edges)
            + sum(float(edge["confidence"]) for edge in in_edges),
            3,
        )
        direction_balance = 0.0 if degree == 0 else min(out_degree, in_degree) / degree
        bridge_score = round(direction_balance, 3)
        degree_norm = 0.0 if max_degree == 0 else degree / max_degree
        weight_norm = 0.0 if max_weight == 0 else weighted / max_weight
        impact_score = round((0.45 * degree_norm + 0.4 * weight_norm + 0.15 * bridge_score) * 100, 1)
        scored_nodes.append(
            {
                **node,
                "out_degree": out_degree,
                "in_degree": in_degree,
                "degree": degree,
                "weighted_confidence": weighted,
                "bridge_score": bridge_score,
                "impact_score": impact_score,
                "inference": True,
            }
        )

    scored_nodes.sort(key=lambda item: (-item["impact_score"], item["host"]))

    scored_edges: list[dict] = []
    node_impact = {int(item["server_id"]): float(item["impact_score"]) for item in scored_nodes}
    for edge in topology["edges"]:
        source = int(edge["source_server_id"])
        target = int(edge["target_server_id"])
        endpoint_impact = max(node_impact.get(source, 0.0), node_impact.get(target, 0.0))
        edge_impact = round(float(edge["confidence"]) * endpoint_impact, 1)
        scored_edges.append({**edge, "impact_score": edge_impact})
    scored_edges.sort(
        key=lambda item: (-item["impact_score"], item["source_host"], item["target_host"])
    )

    return {
        "model": "inferred_topology_impact",
        "authoritative_topology": False,
        "disclaimer": (
            "Impact scores rank observed inferred topology only; they do not establish "
            "physical NNTP centrality, direct peering, or operational dependency."
        ),
        "node_count": len(scored_nodes),
        "edge_count": len(scored_edges),
        "nodes": scored_nodes,
        "edges": scored_edges,
    }
