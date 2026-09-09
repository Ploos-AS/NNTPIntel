from __future__ import annotations

from html import escape
from urllib.parse import quote

from nntpintel.propagation_topology_communities import topology_communities
from nntpintel.storage import Storage


def communities_page(storage: Storage) -> str:
    data = topology_communities(storage)
    rows = "".join(
        "<tr>"
        f'<td>{item["community_id"]}</td>'
        f'<td>{item["server_count"]}</td>'
        f'<td>{item["edge_count"]}</td>'
        f'<td>{escape(", ".join(str(server["host"]) for server in item["servers"]))}</td>'
        f'<td>{item["average_edge_confidence"] if item["average_edge_confidence"] is not None else ""}</td>'
        f'<td>{item["average_impact_score"]}</td>'
        f'<td>{item["max_impact_score"]}</td>'
        f'<td>{item["open_incident_count"]}</td>'
        f'<td>{item["affected_server_count"]}</td>'
        f'<td><a href="/web/propagation/topology/explain/{quote(f"community:{item["community_id"]}", safe="")}">Explain</a></td>'
        "</tr>"
        for item in data["communities"]
    ) or '<tr><td colspan="10">No inferred topology communities yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology communities - NNTPIntel</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0 2rem}}.card,table{{background:#182028;border:1px solid #2d3944}}.card{{min-width:180px;padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/conclusions">Explainable conclusions</a> · <a href="/web/propagation/topology/impact">Impact / centrality</a> · <a href="/web/propagation/topology/incidents">Topology incidents</a></p>
<h2>Topology communities / clusters</h2>
<p class="warning"><strong>Inference only.</strong> {escape(data["disclaimer"])}</p>
<div class="cards"><div class="card">Communities<div class="metric">{data["community_count"]}</div></div><div class="card">Isolated servers<div class="metric">{data["isolated_server_count"]}</div></div><div class="card">Clusters with open incidents<div class="metric">{data["communities_with_open_incidents"]}</div></div></div>
<table><thead><tr><th>Cluster</th><th>Servers</th><th>Edges</th><th>Members</th><th>Avg confidence</th><th>Avg impact</th><th>Max impact</th><th>Open incidents</th><th>Affected servers</th><th></th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
