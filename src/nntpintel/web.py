from __future__ import annotations

import json
from html import escape

from nntpintel.api import (
    get_server,
    list_endpoints,
    list_events,
    list_groups,
    list_hierarchies,
    list_servers,
)
from nntpintel.storage import Storage

_STYLE = """
:root { color-scheme: dark; font-family: system-ui, sans-serif; }
body { margin: 0; background: #101418; color: #e8edf2; }
header { padding: 1.5rem 2rem; background: #182028; border-bottom: 1px solid #2d3944; }
main { padding: 1.5rem 2rem 3rem; max-width: 1400px; margin: auto; }
h1, h2 { margin-top: 0; }
nav a, a { color: #9fd3ff; }
nav a { margin-right: 1rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin: 1rem 0 2rem; }
.card { background: #182028; border: 1px solid #2d3944; border-radius: .6rem; padding: 1rem; }
.metric { font-size: 2rem; font-weight: 700; }
section { margin: 2rem 0; }
table { width: 100%; border-collapse: collapse; background: #182028; }
th, td { text-align: left; padding: .65rem; border-bottom: 1px solid #2d3944; vertical-align: top; }
th { color: #a8b5c2; }
.status-ok { color: #8fe388; }
.status-bad { color: #ff9b9b; }
.muted { color: #8f9ba6; }
code { color: #c9e5ff; white-space: pre-wrap; overflow-wrap: anywhere; }
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} - NNTPIntel</title>
<style>{_STYLE}</style>
</head>
<body>
<header>
  <h1>NNTPIntel</h1>
  <nav>
    <a href="/">Dashboard</a>
    <a href="/web/servers">Servers</a>
    <a href="/web/groups">Groups</a>
    <a href="/web/events">Events</a>
    <a href="/healthz">API health</a>
  </nav>
</header>
<main>{body}</main>
</body>
</html>"""


def dashboard(storage: Storage) -> str:
    servers = list_servers(storage)
    endpoints = list_endpoints(storage)
    groups = list_groups(storage)
    hierarchies = list_hierarchies(storage)
    events = list_events(storage, limit=10)
    failing = sum(1 for endpoint in endpoints if int(endpoint["consecutive_failures"]) > 0)

    cards = "".join(
        f'<div class="card"><div class="muted">{label}</div><div class="metric">{value}</div></div>'
        for label, value in [
            ("Servers", len(servers)),
            ("Endpoints", len(endpoints)),
            ("Failing endpoints", failing),
            ("Hierarchies", len(hierarchies)),
            ("Newsgroups", len(groups)),
        ]
    )
    event_rows = "".join(
        "<tr>"
        f"<td>{escape(str(event['observed_at']))}</td>"
        f"<td>{escape(str(event['host']))}:{event['port']}</td>"
        f"<td>{escape(str(event['newsgroup']))}</td>"
        f"<td>{escape(str(event['event_type']))}</td>"
        "</tr>"
        for event in events
    ) or '<tr><td colspan="4" class="muted">No events recorded yet.</td></tr>'

    body = f"""
<section>
  <h2>Overview</h2>
  <div class="cards">{cards}</div>
</section>
<section>
  <h2>Recent group events</h2>
  <table><thead><tr><th>Observed</th><th>Endpoint</th><th>Newsgroup</th><th>Event</th></tr></thead>
  <tbody>{event_rows}</tbody></table>
</section>
"""
    return _page("Dashboard", body)


def servers_page(storage: Storage) -> str:
    servers = {server["host"]: server for server in list_servers(storage)}
    endpoints = list_endpoints(storage)
    rows = "".join(
        "<tr>"
        f"<td><a href=\"/web/servers/{servers[endpoint['host']]['id']}\">{escape(str(endpoint['host']))}</a></td>"
        f"<td>{endpoint['port']}</td>"
        f"<td>{escape(str(endpoint['transport']))}</td>"
        f"<td>{'yes' if endpoint['starttls'] else 'no'}</td>"
        f"<td class={'status-bad' if endpoint['consecutive_failures'] else 'status-ok'}>"
        f"{endpoint['consecutive_failures']}</td>"
        f"<td>{escape(str(endpoint['last_probe_at'] or 'never'))}</td>"
        "</tr>"
        for endpoint in endpoints
    ) or '<tr><td colspan="6" class="muted">No endpoints configured.</td></tr>'
    body = f"""
<section><h2>Servers and endpoints</h2>
<table><thead><tr><th>Host</th><th>Port</th><th>Transport</th><th>STARTTLS</th><th>Failures</th><th>Last probe</th></tr></thead>
<tbody>{rows}</tbody></table></section>
"""
    return _page("Servers", body)


def server_detail_page(storage: Storage, server_id: int) -> str | None:
    server = get_server(storage, server_id)
    if server is None:
        return None

    endpoint_rows = "".join(
        "<tr>"
        f"<td>{endpoint['port']}</td>"
        f"<td>{escape(str(endpoint['transport']))}</td>"
        f"<td>{'yes' if endpoint['starttls'] else 'no'}</td>"
        f"<td>{endpoint['consecutive_failures']}</td>"
        f"<td>{escape(str(endpoint['last_probe_at'] or 'never'))}</td>"
        f"<td>{escape(str(endpoint['next_probe_at'] or ''))}</td>"
        "</tr>"
        for endpoint in server["endpoints"]
    ) or '<tr><td colspan="6" class="muted">No endpoints configured.</td></tr>'

    observation_rows = "".join(
        "<tr>"
        f"<td>{escape(str(obs['observed_at']))}</td>"
        f"<td>{obs['port']}</td>"
        f"<td class={'status-ok' if obs['success'] else 'status-bad'}>{'ok' if obs['success'] else 'fail'}</td>"
        f"<td>{'' if obs['connect_ms'] is None else obs['connect_ms']}</td>"
        f"<td>{escape(str(obs['greeting_code'] or ''))}</td>"
        f"<td><code>{escape(', '.join(obs['capabilities']))}</code></td>"
        f"<td><code>{escape(json.dumps(obs['tls'], sort_keys=True))}</code></td>"
        f"<td>{escape(str(obs['error'] or ''))}</td>"
        "</tr>"
        for obs in server["observations"]
    ) or '<tr><td colspan="8" class="muted">No probe observations recorded yet.</td></tr>'

    event_rows = "".join(
        "<tr>"
        f"<td>{escape(str(event['observed_at']))}</td>"
        f"<td>{event['port']}</td>"
        f"<td>{escape(str(event['newsgroup']))}</td>"
        f"<td>{escape(str(event['event_type']))}</td>"
        f"<td><code>{escape(str(event['detail_json']))}</code></td>"
        "</tr>"
        for event in server["events"]
    ) or '<tr><td colspan="5" class="muted">No group events recorded yet.</td></tr>'

    latest = server["observations"][0] if server["observations"] else None
    cards = [
        ("Endpoints", len(server["endpoints"])),
        ("Observations", len(server["observations"])),
        ("Latest status", "ok" if latest and latest["success"] else "unknown" if latest is None else "fail"),
        ("Latest latency ms", "" if latest is None or latest["connect_ms"] is None else latest["connect_ms"]),
    ]
    card_html = "".join(
        f'<div class="card"><div class="muted">{escape(str(label))}</div><div class="metric">{escape(str(value))}</div></div>'
        for label, value in cards
    )

    body = f"""
<section>
  <p><a href="/web/servers">← All servers</a></p>
  <h2>{escape(str(server['host']))}</h2>
  <div class="cards">{card_html}</div>
</section>
<section><h2>Endpoints</h2>
<table><thead><tr><th>Port</th><th>Transport</th><th>STARTTLS</th><th>Failures</th><th>Last probe</th><th>Next probe</th></tr></thead>
<tbody>{endpoint_rows}</tbody></table></section>
<section><h2>Observation history</h2>
<table><thead><tr><th>Observed</th><th>Port</th><th>Status</th><th>Latency ms</th><th>Greeting</th><th>Capabilities</th><th>TLS</th><th>Error</th></tr></thead>
<tbody>{observation_rows}</tbody></table></section>
<section><h2>Group changes</h2>
<table><thead><tr><th>Observed</th><th>Port</th><th>Newsgroup</th><th>Event</th><th>Detail</th></tr></thead>
<tbody>{event_rows}</tbody></table></section>
"""
    return _page(str(server["host"]), body)


def groups_page(storage: Storage) -> str:
    groups = list_groups(storage)
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(group['name']))}</td>"
        f"<td>{escape(str(group['hierarchy']))}</td>"
        f"<td>{group['low_water'] if group['low_water'] is not None else ''}</td>"
        f"<td>{group['high_water'] if group['high_water'] is not None else ''}</td>"
        f"<td>{escape(str(group['posting_status'] or ''))}</td>"
        f"<td>{escape(str(group['description'] or ''))}</td>"
        "</tr>"
        for group in groups
    ) or '<tr><td colspan="6" class="muted">No groups observed yet.</td></tr>'
    body = f"""
<section><h2>Newsgroups</h2>
<table><thead><tr><th>Name</th><th>Hierarchy</th><th>Low</th><th>High</th><th>Posting</th><th>Description</th></tr></thead>
<tbody>{rows}</tbody></table></section>
"""
    return _page("Groups", body)


def events_page(storage: Storage) -> str:
    events = list_events(storage, limit=200)
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(event['observed_at']))}</td>"
        f"<td>{escape(str(event['host']))}:{event['port']}</td>"
        f"<td>{escape(str(event['newsgroup']))}</td>"
        f"<td>{escape(str(event['event_type']))}</td>"
        f"<td><code>{escape(str(event['detail_json']))}</code></td>"
        "</tr>"
        for event in events
    ) or '<tr><td colspan="5" class="muted">No events recorded yet.</td></tr>'
    body = f"""
<section><h2>Group events</h2>
<table><thead><tr><th>Observed</th><th>Endpoint</th><th>Newsgroup</th><th>Event</th><th>Detail</th></tr></thead>
<tbody>{rows}</tbody></table></section>
"""
    return _page("Events", body)
