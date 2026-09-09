from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_resilience import topology_resilience
from nntpintel.storage import Storage


def resilience_page(storage: Storage) -> str:
    data = topology_resilience(storage)
    node_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["community_id"]}</td>'
        f'<td>{item["resilience_score"]}</td>'
        f'<td>{item["fragmentation_delta"]}</td>'
        f'<td>{item["lost_cross_community_edges"]}</td>'
        f'<td>{item["cross_community_edge_loss_ratio"]}</td>'
        f'<td>{item["impact_score"]}</td>'
        "</tr>"
        for item in data["nodes"]
    ) or '<tr><td colspan="7">No inferred topology nodes yet.</td></tr>'
    edge_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["source_host"]))}</td><td>→</td>'
        f'<td>{escape(str(item["target_host"]))}</td>'
        f'<td>{item["resilience_score"]}</td>'
        f'<td>{"yes" if item["cross_community"] else "no"}</td>'
        f'<td>{item["fragmentation_delta"]}</td>'
        f'<td>{item["confidence"]}</td>'
        "</tr>"
        for item in data["edges"]
    ) or '<tr><td colspan="7">No inferred topology edges yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology resilience - NNTPIntel</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0 2rem}}.card,table{{background:#182028;border:1px solid #2d3944}}.card{{min-width:180px;padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}table{{width:100%;border-collapse:collapse;margin-bottom:2rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/cross-cluster">Cross-cluster</a></p>
<h2>Topology resilience / critical paths</h2>
<p class="warning"><strong>Inference only.</strong> {escape(data["disclaimer"])}</p>
<div class="cards"><div class="card">Critical nodes<div class="metric">{data["critical_node_count"]}</div></div><div class="card">Critical edges<div class="metric">{data["critical_edge_count"]}</div></div><div class="card">Cross-cluster edges<div class="metric">{data["cross_community_edge_count"]}</div></div></div>
<h3>Node removal simulation</h3><table><thead><tr><th>Server</th><th>Cluster</th><th>Resilience score</th><th>Fragmentation +</th><th>Lost cross edges</th><th>Cross loss ratio</th><th>Impact</th></tr></thead><tbody>{node_rows}</tbody></table>
<h3>Edge removal simulation</h3><table><thead><tr><th>Source</th><th></th><th>Target</th><th>Resilience score</th><th>Cross-cluster</th><th>Fragmentation +</th><th>Confidence</th></tr></thead><tbody>{edge_rows}</tbody></table>
</main></body></html>"""
