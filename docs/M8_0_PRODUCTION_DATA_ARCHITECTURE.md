# M8.0 — Production Data Architecture

Status: architecture contract for the production track before the first public release.

NNTPIntel's first release is intended to be production-ready. There is no preview release target. The service must be able to collect, retain, aggregate and expose public NNTP/Usenet statistics continuously over multiple years.

## Decisions

### 1. PostgreSQL is the production database

SQLite remains supported for development, tests and small single-node installations, but it is not the production storage target for the public long-running service.

Production storage MUST use PostgreSQL. Application code MUST move behind an explicit storage interface rather than importing or depending on `sqlite3` outside the SQLite backend.

The migration path must preserve existing SQLite installations where practical; production qualification will include import/migration testing from a representative SQLite dataset.

### 2. Time is a first-class data dimension

All durable observations and derived statistics MUST use UTC timestamps with unambiguous semantics.

High-volume production tables MUST be designed for time-based partitioning. Initial PostgreSQL partitioning candidates are:

- endpoint observations
- group snapshots/events
- propagation observations
- evidence snapshots where growth warrants it

Partition granularity is an implementation decision, but monthly partitions are the default starting point for multi-year retention because they balance operational simplicity and pruning efficiency.

### 3. Raw evidence and long-term statistics are separate layers

NNTPIntel MUST retain enough raw evidence for explainability, incident reconstruction and confidence calculations, while serving multi-year public statistics from rollups rather than repeatedly scanning raw observations.

The production data model has three logical layers:

1. **raw observations** — protocol measurements and source evidence
2. **derived state/events** — incidents, inferred topology, evidence snapshots and change records
3. **statistical rollups** — immutable or reproducibly rebuildable aggregates optimized for public historical queries

Deleting or compacting raw observations under a retention policy MUST NOT silently destroy already-published long-term statistical history.

### 4. Rollup hierarchy

The production statistics pipeline MUST support at least:

- hourly rollups
- daily rollups
- monthly rollups
- yearly/all-time queries derived efficiently from lower-level aggregates

Rollups MUST be idempotent and safe to recompute for a time window.

Initial statistics families:

#### Server availability and latency

Per endpoint/server and time bucket:

- sample count
- success/failure count
- availability percentage
- latency min/max/average
- latency percentile support where the backend permits an efficient, well-defined implementation
- outage/recovery transition counts

#### NNTP capability and TLS posture

Per time bucket:

- capability presence/change counts
- plaintext/TLS/STARTTLS availability
- TLS-version/certificate posture summaries where observed
- posting/read-mode state changes

#### Group and hierarchy statistics

Per time bucket:

- observed group count
- hierarchy group count
- appeared/disappeared groups
- posting-status changes
- description/change event counts

#### Propagation statistics

Per article/group/server scope and time bucket where meaningful:

- campaign count
- valid presence sample count
- observed propagation delay distributions
- coverage
- lag/coverage/delay incident counts

Observed delay remains relative to NNTPIntel observation cadence; it is not asserted to be true feed transit time.

#### Topology and incident statistics

Per time bucket:

- inferred node/edge counts
- confidence distribution
- community/gateway counts
- anomaly and incident counts by kind/severity/status
- risk/evidence-level distributions
- significant evidence-change counts

These remain inferred/triage statistics and MUST retain the same disclaimers as the live models.

### 5. Public historical query contract

The public statistics service MUST support these minimum ranges before v0.1.0:

- last 24 hours
- 7 days
- 30 days
- 1 year
- arbitrary bounded date ranges
- all-time summary

A multi-year query MUST normally hit rollups, not raw observation tables.

Target public pages include:

- global statistics overview
- server history
- hierarchy/newsgroup history
- propagation history
- incident history
- inferred topology history
- data-quality/evidence history

The UI must make the selected time range and aggregation resolution explicit.

### 6. Retention

Retention is configurable and MUST distinguish raw data from rollups.

Initial production defaults to qualify later:

- raw endpoint observations: retain at least 180 days
- raw group snapshots: retain at least 180 days after rollup coverage is verified
- raw propagation observations: retain at least 365 days because they support provenance/topology analysis
- incidents/events/evidence snapshots: retain indefinitely by default
- daily/monthly/yearly rollups: retain indefinitely by default

These are policy defaults, not hard-coded schema limits. Production deployment MUST allow longer raw retention.

Retention jobs MUST:

- operate in bounded batches/partitions
- verify required rollup coverage before destructive pruning
- expose metrics/results
- never remove evidence still referenced by a retained evidence bundle unless the data model explicitly preserves the required provenance independently

### 7. Process separation

The production service MUST support separate process roles even if one binary/package supplies all roles:

- **collector/scheduler** — performs NNTP probes, discovery, group inventory and propagation campaigns
- **rollup/maintenance worker** — computes rollups, retention, evidence snapshots and maintenance jobs
- **API/web** — read-oriented public serving path

A slow public query MUST NOT block collection scheduling.

The first production deployment may run these roles as separate containers from the same OCI image.

### 8. Distributed collection readiness

M8 does not require fully distributed collectors, but the schema and ingestion boundary MUST not assume that every observation originates from the central host.

Future observations need a stable collector/vantage identity. M8 implementation must reserve a clean path for:

- collector identity
- observation source/vantage metadata
- authenticated central ingestion
- multiple observations of the same server from different locations

We will not fake this by adding unused columns everywhere; the storage/service boundary must simply avoid making central-local assumptions that would require another destructive redesign.

### 9. Caching and public service behavior

Long-range statistics are cacheable derived data.

The public service MUST eventually support:

- deterministic cache keys from metric/scope/range/resolution
- bounded query ranges and pagination where applicable
- server-side caching of expensive historical summaries
- cache invalidation or freshness windows tied to rollup completion
- Caddy/reverse-proxy deployment with HTTPS

Caching must never change metric semantics.

### 10. Prometheus observability

Prometheus support is optional for users but a first-class production integration.

Production metrics should cover at least:

- probe/campaign success and duration
- scheduler lag
- collector backlog
- database/rollup job duration and failures
- rollup freshness
- retention/pruning counts
- API request count/latency/status
- cache hit/miss
- current configured server/endpoint/group counts

High-cardinality labels such as arbitrary Message-ID or newsgroup names MUST NOT be exported naively.

## Storage abstraction requirements for M8.1

The current `Storage` class is SQLite-specific. M8.1 must introduce a backend boundary without a big-bang rewrite of all domain logic.

Required direction:

- common storage protocol/interface for operations used by scheduler/domain services
- `SQLiteStorage` for tests/dev/backward compatibility
- `PostgresStorage` for production
- migrations stored as explicit ordered migration units rather than ad-hoc schema mutation inside constructor startup
- database URL/config selection, with SQLite still easy by default for developers
- transaction boundaries owned by storage/repository operations
- SQL dialect differences isolated behind the backend where possible

Direct SQL in API/read-model modules is technical debt that must be migrated behind query/repository functions before production qualification.

## PostgreSQL implementation rules

M8.1/M8.2 implementation should use standard PostgreSQL features first. Do not require TimescaleDB for the initial production release.

Prefer:

- native declarative partitioning
- `TIMESTAMPTZ`
- explicit indexes matching public query shapes
- JSONB only for genuinely semi-structured fields
- constraints and foreign keys for durable invariants
- transactional/idempotent rollup upserts

A later optional TimescaleDB profile may be added only if it provides a demonstrated operational benefit without making it mandatory.

## Multi-year qualification dataset

Before v0.1.0, qualification MUST include a synthetic or generated dataset representing multiple years of operation. It must be large enough to exercise partitioning, rollups and historical query plans rather than merely containing old timestamps.

Qualification must prove:

- rollups are idempotent
- retention preserves long-term aggregates
- 1-year/all-time queries use bounded/aggregated paths
- backup/restore preserves raw + aggregate state
- schema upgrades work on a non-empty production-sized database
- API/web can serve historical statistics while collection continues

Exact performance budgets will be fixed once the PostgreSQL implementation exists and can be measured realistically.

## v0.1.0 production gate

No v0.1.0 release until all of the following are true:

- PostgreSQL production path qualified
- multi-year rollup/statistics service qualified
- public web/API history views available
- collector and web roles can run independently
- retention and maintenance jobs qualified
- backup/restore qualified
- production OCI/deployment profiles qualified
- HTTPS/reverse-proxy deployment documented and tested
- Prometheus metrics available as an optional integration
- stable versioned public API contract defined
- security review complete
- load/soak/recovery/upgrade qualification complete
- production staging instance has run successfully under realistic continuous collection

## M8.0 exit criteria

M8.0 is complete when this architecture is committed, the roadmap reflects the production-first release plan, and CI remains green. M8.0 does not itself claim PostgreSQL or multi-year runtime support; those are implementation milestones beginning with M8.1.
