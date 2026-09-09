from __future__ import annotations

from html import escape
from urllib.parse import quote

from nntpintel.propagation_topology_conclusions import topology_conclusions
from nntpintel.propagation_topology_evidence import topology_evidence
from nntpintel.storage import Storage


def _explain_href(evidence_ref: str) -> str:
    return "/web/propagation/topology/explain/" + quote(evidence_ref, safe="")


def evidence_page(storage: Storage) -> str:
    data = topology_evidence(storage)
    conclusions = topology_conclusions(storage)
    conclusion_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["label"]))}</td>'
        f'<td><code>{escape(str(item["conclusion_ref"]))}</code></td>'
        f'<td>{escape(str(item["summary"]))}</td>'
        f'<td><a href="{_explain_href(str(item["conclusion_ref"]))}">Explain</a></td>'
        "</tr>"
        for item in conclusions["conclusions"]
    ) or '<tr><td colspan="5">No explainable conclusions yet.</td></tr>'
    server_rows = "".join(
        "<tr>"
        f'<td><a href="{_explain_href(str(item["evidence_ref"]))}">{escape(str(item["evidence_ref"]))}</a></td>'
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{len(item["campaign_ids"])}</td>'
        f'<td>{len(item["article_ids"])}</td>'
        f'<td>{len(item["visible_article_ids"])}</td>'
        f'<td>{len(item["valid_presence_observation_ids"])}</td>'
        "</tr>"
        for item in data["servers"]
    ) or '<tr><td colspan="6">No server evidence yet.</td></tr>'
    edge_rows = "".join(
        "<tr>"
        f'<td><a href="{_explain_href(str(item["evidence_ref"]))}">{escape(str(item["evidence_ref"]))}</a></td>'
        f'<td>{escape(str(item["source_host"]))}</td>'
        f'<td>→</td>'
        f'<td>{escape(str(item["target_host"]))}</td>'
        f'<td>{item["edge_confidence"]}</td>'
        f'<td>{item["directional_sample_count"]}</td>'
        f'<td>{item["supporting_article_count"]}</td>'
        "</tr>"
        for item in data["edges"]
    ) or '<tr><td colspan="7">No inferred edge evidence yet.</td></tr>'
    article_rows = "".join(
        "<tr>"
        f'<td>{escape(str(edge["evidence_ref"]))}</td>'
        f'<td>{item["article_id"]}</td>'
        f'<td>{escape(str(item["message_id"] or ""))}</td>'
        f'<td>{escape(str(item["source_campaign_ids"]))}</td>'
        f'<td>{escape(str(item["target_campaign_ids"]))}</td>'
        f'<td>{item["source_observation_id"]}</td>'
        f'<td>{item["target_observation_id"]}</td>'
        "</tr>"
        for edge in data["edges"]
        for item in edge["supporting_articles"][:10]
    ) or '<tr><td colspan="7">No supporting articles yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Topology evidence provenance - NNTPIntel</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}
header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1500px;margin:auto}}
a{{color:#9fd3ff}}.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0 2rem}}.card,table{{background:#182028;border:1px solid #2d3944}}.card{{min-width:180px;padding:1rem;border-radius:.6rem}}.metric{{font-size:2rem;font-weight:700}}table{{width:100%;border-collapse:collapse;margin-bottom:2rem}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}
</style></head><body><header><h1>NNTPIntel</h1></header><main>
<p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/conclusions">Search / filter conclusions</a> · <a href="/web/propagation/topology/risk">Risk</a> · <a href="/web/propagation/topology/incidents">Incidents</a></p>
<h2>Topology evidence provenance</h2><p class="warning"><strong>Explainability only.</strong> {escape(data["disclaimer"])}</p>
<div class="cards"><div class="card">Explainable conclusions<div class="metric">{conclusions["conclusion_count"]}</div></div><div class="card">Server evidence refs<div class="metric">{data["server_evidence_count"]}</div></div><div class="card">Edge evidence refs<div class="metric">{data["edge_evidence_count"]}</div></div></div>
<h3 id="conclusions">Explainable conclusion index</h3><p>{escape(conclusions["disclaimer"])}</p><table><thead><tr><th>Kind</th><th>Label</th><th>Conclusion ref</th><th>Summary</th><th></th></tr></thead><tbody>{conclusion_rows}</tbody></table>
<h3>Server evidence</h3><table><thead><tr><th>Evidence ref / explain</th><th>Server</th><th>Campaigns</th><th>Targeted articles</th><th>Visible articles</th><th>Valid observations</th></tr></thead><tbody>{server_rows}</tbody></table>
<h3>Inferred edge evidence</h3><table><thead><tr><th>Evidence ref / explain</th><th>Earlier server</th><th></th><th>Later server</th><th>Confidence</th><th>Directional samples</th><th>Supporting articles</th></tr></thead><tbody>{edge_rows}</tbody></table>
<h3>Supporting Message-IDs and observations</h3><table><thead><tr><th>Edge ref</th><th>Article ID</th><th>Message-ID</th><th>Source campaigns</th><th>Target campaigns</th><th>Source observation</th><th>Target observation</th></tr></thead><tbody>{article_rows}</tbody></table>
</main></body></html>"""
