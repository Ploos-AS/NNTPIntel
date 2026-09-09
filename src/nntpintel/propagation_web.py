from __future__ import annotations

from html import escape

from nntpintel.propagation_analytics import propagation_analytics
from nntpintel.propagation_view import (
    get_propagation_article,
    list_propagation_articles,
    list_propagation_campaigns,
)
from nntpintel.storage import Storage


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} - NNTPIntel</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #101418; color: #e8edf2; }}
header {{ padding: 1.5rem 2rem; background: #182028; border-bottom: 1px solid #2d3944; }}
main {{ padding: 1.5rem 2rem 3rem; max-width: 1400px; margin: auto; }}
nav a, a {{ color: #9fd3ff; }} nav a {{ margin-right: 1rem; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:1rem; margin:1rem 0 2rem; }}
.card, table {{ background:#182028; border:1px solid #2d3944; }}
.card {{ border-radius:.6rem; padding:1rem; }} .metric {{ font-size:2rem; font-weight:700; }}
table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; padding:.65rem; border-bottom:1px solid #2d3944; vertical-align:top; }}
th,.muted {{ color:#a8b5c2; }} .ok {{ color:#8fe388; }} .bad {{ color:#ff9b9b; }}
code {{ color:#c9e5ff; overflow-wrap:anywhere; }} section {{ margin:2rem 0; }}
</style>
</head><body><header><h1>NNTPIntel</h1><nav>
<a href="/">Dashboard</a><a href="/web/servers">Servers</a><a href="/web/groups">Groups</a>
<a href="/web/events">Events</a><a href="/web/propagation">Propagation</a>
</nav></header><main>{body}</main></body></html>"""


def propagation_page(storage: Storage) -> str:
    articles = list_propagation_articles(storage)
    campaigns = list_propagation_campaigns(storage)
    analytics = propagation_analytics(storage)
    article_rows = "".join(
        "<tr>"
        f'<td><a href="/web/propagation/{item["id"]}"><code>{escape(str(item["message_id"]))}</code></a></td>'
        f'<td>{escape(str(item["newsgroup"] or ""))}</td>'
        f'<td>{item["observation_count"]}</td><td>{item["visible_endpoint_count"]}</td>'
        f'<td>{escape(str(item["first_visibility_at"] or "not seen"))}</td>'
        "</tr>"
        for item in articles
    ) or '<tr><td colspan="5" class="muted">No propagation articles registered.</td></tr>'
    campaign_rows = "".join(
        "<tr>"
        f'<td>{item["id"]}</td><td><code>{escape(str(item["message_id"]))}</code></td>'
        f'<td>{escape(str(item["status"]))}</td><td>{len(item["endpoint_ids"])}</td>'
        f'<td>{item["stop_after_visible"]}</td><td>{escape(str(item["expires_at"]))}</td>'
        "</tr>"
        for item in campaigns
    ) or '<tr><td colspan="6" class="muted">No propagation campaigns.</td></tr>'
    analytics_cards = "".join(
        f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(value))}</div></div>'
        for label, value in [
            ("Delay samples", analytics["sample_count"]),
            ("Median delay s", analytics["median_delay_seconds"] if analytics["median_delay_seconds"] is not None else "—"),
            ("p95 delay s", analytics["p95_delay_seconds"] if analytics["p95_delay_seconds"] is not None else "—"),
            ("Target coverage %", analytics["target_coverage_percent"] if analytics["target_coverage_percent"] is not None else "—"),
        ]
    )
    endpoint_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}:{item["port"]}</td>'
        f'<td>{item["targeted_article_count"]}</td>'
        f'<td>{item["visible_article_count"]}</td>'
        f'<td>{item["coverage_percent"] if item["coverage_percent"] is not None else "—"}</td>'
        f'<td>{item["median_delay_seconds"] if item["median_delay_seconds"] is not None else "—"}</td>'
        f'<td>{item["p95_delay_seconds"] if item["p95_delay_seconds"] is not None else "—"}</td>'
        "</tr>"
        for item in analytics["endpoints"]
    ) or '<tr><td colspan="6" class="muted">No propagation analytics yet.</td></tr>'
    server_rows = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}</td>'
        f'<td>{item["targeted_article_count"]}</td>'
        f'<td>{item["visible_article_count"]}</td>'
        f'<td>{item["coverage_percent"] if item["coverage_percent"] is not None else "—"}</td>'
        f'<td>{item["median_delay_seconds"] if item["median_delay_seconds"] is not None else "—"}</td>'
        f'<td>{item["p95_delay_seconds"] if item["p95_delay_seconds"] is not None else "—"}</td>'
        "</tr>"
        for item in analytics["servers"]
    ) or '<tr><td colspan="6" class="muted">No server analytics yet.</td></tr>'
    return _page(
        "Propagation",
        f"""
<section><p><a href="/web/propagation/trends">Trends</a> · <a href="/web/propagation/incidents">Incidents</a> · <a href="/web/propagation/topology">Inferred topology</a></p><h2>Propagation analytics</h2><div class="cards">{analytics_cards}</div></section>
<section><h2>Endpoint comparison</h2><table><thead><tr><th>Endpoint</th><th>Targeted articles</th><th>Visible articles</th><th>Coverage %</th><th>Median delay s</th><th>p95 delay s</th></tr></thead><tbody>{endpoint_rows}</tbody></table></section>
<section><h2>Server comparison</h2><table><thead><tr><th>Server</th><th>Targeted articles</th><th>Visible articles</th><th>Coverage %</th><th>Median delay s</th><th>p95 delay s</th></tr></thead><tbody>{server_rows}</tbody></table></section>
<section><h2>Propagation articles</h2><table><thead><tr><th>Message-ID</th><th>Newsgroup</th><th>Samples</th><th>Visible endpoints</th><th>First visibility</th></tr></thead><tbody>{article_rows}</tbody></table></section>
<section><h2>Campaigns</h2><table><thead><tr><th>ID</th><th>Message-ID</th><th>Status</th><th>Targets</th><th>Stop after visible</th><th>Expires</th></tr></thead><tbody>{campaign_rows}</tbody></table></section>
""",
    )


def propagation_detail_page(storage: Storage, article_id: int) -> str | None:
    article = get_propagation_article(storage, article_id)
    if article is None:
        return None
    endpoints = "".join(
        "<tr>"
        f'<td>{escape(str(item["host"]))}:{item["port"]}</td>'
        f'<td>{escape(str(item["transport"]))}</td>'
        f'<td>{escape(str(item["first_seen_at"]))}</td>'
        f'<td>{item["delay_seconds"]}</td>'
        "</tr>"
        for item in article["endpoints"]
    ) or '<tr><td colspan="4" class="muted">Not observed on any endpoint yet.</td></tr>'
    observations = "".join(
        "<tr>"
        f'<td>{escape(str(item["observed_at"]))}</td>'
        f'<td>{escape(str(item["host"]))}:{item["port"]}</td>'
        f'<td class={"ok" if item["state"] == "present" else "bad"}>{escape(str(item["state"]))}</td>'
        f'<td>{escape(str(item["method"]))}</td><td>{item["response_code"] or ""}</td>'
        f'<td>{escape(str(item["error"] or ""))}</td>'
        "</tr>"
        for item in article["observations"]
    ) or '<tr><td colspan="6" class="muted">No observations yet.</td></tr>'
    cards = "".join(
        f'<div class="card"><div class="muted">{escape(label)}</div><div class="metric">{escape(str(value))}</div></div>'
        for label, value in [
            ("Samples", article["observation_count"]),
            ("Visible endpoints", article["visible_endpoint_count"]),
            ("First visibility", article["first_visibility_at"] or "not seen"),
            ("Campaigns", len(article["campaigns"])),
        ]
    )
    return _page(
        "Propagation detail",
        f"""
<section><p><a href="/web/propagation">← Propagation</a></p><h2><code>{escape(str(article["message_id"]))}</code></h2><p>{escape(str(article["newsgroup"] or ""))}</p><div class="cards">{cards}</div></section>
<section><h2>Measured propagation delay</h2><table><thead><tr><th>Endpoint</th><th>Transport</th><th>First seen</th><th>Delay seconds</th></tr></thead><tbody>{endpoints}</tbody></table></section>
<section><h2>Presence timeline</h2><table><thead><tr><th>Observed</th><th>Endpoint</th><th>Presence</th><th>Method</th><th>Code</th><th>Error</th></tr></thead><tbody>{observations}</tbody></table></section>
""",
    )
