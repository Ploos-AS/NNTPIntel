from __future__ import annotations

from collections import defaultdict, deque

from nntpintel.propagation_topology_impact import topology_impact
from nntpintel.storage import Storage


def topology_communities(storage: Storage) -> dict:
    impact = topology_impact(storage)
    nodes = {int(item["server_id"]): dict(item) for item in impact["nodes"]}
    adjacency: dict[int, set[int]] = defaultdict(set)
    edge_by_pair: dict[tuple[int, int], dict] = {}

    for edge in impact["edges"]:
        source = int(edge["source_server_id"])
        target = int(edge["target_server_id"])
        adjacency[source].add(target)
        adjacency[target].add(source)
        edge_by_pair[tuple(sorted((source, target)))] = edge

    communities: list[dict] = []
    assigned: dict[int, int] = {}
    visited: set[int] = set()

    for server_id in sorted(nodes, key=lambda item: str(nodes[item]["host"])):
        if server_id in visited:
            continue
        queue = deque([server_id])
        component: list[int] = []
        visited.add(server_id)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        component.sort(key=lambda item: str(nodes[item]["host"]))
        community_id = len(communities) + 1
        for item in component:
            assigned[item] = community_id

        internal_edges = [
            edge
            for pair, edge in edge_by_pair.items()
            if pair[0] in component and pair[1] in component
        ]
        max_impact = max((float(nodes[item]["impact_score"]) for item in component), default=0.0)
        avg_impact = (
            round(sum(float(nodes[item]["impact_score"]) for item in component) / len(component), 1)
            if component
            else 0.0
        )
        avg_confidence = (
            round(sum(float(edge["confidence"]) for edge in internal_edges) / len(internal_edges), 3)
            if internal_edges
            else None
        )
        communities.append(
            {
                "community_id": community_id,
                "server_count": len(component),
                "edge_count": len(internal_edges),
                "average_edge_confidence": avg_confidence,
                "average_impact_score": avg_impact,
                "max_impact_score": round(max_impact, 1),
                "servers": [
                    {
                        "server_id": item,
                        "host": nodes[item]["host"],
                        "impact_score": nodes[item]["impact_score"],
                    }
                    for item in component
                ],
            }
        )

    communities.sort(
        key=lambda item: (
            -item["server_count"],
            -item["max_impact_score"],
            item["servers"][0]["host"] if item["servers"] else "",
        )
    )

    return {
        "model": "inferred_topology_communities",
        "authoritative_topology": False,
        "disclaimer": (
            "Communities are connected components of NNTPIntel's observed inferred precedence graph; "
            "they do not establish administrative domains, direct peering groups, or real feed clusters."
        ),
        "community_count": len(communities),
        "isolated_server_count": sum(1 for item in communities if item["server_count"] == 1),
        "communities": communities,
        "server_community": {str(server_id): community_id for server_id, community_id in assigned.items()},
    }
