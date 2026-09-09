from html import escape

from nntpintel.candidate_observability import list_candidate_observability
from nntpintel.storage import Storage


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def candidates_page(storage: Storage) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(item['host']))}</td>"
        f"<td>{escape(str(item['status']))}</td>"
        f"<td>{escape(str(item['latest_classification'] or 'never'))}</td>"
        f"<td>{escape(str(item['latest_age_seconds'] if item['latest_age_seconds'] is not None else ''))}</td>"
        f"<td>{escape(str(item['next_qualification_at']))}</td>"
        f"<td>{_yes_no(bool(item['qualification_due']))}</td>"
        f"<td>{item['recent_reachable_count']}/{item['promotion_required_reachable']}</td>"
        f"<td>{_yes_no(bool(item['promotion_ready']))}</td>"
        f"<td>{escape(', '.join(item['promotion_blockers']))}</td>"
        f"<td>{escape(str(item['note'] or ''))}</td>"
        "</tr>"
        for item in list_candidate_observability(storage)
    ) or '<tr><td colspan="10">No discovery candidates.</td></tr>'
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
th, td {{ text-align: left; padding: .65rem; border-bottom: 1px solid #2d3944; vertical-align: top; }}
th {{ color: #a8b5c2; }}
</style></head>
<body><header><h1>NNTPIntel</h1><nav><a href="/">Dashboard</a> · <a href="/web/servers">Servers</a> · <a href="/web/candidates">Candidates</a></nav></header>
<main><h2>Discovery candidates</h2>
<p>Promotion remains an explicit CLI action. Readiness requires pending status, fresh reachable evidence, and the latest fresh qualification to be reachable.</p>
<table><thead><tr><th>Host</th><th>Status</th><th>Latest</th><th>Age (s)</th><th>Next qualification</th><th>Due</th><th>Recent reachable</th><th>Promotion ready</th><th>Blockers</th><th>Note</th></tr></thead><tbody>{rows}</tbody></table>
</main></body></html>"""
