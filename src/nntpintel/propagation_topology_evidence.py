from __future__ import annotations

from collections import defaultdict

from nntpintel.propagation_topology import inferred_propagation_topology
from nntpintel.storage import Storage


def _server_ref(server_id: int) -> str:
    return f"server:{server_id}"


def _edge_ref(source_id: int, target_id: int) -> str:
    return f"edge:{source_id}->{target_id}"


def topology_evidence(storage: Storage, *, max_articles_per_edge: int = 50) -> dict:
    if max_articles_per_edge < 1 or max_articles_per_edge > 500:
        raise ValueError("max_articles_per_edge must be between 1 and 500")

    topology = inferred_propagation_topology(storage)
    with storage.connect() as conn:
        target_rows = conn.execute(
            """
            SELECT pc.id AS campaign_id, pc.article_id, pa.message_id,
                   s.id AS server_id, s.host, e.id AS endpoint_id
            FROM propagation_campaigns pc
            JOIN propagation_articles pa ON pa.id = pc.article_id
            JOIN propagation_campaign_endpoints pce ON pce.campaign_id = pc.id
            JOIN endpoints e ON e.id = pce.endpoint_id
            JOIN servers s ON s.id = e.server_id
            ORDER BY pc.article_id, pc.id, s.id, e.id
            """
        ).fetchall()
        visible_rows = conn.execute(
            """
            SELECT po.id AS observation_id, po.article_id, pa.message_id,
                   s.id AS server_id, s.host, po.endpoint_id, po.observed_at
            FROM propagation_observations po
            JOIN propagation_articles pa ON pa.id = po.article_id
            JOIN endpoints e ON e.id = po.endpoint_id
            JOIN servers s ON s.id = e.server_id
            WHERE po.present = 1 AND po.error IS NULL AND po.response_code = 223
            ORDER BY po.article_id, s.id, po.observed_at, po.id
            """
        ).fetchall()

    campaigns_by_article_server: dict[tuple[int, int], set[int]] = defaultdict(set)
    endpoints_by_article_server: dict[tuple[int, int], set[int]] = defaultdict(set)
    messages: dict[int, str] = {}
    hosts: dict[int, str] = {}
    targeted_articles_by_server: dict[int, set[int]] = defaultdict(set)
    for row in target_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        campaigns_by_article_server[(article_id, server_id)].add(int(row["campaign_id"]))
        endpoints_by_article_server[(article_id, server_id)].add(int(row["endpoint_id"]))
        targeted_articles_by_server[server_id].add(article_id)
        messages[article_id] = str(row["message_id"])
        hosts[server_id] = str(row["host"])

    first_visible: dict[tuple[int, int], dict] = {}
    valid_observation_ids_by_server: dict[int, list[int]] = defaultdict(list)
    for row in visible_rows:
        article_id = int(row["article_id"])
        server_id = int(row["server_id"])
        key = (article_id, server_id)
        if key not in first_visible:
            first_visible[key] = {
                "observation_id": int(row["observation_id"]),
                "endpoint_id": int(row["endpoint_id"]),
                "observed_at": str(row["observed_at"]),
            }
        valid_observation_ids_by_server[server_id].append(int(row["observation_id"]))
        messages[article_id] = str(row["message_id"])
        hosts[server_id] = str(row["host"])

    server_evidence = []
    for node in topology["nodes"]:
        server_id = int(node["server_id"])
        article_ids = sorted(targeted_articles_by_server.get(server_id, set()))
        campaign_ids = sorted(
            {
                campaign_id
                for article_id in article_ids
                for campaign_id in campaigns_by_article_server.get((article_id, server_id), set())
            }
        )
        visible_article_ids = [
            article_id for article_id in article_ids if (article_id, server_id) in first_visible
        ]
        server_evidence.append(
            {
                "evidence_ref": _server_ref(server_id),
                "server_id": server_id,
                "host": node["host"],
                "campaign_ids": campaign_ids,
                "article_ids": article_ids,
                "message_ids": [messages[item] for item in article_ids if item in messages],
                "visible_article_ids": visible_article_ids,
                "valid_presence_observation_ids": valid_observation_ids_by_server.get(server_id, [])[:200],
            }
        )

    edge_evidence = []
    for edge in topology["edges"]:
        source_id = int(edge["source_server_id"])
        target_id = int(edge["target_server_id"])
        comparable = sorted(
            targeted_articles_by_server.get(source_id, set())
            & targeted_articles_by_server.get(target_id, set())
        )
        articles = []
        for article_id in comparable:
            source = first_visible.get((article_id, source_id))
            target = first_visible.get((article_id, target_id))
            if source is None or target is None:
                continue
            source_at = source["observed_at"]
            target_at = target["observed_at"]
            articles.append(
                {
                    "article_id": article_id,
                    "message_id": messages.get(article_id),
                    "source_campaign_ids": sorted(
                        campaigns_by_article_server.get((article_id, source_id), set())
                    ),
                    "target_campaign_ids": sorted(
                        campaigns_by_article_server.get((article_id, target_id), set())
                    ),
                    "source_endpoint_ids": sorted(
                        endpoints_by_article_server.get((article_id, source_id), set())
                    ),
                    "target_endpoint_ids": sorted(
                        endpoints_by_article_server.get((article_id, target_id), set())
                    ),
                    "source_observation_id": source["observation_id"],
                    "target_observation_id": target["observation_id"],
                    "source_first_seen_at": source_at,
                    "target_first_seen_at": target_at,
                }
            )
        edge_evidence.append(
            {
                "evidence_ref": _edge_ref(source_id, target_id),
                "source_server_id": source_id,
                "source_host": edge["source_host"],
                "target_server_id": target_id,
                "target_host": edge["target_host"],
                "edge_confidence": edge["confidence"],
                "directional_sample_count": edge["directional_sample_count"],
                "supporting_article_count": len(articles),
                "supporting_articles": articles[:max_articles_per_edge],
            }
        )

    return {
        "model": "inferred_topology_evidence_provenance",
        "authoritative_topology": False,
        "disclaimer": (
            "Evidence provenance links NNTPIntel's inferred conclusions back to recorded campaigns, "
            "Message-IDs, endpoints, and valid presence observations. Provenance improves explainability "
            "but does not prove direct NNTP peering or physical topology."
        ),
        "server_evidence_count": len(server_evidence),
        "edge_evidence_count": len(edge_evidence),
        "servers": server_evidence,
        "edges": edge_evidence,
    }
