from __future__ import annotations

from html import escape

from nntpintel.propagation_topology_quality import topology_data_quality
from nntpintel.storage import Storage


def quality_page(storage: Storage) -> str:
    quality = topology_data_quality(storage)
    server_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["targeted_article_count"]}</td>'
        f'<td>{item["visible_article_count"]}</td>'
        f'<td>{item["valid_presence_coverage"]}</td>'
        f'<td>{escape(str(item["freshness"]))}</td>'
        f'<td>{"—" if item["age_hours"] is None else item["age_hours"]}</td>'
        "</tr>"
        for item in quality["servers"]
    ) or '<tr><td colspan="6" class="muted">No propagation quality data yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Topology data quality - NNTPIntel</title><style>
:root {{ color-scheme:dark;font-family:system-ui,sans-serif; }} body {{ margin:0;background:#101418;color:#e8edf2; }}
header {{ padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944; }} main {{ padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto; }}
a {{ color:#9fd3ff; }} nav a {{ margin-right:1rem; }} .cards {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin:1rem 0 2rem; }}
.card,table {{ background:#182028;border:1px solid #2d3944; }} .card {{ border-radius:.6rem;padding:1rem; }} .metric {{ font-size:2rem;font-weight:700; }}
table {{ width:100%;border-collapse:collapse;margin-bottom:2rem; }} th,td {{ text-align:left;padding:.65rem;border-bottom:1px solid #2d3944; }} th,.muted {{ color:#a8b5c2; }}
.warning {{ padding:1rem;border:1px solid #8a6f2a;background:#2a2416;border-radius:.6rem; }}
</style></head><body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a><a href="/web/servers">Servers</a><a href="/web/groups">Groups</a><a href="/web/events">Events</a><a href="/web/propagation">Propagation</a></nav></header><main>
<p><a href="/web/propagation/topology">← Topology</a> · <a href="/web/propagation/topology/overview">Executive overview</a> · <a href="/web/propagation/topology/risk">Risk synthesis</a></p>
<h2>Topology data quality / confidence</h2><div class="warning"><strong>Evidence quality.</strong> {escape(str(quality["disclaimer"]))}</div>
<div class="cards"><div class="card"><div class="muted">Quality score</div><div class="metric">{quality["quality_score"]}</div><div>{escape(str(quality["quality_level"]))}</div></div>
<div class="card"><div class="muted">Comparable articles</div><div class="metric">{quality["comparable_article_ratio"]}</div></div>
<div class="card"><div class="muted">Strong edges</div><div class="metric">{quality["strong_edge_count"]}</div></div>
<div class="card"><div class="muted">Weak-sample edges</div><div class="metric">{quality["weak_sample_edge_count"]}</div></div>
<div class="card"><div class="muted">Low-coverage servers</div><div class="metric">{quality["low_coverage_server_count"]}</div></div>
<div class="card"><div class="muted">Stale / missing</div><div class="metric">{quality["stale_server_count"]} / {quality["missing_valid_presence_server_count"]}</div></div></div>
<h2>Server evidence coverage</h2><table><thead><tr><th>Server</th><th>Targeted articles</th><th>Valid presence</th><th>Coverage</th><th>Freshness</th><th>Age h</th></tr></thead><tbody>{server_rows}</tbody></table>
<p class="muted">Freshness thresholds: stale after {quality["stale_after_hours"]}h; very stale after {quality["very_stale_after_hours"]}h. Confidence and quality refer only to NNTPIntel observations.</p>
</main></body></html>"""
