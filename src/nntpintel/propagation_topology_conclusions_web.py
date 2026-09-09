from __future__ import annotations

from html import escape
from urllib.parse import quote

from nntpintel.propagation_topology_conclusions import topology_conclusions
from nntpintel.storage import Storage


def conclusions_page(storage: Storage) -> str:
    data = topology_conclusions(storage)
    rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["label"]))}</td>'
        f'<td><code>{escape(str(item["conclusion_ref"]))}</code></td>'
        f'<td>{escape(str(item["summary"]))}</td>'
        f'<td><a href="/web/propagation/topology/explain/{quote(str(item["conclusion_ref"]), safe="")}">Explain</a></td>'
        "</tr>"
        for item in data["conclusions"]
    ) or '<tr><td colspan="5">No explainable conclusions yet.</td></tr>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Explainable topology conclusions - NNTPIntel</title><style>:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1500px;margin:auto}}a{{color:#9fd3ff}}table{{width:100%;border-collapse:collapse;background:#182028;border:1px solid #2d3944}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}</style></head><body><header><h1>NNTPIntel</h1></header><main><p><a href="/web/propagation/topology">← Inferred topology</a> · <a href="/web/propagation/topology/evidence">Evidence provenance</a> · <a href="/web/propagation/topology/risk">Risk</a> · <a href="/web/propagation/topology/incidents">Incidents</a></p><h2>Explainable topology conclusions</h2><p class="warning"><strong>Navigation only.</strong> {escape(data["disclaimer"])}</p><p>Total: <strong>{data["conclusion_count"]}</strong></p><table><thead><tr><th>Kind</th><th>Label</th><th>Conclusion ref</th><th>Summary</th><th></th></tr></thead><tbody>{rows}</tbody></table></main></body></html>"""
