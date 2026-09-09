# NNTPIntel roadmap

NNTPIntel will not make a preview release. The first public release, v0.1.0, is a production release and must be qualified for continuous public operation and multi-year historical statistics.

## M0 — Foundation

Scope, principles, architecture, data model direction, deployment targets and project boundaries.

## M1 — Probe engine

Implement a small NNTP client/probe with TCP/119, TLS/563, STARTTLS, greeting parsing, `CAPABILITIES`, `MODE READER`, timeouts, bounded reads, structured observation output and tests.

## M2 — Persistence and scheduler

SQLite persistence, server/endpoints, observation history, recurring scheduler, retry/backoff, per-host rate limits, deduplication and migrations.

## M3 — Group intelligence

Safe `LIST`, `LIST ACTIVE`, `LIST NEWSGROUPS` and `NEWGROUPS` inventory with hierarchy/group history and change events.

## M4 — API and web UI

Server pages, endpoint health, capabilities, TLS state, groups/hierarchies, observation history, incidents/change events and JSON API.

## M5 — Discovery and public deployment foundations

Controlled NNTP-specific discovery sources, operator tooling, candidate qualification, opt-out/exclusion principles and safe bounded discovery. Discovery must not become indiscriminate scanning.

## M6 — Propagation intelligence

Message-ID presence measurements without article-body retention; propagation campaigns, timing/coverage analytics, incidents and historical trends. Measured facts remain distinct from inferred feed relationships.

## M7 — Incident, topology and explainability intelligence

Confidence-scored inferred topology, history, anomalies, incidents, impact, communities, cross-cluster intelligence, resilience, risk synthesis, data-quality overlays, evidence provenance, explainability, deterministic evidence bundles/fingerprints, persisted evidence snapshots, timelines, semantic change summaries and change-significance classification.

M7 is feature-complete enough to move the project focus from intelligence expansion to production architecture. Further M7 features are deferred unless they become production blockers.

## M8 — Production data platform

### M8.0 — Production Data Architecture

Freeze the production-first data architecture before implementation:

- PostgreSQL as production storage; SQLite retained for dev/tests/small installs
- explicit storage/backend boundary
- time partitioning strategy
- raw evidence vs derived state vs statistical rollups
- hourly/daily/monthly/yearly aggregation model
- multi-year public query contract
- retention invariants
- collector/worker/web process separation
- distributed-collector readiness
- Prometheus observability requirements
- multi-year qualification dataset and production gate

See `docs/M8_0_PRODUCTION_DATA_ARCHITECTURE.md`.

### M8.1 — Storage backend foundation

Introduce the storage interface, SQLite backend compatibility path, PostgreSQL backend, explicit migrations and configuration/database URL handling. Remove production-critical direct `sqlite3` assumptions from domain/service code.

### M8.2 — Production schema and partitioning

Implement PostgreSQL-native production schema, appropriate `TIMESTAMPTZ` semantics, indexes and time-based partitioning for high-volume observation tables. Add collector/vantage-ready observation boundaries without prematurely implementing distributed ingestion.

### M8.3 — Rollup engine

Implement idempotent hourly/daily/monthly rollups for server availability/latency, TLS/capabilities, groups/hierarchies, propagation and incident/topology statistics. Make rollups rebuildable for bounded windows and observable through metrics/status.

### M8.4 — Retention and maintenance

Configurable raw-data retention, partition/batch pruning, rollup-coverage safety checks, maintenance scheduling and integrity reporting. Long-term aggregate statistics and retained provenance must survive raw-data pruning.

## M9 — Public multi-year statistics service

### M9.0 — Statistics query API

Versioned public statistics API with explicit range/resolution, bounded arbitrary date ranges and efficient all-time queries against rollups rather than raw observations.

### M9.1 — Historical web statistics

Public pages for global statistics, server history, hierarchy/newsgroup history, propagation history, incidents, inferred topology and data-quality/evidence history. Minimum ranges: 24h, 7d, 30d, 1y, bounded custom range and all-time.

### M9.2 — Caching and query protection

Deterministic server-side caching, freshness tied to rollup completion, bounded query costs, pagination where needed and protection against expensive public queries.

## M10 — Distributed collection

Collector identity/vantage model, authenticated central ingestion, multiple geographic vantage points, retry/backpressure, clock/observation semantics and collector fault isolation.

## M11 — Production operations

- amd64/arm64 OCI publication
- Docker Compose production profile
- Podman/Quadlet example
- separate collector/worker/web roles from the same image where practical
- Caddy reverse-proxy/HTTPS profile
- backup/restore procedures and automated qualification
- Prometheus metrics and health/readiness endpoints
- resource limits and graceful shutdown
- security review and hardened defaults
- upgrade/migration operations

## M12 — Production qualification

Before v0.1.0:

- multi-year generated/synthetic production-sized dataset
- PostgreSQL query/partition/rollup qualification
- retention tests
- backup/restore tests
- migration and upgrade tests on non-empty databases
- concurrent collection + public historical serving tests
- load testing
- soak testing
- failure/recovery testing
- deployment qualification on staging behind HTTPS
- stable versioned API review
- final documentation/README/release notes

## v0.1.0 — First production release

v0.1.0 is tagged only after the production gate in M8.0 and M12 is satisfied. There is no planned public alpha/beta/preview tag before that gate.
