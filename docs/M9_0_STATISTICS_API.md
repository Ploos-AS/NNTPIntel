# M9.0 — Statistics query API

Status: **PASS / complete**

M9.0 establishes the production query contract for NNTPIntel's public multi-year statistics service.

## Production backend

The public statistics service is PostgreSQL-only. SQLite remains supported for development, tests and small/legacy installs, but it is not accepted by the production statistics HTTP entrypoint.

Production entrypoint:

```text
nntpintel-statistics-api
```

Database configuration is supplied with `--database-url` or `NNTPINTEL_DATABASE_URL`.

The statistics service intentionally has a narrow HTTP surface independent of the legacy SQLite-oriented API. This avoids claiming PostgreSQL compatibility for legacy endpoints that have not yet been migrated.

## HTTP endpoints

All statistics endpoints are versioned under `/api/v1/statistics`:

- `/api/v1/statistics/servers`
- `/api/v1/statistics/groups`
- `/api/v1/statistics/protocol`
- `/api/v1/statistics/propagation`
- `/api/v1/statistics/topology`

Operational endpoint:

- `/healthz`

Unknown routes return `404` JSON.

## Query contract

`resolution` is required and must be one of:

- `hour`
- `day`
- `month`

`start` and `end` are optional, but must be supplied together. They are ISO-8601 timestamps with an explicit timezone and define a half-open interval `[start, end)`.

If no range is supplied, the query is an all-time rollup query.

`server_id` is optional for server-scoped metric families and must be a positive integer. Topology statistics are global and reject `server_id` rather than silently ignoring it.

Malformed or ambiguous query parameters return `400`. Backend/service failures return `503`.

## Rollup-only invariant

Public multi-year queries read derived rollup tables rather than raw observation/history tables. This is a production invariant for bounded cost and long-term retention.

Metric families and sources:

- server availability/latency: `server_observation_rollups`
- group/hierarchy inventory/change history: `server_group_rollups`, `server_group_value_rollups`
- TLS/protocol/capabilities: `server_protocol_rollups`, `server_protocol_value_rollups`
- propagation/incidents/campaigns: `server_propagation_rollups`, `server_propagation_value_rollups`, `propagation_campaign_rollups`
- inferred-topology evidence/incidents: `topology_rollups`, `topology_value_rollups`

Timestamps and numeric PostgreSQL values are normalized to JSON-native values before serialization.

## Production qualification

GitHub Actions runs a live PostgreSQL 17 qualification for the statistics HTTP service. The qualification:

1. starts from the PostgreSQL production schema/migrations,
2. starts the real statistics HTTP server against PostgreSQL,
3. calls all five public statistics endpoints over HTTP,
4. requires successful JSON responses,
5. runs alongside the existing migration, partition, retention, backup/restore and rollup qualifications.

The M9.0 production HTTP gate passed in CI run #448 on commit `e54171bfcd500533d6ba8c61f7319c78eadddc12`.

## Completion criteria

M9.0 is complete when:

- the five public metric families are exposed by a versioned HTTP API,
- range/resolution/server filters are validated,
- topology's global scope is explicit,
- queries use rollups only,
- payloads are JSON-native,
- PostgreSQL is enforced for the production statistics service,
- the real HTTP success path is qualified against PostgreSQL 17,
- Python 3.11, 3.12 and 3.13 tests plus Ruff are green.

All criteria are satisfied.

Next milestone: **M9.1 — Historical web statistics**.
