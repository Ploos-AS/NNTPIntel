# NNTPIntel roadmap

## M0 — Foundation

Scope, principles, architecture, data model direction, deployment targets and project boundaries.

## M1 — Probe engine

Implement a small NNTP client/probe with:

- TCP/119
- TLS/563
- STARTTLS
- greeting parsing
- `CAPABILITIES`
- `MODE READER`
- timeouts
- bounded reads
- structured observation output
- unit/integration tests

Deliverable: probe one configured server and emit normalized JSON.

## M2 — Persistence and scheduler

Add:

- SQLite schema
- server/endpoints
- observation history
- recurring scheduler
- retry/backoff
- per-host rate limits
- deduplication
- migrations

Deliverable: continuously observe a configured set of servers.

## M3 — Group intelligence

Add safe inventory support for:

- `LIST`
- `LIST ACTIVE`
- `LIST NEWSGROUPS`
- `NEWGROUPS`

Track:

- group appearance/disappearance
- high/low article numbers
- posting status
- description changes
- hierarchy statistics

## M4 — API and web UI

Expose:

- server pages
- endpoint health
- capabilities
- TLS state
- groups/hierarchies
- observation history
- incidents/change events
- JSON API

## M5 — Discovery and public deployment

Add controlled discovery sources and operator tooling:

- seed lists
- manually curated endpoints
- DNS/known-provider sources where appropriate
- opt-out/exclusion system
- public service deployment profile
- metrics and health endpoints

Discovery must not become indiscriminate scanning.

## M6 — Propagation intelligence

Measure article presence using Message-ID without requiring article-body retention.

Goals:

- observe selected public articles
- timestamp first visibility per server
- compute propagation delay
- visualize propagation paths/timing
- distinguish measured facts from inferred feed relationships

## M7 — Incident and topology inference

Detect:

- outages
- capability changes
- hierarchy/group anomalies
- propagation degradation
- correlated server events

Build confidence-scored topology/feed hypotheses from repeated observations.

## M8 — Release hardening

- amd64/arm64 OCI publication
- Docker Compose
- Podman/Quadlet example
- backup/restore documentation
- security review
- retention controls
- stable API versioning
- v1.0 release criteria
