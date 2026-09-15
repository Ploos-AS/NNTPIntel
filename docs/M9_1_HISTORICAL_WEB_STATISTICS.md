# M9.1 — Historical web statistics

Status: **COMPLETE / CI-qualified**

M9.1 provides public, server-rendered historical statistics pages on the dedicated PostgreSQL statistics service. Historical views query statistical rollups by default; raw observations are not used to build normal historical pages or graphs.

## Public historical views

- `/web/statistics` — global historical overview and server discovery
- `/web/statistics/server/<id>` — server availability and connection-latency history
- `/web/statistics/server/<id>/groups` — hierarchy/newsgroup inventory and change history
- `/web/statistics/server/<id>/protocol` — TLS, protocol and capability history
- `/web/statistics/server/<id>/propagation` — propagation, incidents and global campaign history
- `/web/statistics/topology` — global inferred-topology history

The overview links directly to servers represented in the selected rollup range. Server pages provide navigation to the server-specific group, protocol/TLS and propagation views.

## Time ranges

Historical pages support the required presets:

- 24 hours
- 7 days
- 30 days
- 1 year
- all time

They also support validated bounded custom ranges with explicit ISO-8601 start/end timestamps and hour/day/month resolution. Range validation reuses the public statistics query contract.

## Presentation

The web UI is dependency-free, server-rendered HTML with inline SVG graphs generated from already queried rollup rows. It does not require JavaScript or a chart framework.

Implemented trend views include server availability/latency plus global TLS, propagation and topology trends. Detailed history remains available in tabular form for evidence-friendly inspection.

Group/hierarchy history explicitly distinguishes rollup time semantics:

- **First seen in selected rollups** is the first returned bucket in the selected range.
- **Last seen in selected rollups** is the last returned bucket in the selected range.
- **Last changed bucket** is the latest returned bucket containing one or more recorded group/hierarchy events.

These labels do not claim lifetime first/last observation and do not turn rollup buckets into exact raw-event timestamps.

## Bounded raw drill-down

Normal public history stays rollup-backed. A separate diagnostic endpoint exists for explicit short-window evidence inspection:

`GET /api/v1/statistics/server/<id>/observations?start=<timestamp>&end=<timestamp>&limit=<n>`

The endpoint:

- requires PostgreSQL;
- requires explicit start and end timestamps;
- limits the raw window to 24 hours;
- limits results to at most 500 rows;
- scopes observations to one server;
- returns a deliberately bounded observation subset rather than large raw JSON/TLS/capability payloads.

This is an evidence/drill-down escape hatch, not the data source for historical statistics.

## Qualification summary

M9.1 development was continuously qualified by the repository CI matrix. Coverage includes:

- historical landing-page rendering;
- required range presets and bounded custom ranges;
- server history;
- hierarchy/newsgroup history and time semantics;
- protocol/TLS history;
- propagation and campaign history;
- inferred-topology history;
- rollup-backed SVG graph rendering;
- server discovery/navigation;
- dedicated HTTP routes;
- bounded raw-observation drill-down validation and HTTP behavior.

The final M9.1 navigation test commit was qualified successfully by CI run #492 on `main` before this completion document was added.

## Architectural invariants

1. PostgreSQL is the production statistics backend.
2. Normal multi-year historical queries use rollups, not raw observations.
3. Arbitrary ranges pass the same bounded validation contract as the statistics API.
4. Global topology and propagation-campaign statistics are not misrepresented as server-scoped data.
5. Raw observation access is explicit, server-scoped, short-window and row-bounded.
6. M9.2 owns caching, freshness coupling, query-cost protection and pagination hardening.

With these invariants and public historical views in place, M9.1 is complete. The next milestone is M9.2 — caching and query protection.
