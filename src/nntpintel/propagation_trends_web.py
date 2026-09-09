from __future__ import annotations

from html import escape

from nntpintel.propagation_trends import propagation_trends
from nntpintel.storage import Storage


def trends_page(storage: Storage) -> str:
    trends = propagation_trends(storage)
    window_cards = "".join(
        f'<div class="card"><div class="muted">{escape(label)}</div>'
        f'<div class="metric">{window["median_delay_seconds"] if window["median_delay_seconds"] is not None else "—"} s</div>'
        f'<div>p95 {window["p95_delay_seconds"] if window["p95_delay_seconds"] is not None else "—"} s · '
        f'{window["lagging_server_count"]} lagging</div></div>'
        for label, window in trends["windows"].items()
    )
    server_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["sample_count"]}</td>'
        f'<td>{item["coverage_percent"] if item["coverage_percent"] is not None else "—"}</td>'
        f'<td>{item["median_delay_seconds"] if item["median_delay_seconds"] is not None else "—"}</td>'
        f'<td>{item["p95_delay_seconds"] if item["p95_delay_seconds"] is not None else "—"}</td>'
        f'<td>{item["median_delta_seconds"] if item["median_delta_seconds"] is not None else "—"}</td>'
        f'<td class={"bad" if item["lagging"] else "ok"}>{"lagging" if item["lagging"] else "normal"}</td>'
        "</tr>"
        for item in trends["windows"]["7d"]["servers"]
        if item["targeted_article_count"]
    ) or '<tr><td colspan="7" class="muted">No 7-day trend data yet.</td></tr>'
    history_rows = "".join(
        "<tr>"
        f'<td>{item["date"]}</td><td>{item["sample_count"]}</td>'
        f'<td>{item["median_delay_seconds"] if item["median_delay_seconds"] is not None else "—"}</td>'
        f'<td>{item["p95_delay_seconds"] if item["p95_delay_seconds"] is not None else "—"}</td>'
        "</tr>"
        for item in trends["daily"]
    ) or '<tr><td colspan="4" class="muted">No daily history yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Propagation trends - NNTPIntel</title><style>
:root {{ color-scheme:dark;font-family:system-ui,sans-serif }} body {{ margin:0;background:#101418;color:#e8edf2 }}
header {{ padding:1.5rem 2rem;background:#182028;border-bottom:1px solid #2d3944 }} main {{ padding:1.5rem 2rem 3rem;max-width:1400px;margin:auto }}
a {{ color:#9fd3ff }} .cards {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:1rem;margin:1rem 0 2rem }}
.card,table {{ background:#182028;border:1px solid #2d3944 }} .card {{ border-radius:.6rem;padding:1rem }} .metric {{ font-size:1.8rem;font-weight:700 }}
table {{ width:100%;border-collapse:collapse }} th,td {{ text-align:left;padding:.65rem;border-bottom:1px solid #2d3944 }} th,.muted {{ color:#a8b5c2 }}
.ok {{ color:#8fe388 }} .bad {{ color:#ff9b9b }} section {{ margin:2rem 0 }}
</style></head><body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a> · <a href="/web/propagation">Propagation</a></nav></header><main>
<section><h2>Propagation trends</h2><p class="muted">Lagging requires at least {trends["lagging_min_samples"]} samples and a median delay at least {trends["lagging_min_delta_seconds"]} seconds above the network baseline.</p><div class="cards">{window_cards}</div></section>
<section><h2>7-day server trend</h2><table><thead><tr><th>Server</th><th>Samples</th><th>Coverage %</th><th>Median s</th><th>p95 s</th><th>Delta s</th><th>Status</th></tr></thead><tbody>{server_rows}</tbody></table></section>
<section><h2>30-day daily history</h2><table><thead><tr><th>Date</th><th>Samples</th><th>Median s</th><th>p95 s</th></tr></thead><tbody>{history_rows}</tbody></table></section>
</main></body></html>"""
