from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_cross_cluster import cross_cluster_intelligence
from nntpintel.storage import Storage


def cross_cluster_page(storage: Storage) -> str:
    data = cross_cluster_intelligence(storage)
    gateway_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["community_id"]}</td>'
        f'<td>{escape(", ".join(str(value) for value in item["peer_community_ids"]))}</td>'
        f'<td>{item["cross_edge_count"]}</td>'
        f'<td>{item["max_edge_confidence"]}</td>'
        f'<td>{item["max_edge_impact_score"]}</td>'
        "</tr>"
        for item in data["gateway_servers"]
    ) or '<tr><td colspan="6">No inferred cross-community gateways yet.</td></tr>'
    edge_rows = "".join(
        "<tr>"
        f'<td>{item["source_community_id"]}</td>'
        f'<td>{escape(str(item["source_host"]))}</td><td>→</td>'
        f'<td>{escape(str(item["target_host"]))}</td>'
        f'<td>{item["target_community_id"]}</td>'
        f'<td>{item["confidence"]}</td>'
        f'<td>{item.get("impact_score", 0.0)}</td>'
        "</tr>"
        for item in data["cross_community_edges"]
    ) or '<tr><td colspan="7">No inferred cross-community edges yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cross-cluster propagation - NNTPIntel</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0 2rem}}.card,table{{background:#182028;border:1px solid #2d3944}}.card{{min-width:180px;padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}table{{width:100%;border-collapse:collapse;margin-bottom:2rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/communities">Communities</a></p>
<h2>Cross-cluster propagation intelligence</h2>
<p class="warning"><strong>Inference only.</strong> {escape(data["disclaimer"])}</p>
<div class="cards">
<div class="card">Boundary edges<div class="metric">{data["cross_community_edge_count"]}</div></div>
<div class="card">Gateway servers<div class="metric">{data["gateway_server_count"]}</div></div>
<div class="card">Community links<div class="metric">{data["community_link_count"]}</div></div>
<div class="card">Incident scope<div class="metric">{escape(str(data["incident_scope"]))}</div></div>
</div>
<p>Strong-edge community threshold: {data["community_min_confidence"]} · affected communities: {escape(", ".join(str(value) for value in data["affected_community_ids"]) or "none")}</p>
<h3>Observed gateway servers</h3><table><thead><tr><th>Server</th><th>Community</th><th>Peer communities</th><th>Boundary edges</th><th>Max confidence</th><th>Max impact</th></tr></thead><tbody>{gateway_rows}</tbody></table>
<h3>Observed cross-community precedence edges</h3><table><thead><tr><th>From cluster</th><th>Source</th><th></th><th>Target</th><th>To cluster</th><th>Confidence</th><th>Impact</th></tr></thead><tbody>{edge_rows}</tbody></table>
</main></body></html>"""
