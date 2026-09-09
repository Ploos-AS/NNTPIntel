# M8.2 — PostgreSQL production schema and partitioning

M8.2 establishes the first PostgreSQL-native production schema for NNTPIntel.

## Scope

The production backend uses PostgreSQL-native types and time partitioning for the data sets expected to grow continuously over years.

Core entity tables are currently unpartitioned:

- `servers`
- `endpoints`
- `hierarchies`
- `newsgroups`
- `propagation_articles`

High-volume observation tables are partitioned by `observed_at` using PostgreSQL `RANGE` partitioning:

- `observations`
- `group_snapshots`
- `group_events`
- `propagation_observations`

Each partitioned table has a default partition so ingestion remains safe before automated time-partition maintenance is introduced.

## Time semantics

Production timestamps use `TIMESTAMPTZ`. NNTPIntel treats stored observation times as absolute instants. Public/API formatting will normalize timestamps consistently; local display time is a presentation concern.

Important timestamps include:

- observation times
- first/last-seen times
- scheduling times
- article dates where available
- schema migration application time

## JSON semantics

Structured payloads use `JSONB` in PostgreSQL, including capabilities, TLS metadata, raw normalized observations and event details. This differs intentionally from SQLite's JSON-as-text compatibility representation.

## Partition-key constraints

PostgreSQL requires unique/primary constraints on partitioned tables to include the partition key. Therefore partitioned primary keys include `observed_at` alongside the generated identity ID.

Domain uniqueness also includes `observed_at` where applicable, for example:

- `(endpoint_id, newsgroup_id, observed_at)` for group snapshots
- `(article_id, endpoint_id, observed_at)` for propagation observations

## Indexing baseline

The parent partitioned tables define indexes for the principal historical access paths:

- endpoint + observation time
- newsgroup + snapshot time
- endpoint + group-event time
- article + propagation-observation time
- endpoint + propagation-observation time

PostgreSQL propagates partitioned indexes to partitions.

## Default partitions

Default partitions are a safety net, not the intended long-term storage layout. Later maintenance work must create bounded monthly partitions ahead of ingestion and move any eligible rows out of default partitions before retention or detach/drop operations.

M8.2 does not yet implement automatic partition creation, movement, pruning or retention. Those belong to later M8 maintenance milestones.

## Distributed-collector readiness

The schema deliberately keeps observation identity separate from future collector/vantage identity. M8.2 does not add distributed ingestion prematurely. M10 will introduce collector/vantage identity and authenticated central ingestion after the production storage and rollup model are qualified.

## Qualification gates

M8.2 is complete when:

- PostgreSQL migration v2 is idempotent
- production timestamps are `TIMESTAMPTZ`
- structured JSON fields use `JSONB`
- the four high-volume tables use `RANGE (observed_at)` partitioning
- each high-volume table has a default partition
- partitioned unique/primary constraints include the partition key
- the existing SQLite test suite remains green
- CI is green on supported Python versions

Actual PostgreSQL runtime execution against a live server is a required follow-up qualification before production release; static SQL-contract tests alone are not sufficient for v0.1.0.
