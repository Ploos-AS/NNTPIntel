import json
from html import escape

from nntpintel.cycle import list_cycle_runs
from nntpintel.storage import Storage


def cycle_runs_page(storage: Storage) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{item['id']}</td>"
        f"<td>{escape(str(item['source']))}</td>"
        f"<td>{escape(str(item['started_at']))}</td>"
        f"<td>{escape(str(item['finished_at'] or ''))}</td>"
        f"<td>{escape(str(item['status']))}</td>"
        f"<td>{item['added']}</td>"
        f"<td>{item['still_present']}</td>"
        f"<td>{item['missing']}</td>"
        f"<td>{item['qualification_count']}</td>"
        f"<td><code>{escape(json.dumps(item['classifications'], sort_keys=True))}</code></td>"
        f"<td>{escape(str(item['error'] or ''))}</td>"
        "</tr>"
        for item in list_cycle_runs(storage, limit=200)
    ) or '<tr><td colspan="11">No candidate cycles recorded yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Candidate cycles - NNTPIntel</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #101418; color: #e8edf2; }}
header, main {{ padding: 1.5rem 2rem; }}
a {{ color: #9fd3ff; }}
table {{ width: 100%; border-collapse: collapse; background: #182028; }}
th, td {{ text-align: left; padding: .65rem; border-bottom: 1px solid #2d3944; vertical-align: top; }}
th {{ color: #a8b5c2; }}
code {{ white-space: pre-wrap; }}
</style></head>
<body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a> · <a href="/web/candidates">Candidates</a> · <a href="/web/cycles">Cycles</a></nav></header>
<main><h2>Candidate cycle history</h2>
<p>Cycles refresh discovery sources and qualify small batches only; promotion remains explicit.</p>
<table><thead><tr><th>ID</th><th>Source</th><th>Started</th><th>Finished</th><th>Status</th><th>Added</th><th>Still present</th><th>Missing</th><th>Qualified</th><th>Classifications</th><th>Error</th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
