from __future__ import annotations

from collections import defaultdict, deque

from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.propagation_topology_impact import topology_impact
from nntpintel.storage import Storage


def _component_count(nodes: set[int], edges: list[tuple[int, int]]) -> int:
    if not nodes:
        return 0
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in edges:
        if left in nodes and right in nodes:
            adjacency[left].add(right)
            adjacency[right].add(left)
    visited: set[int] = set()
    count = 0
    for node in sorted(nodes):
        if node in visited:
            continue
        count += 1
        queue = deque([node])
        visited.add(node)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
    return count


def topology_resilience(storage: Storage) -> dict:
    communities = topology_communities(storage)
    impact = topology_impact(storage)
    min_confidence = float(communities["min_confidence"])
    server_community = {
        int(server_id): int(community_id)
        for server_id, community_id in communities["server_community"].items()
    }
    hosts = {int(item["server_id"]): str(item["host"]) for item in impact["nodes"]}
    node_impact = {
        int(item["server_id"]): float(item["impact_score"]) for item in impact["nodes"]
    }

    strong_edges: list[tuple[int, int]] = []
    cross_edges: list[dict] = []
    for edge in impact["edges"]:
        source = int(edge["source_server_id"])
        target = int(edge["target_server_id"])
        if float(edge["confidence"]) >= min_confidence:
            strong_edges.append((source, target))
        if server_community.get(source) != server_community.get(target):
            cross_edges.append(edge)

    community_nodes: dict[int, set[int]] = defaultdict(set)
    for server_id, community_id in server_community.items():
        community_nodes[community_id].add(server_id)

    node_results: list[dict] = []
    for server_id in sorted(hosts, key=lambda item: hosts[item]):
        community_id = server_community.get(server_id)
        if community_id is None:
            continue
        nodes = community_nodes[community_id]
        baseline_components = _component_count(nodes, strong_edges)
        remaining_nodes = set(nodes) - {server_id}
        remaining_edges = [edge for edge in strong_edges if server_id not in edge]
        after_components = _component_count(remaining_nodes, remaining_edges)
        fragmentation_delta = max(0, after_components - baseline_components)
        lost_cross = sum(
            1
            for edge in cross_edges
            if server_id in {int(edge["source_server_id"]), int(edge["target_server_id"])}
        )
        cross_total = len(cross_edges)
        cross_loss_ratio = 0.0 if cross_total == 0 else lost_cross / cross_total
        fragmentation_norm = min(1.0, float(fragmentation_delta))
        impact_norm = node_impact.get(server_id, 0.0) / 100.0
        resilience_score = round(
            (0.55 * fragmentation_norm + 0.3 * cross_loss_ratio + 0.15 * impact_norm) * 100,
            1,
        )
        node_results.append(
            {
                "server_id": server_id,
                "host": hosts[server_id],
                "community_id": community_id,
                "community_server_count": len(nodes),
                "fragmentation_delta": fragmentation_delta,
                "lost_cross_community_edges": lost_cross,
                "cross_community_edge_loss_ratio": round(cross_loss_ratio, 3),
                "impact_score": round(node_impact.get(server_id, 0.0), 1),
                "resilience_score": resilience_score,
                "inference": True,
            }
        )

    node_results.sort(
        key=lambda item: (-item["resilience_score"], -item["fragmentation_delta"], item["host"])
    )

    edge_results: list[dict] = []
    for edge in impact["edges"]:
        source = int(edge["source_server_id"])
        target = int(edge["target_server_id"])
        source_community = server_community.get(source)
        target_community = server_community.get(target)
        is_cross = source_community != target_community
        fragmentation_delta = 0
        if (
            not is_cross
            and source_community is not None
            and float(edge["confidence"]) >= min_confidence
        ):
            nodes = community_nodes[source_community]
            baseline_components = _component_count(nodes, strong_edges)
            pair = {source, target}
            remaining = [item for item in strong_edges if set(item) != pair]
            fragmentation_delta = max(
                0, _component_count(nodes, remaining) - baseline_components
            )
        resilience_score = round(
            min(
                100.0,
                65.0 * min(1, fragmentation_delta)
                + (25.0 if is_cross else 0.0)
                + 10.0 * float(edge["confidence"]),
            ),
            1,
        )
        edge_results.append(
            {
                **edge,
                "source_community_id": source_community,
                "target_community_id": target_community,
                "cross_community": is_cross,
                "fragmentation_delta": fragmentation_delta,
                "resilience_score": resilience_score,
            }
        )

    edge_results.sort(
        key=lambda item: (
            -item["resilience_score"],
            -float(item["confidence"]),
            str(item["source_host"]),
            str(item["target_host"]),
        )
    )

    return {
        "model": "inferred_topology_resilience",
        "authoritative_topology": False,
        "disclaimer": (
            "Resilience scores simulate removal inside NNTPIntel's observed inferred precedence graph; "
            "they do not establish physical failure domains, direct NNTP dependencies, or real routing criticality."
        ),
        "community_min_confidence": min_confidence,
        "node_count": len(node_results),
        "edge_count": len(edge_results),
        "cross_community_edge_count": len(cross_edges),
        "critical_node_count": sum(1 for item in node_results if item["resilience_score"] >= 50.0),
        "critical_edge_count": sum(1 for item in edge_results if item["resilience_score"] >= 50.0),
        "nodes": node_results,
        "edges": edge_results,
    }
