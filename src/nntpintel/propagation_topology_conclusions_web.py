from __future__ import annotations

from html import escape
from urllib.parse import quote

from nntpintel.propagation_topology_conclusions import VALID_KINDS, topology_conclusions
from nntpintel.storage import Storage


def conclusions_page(
    storage: Storage,
    *,
    kind: str | None = None,
    query: str | None = None,
    conclusion_ref: str | None = None,
) -> str:
    data = topology_conclusions(
        storage,
        kind=kind,
        query=query,
        conclusion_ref=conclusion_ref,
    )
    rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["kind"]))}</td>'
        f'<td>{escape(str(item["label"]))}</td>'
        f'<td><code>{escape(str(item["conclusion_ref"]))}</code></td>'
        f'<td>{escape(str(item["summary"]))}</td>'
        f'<td><a href="/web/propagation/topology/explain/{quote(str(item["conclusion_ref"]), safe="")}">Explain</a></td>'
        "</tr>"
        for item in data["conclusions"]
    ) or '<tr><td colspan="5">No conclusions match these filters.</td></tr>'
    options = ['<option value="">all kinds</option>'] + [
        f'<option value="{escape(value)}"{(" selected" if kind == value else "")}>{escape(value)}</option>'
        for value in sorted(VALID_KINDS)
    ]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Explainability search - NNTPIntel</title><style>:root{{color-scheme:dark;font-family:system-ui,sans-serif}}body{{margin:0;background:#101418;color:#e8edf2}}header{{padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944}}main{{padding:1.5rem 2rem 3rem;max-width:1500px;margin:auto}}a{{color:#9fd3ff}}table{{width:100%;border-collapse:collapse;background:#182028;border:1px solid #2d3944}}th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #2d3944}}th{{color:#a8b5c2}}form{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.75rem;margin:1rem 0}}input,select,button{{font:inherit;padding:.6rem;background:#182028;color:#e8edf2;border:1px solid #40505e;border-radius:.35rem}}.warning{{border:1px solid #8a6d1d;background:#2a2412;padding:1rem;border-radius:.5rem}}</style></head><body><header><h1>NNTPIntel</h1></header><main><p><a href="/web/propagation/topology/evidence">← Evidence provenance</a> · <a href="/web/propagation/topology">Topology</a></p><h2>Explainability search / filtering</h2><p class="warning"><strong>Navigation only.</strong> {escape(data["disclaimer"])}</p><form method="get"><label>Kind<br><select name="kind">{''.join(options)}</select></label><label>Search label / summary<br><input name="q" value="{escape(query or '')}" placeholder="server, critical, confidence..."></label><label>Conclusion ref<br><input name="ref" value="{escape(conclusion_ref or '')}" placeholder="incident:12"></label><label>Direct explain ref<br><input name="direct" placeholder="risk:server:4"></label><button type="submit">Filter</button></form><p>Showing <strong>{data["conclusion_count"]}</strong> of {data["unfiltered_conclusion_count"]} conclusions.</p><table><thead><tr><th>Kind</th><th>Label</th><th>Conclusion ref</th><th>Summary</th><th></th></tr></thead><tbody>{rows}</tbody></table><script>const f=document.querySelector('form');f.addEventListener('submit',e=>{{const d=f.querySelector('[name=direct]').value.trim();if(d){{e.preventDefault();location.href='/web/propagation/topology/explain/'+encodeURIComponent(d);}}}});</script></main></body></html>"""
