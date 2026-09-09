from html import escape

from nntpintel.source_management import list_source_management
from nntpintel.storage import Storage


def _value(value: object) -> str:
    return escape("" if value is None else str(value))


def sources_page(storage: Storage) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_value(item['name'])}</td>"
        f"<td>{_value(item['enabled'])}</td>"
        f"<td>{_value(item['active_server_count'])}/{_value(item['server_count'])}</td>"
        f"<td>{_value(item['schedule_enabled'])}</td>"
        f"<td>{_value(item['interval_seconds'])}</td>"
        f"<td>{_value(item['candidate_limit'])}</td>"
        f"<td>{_value(item['timeout_seconds'])}</td>"
        f"<td>{_value(item['last_cycle_at'])}</td>"
        f"<td>{_value(item['next_cycle_at'])}</td>"
        f"<td>{_value(item['consecutive_failures'])}</td>"
        "</tr>"
        for item in list_source_management(storage)
    ) or '<tr><td colspan="10">No discovery sources.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sources - NNTPIntel</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #101418; color: #e8edf2; }}
header, main {{ padding: 1.5rem 2rem; }}
a {{ color: #9fd3ff; }}
table {{ width: 100%; border-collapse: collapse; background: #182028; }}
th, td {{ text-align: left; padding: .65rem; border-bottom: 1px solid #2d3944; vertical-align: top; }}
th {{ color: #a8b5c2; }}
</style></head>
<body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a> · <a href="/web/sources">Sources</a> · <a href="/web/candidates">Candidates</a> · <a href="/web/cycles">Cycles</a></nav></header>
<main><h2>Discovery source management</h2>
<p>This is read-only. Source and schedule state changes remain explicit CLI actions.</p>
<table><thead><tr><th>Source</th><th>Source enabled</th><th>Active/known</th><th>Schedule enabled</th><th>Cadence (s)</th><th>Batch</th><th>Timeout</th><th>Last cycle</th><th>Next cycle</th><th>Failures</th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
