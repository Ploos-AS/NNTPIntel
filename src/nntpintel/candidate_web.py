from html import escape

from nntpintel.candidates import list_candidates
from nntpintel.storage import Storage


def candidates_page(storage: Storage) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item['host']))}</td>"
        f"<td>{escape(str(item['status']))}</td>"
        f"<td>{item['qualification_count']}</td>"
        f"<td>{item['reachable_count']}</td>"
        f"<td>{escape(str(item['latest_classification'] or 'never'))}</td>"
        f"<td>{escape(str(item['latest_qualified_at'] or ''))}</td>"
        f"<td>{escape(str(item['note'] or ''))}</td>"
        "</tr>"
        for item in list_candidates(storage)
    ) or '<tr><td colspan="7">No discovery candidates.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Candidates - NNTPIntel</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #101418; color: #e8edf2; }}
header, main {{ padding: 1.5rem 2rem; }}
a {{ color: #9fd3ff; }}
table {{ width: 100%; border-collapse: collapse; background: #182028; }}
th, td {{ text-align: left; padding: .65rem; border-bottom: 1px solid #2d3944; }}
th {{ color: #a8b5c2; }}
</style></head>
<body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a> · <a href="/web/servers">Servers</a> · <a href="/web/candidates">Candidates</a></nav></header>
<main><h2>Discovery candidates</h2>
<p>Promotion remains an explicit CLI action and requires qualification policy checks.</p>
<table><thead><tr><th>Host</th><th>Status</th><th>Qualifications</th><th>Reachable</th><th>Latest</th><th>Last qualified</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
