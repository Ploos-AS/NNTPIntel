# M8.4 — Retention and maintenance

NNTPIntel treats raw-data retention as a destructive production operation. The production design is fail-closed: raw data is removed only after the long-term daily statistical rollups required for public historical service can be demonstrated for the exact data range being retired.

## Production policy

- raw observation retention is configurable; the default is 90 days
- a configurable safety lag (default 48 hours) keeps recent raw data beyond the nominal cutoff
- monthly PostgreSQL partition retirement is the primary production retention path
- exact table/month rollup coverage is checked before an attached monthly partition can be retired
- bulk retirement only selects monthly partitions whose complete month is before the safe cutoff and whose own required daily rollups are complete
- the DEFAULT partitions are never retirement targets
- bounded row pruning remains available only as a conservative fallback/recovery path
- rollup tables are never pruned by raw retention
- topology evidence snapshots, incidents, campaigns and normalized entity state are not raw-retention targets
- all maintenance timestamps are timezone-aware UTC
- destructive CLI operations require explicit `--yes`
- maintenance lifecycle results are persisted in `maintenance_runs`

The raw production tables covered by this milestone are:

- `observations`
- `group_snapshots`
- `group_events`
- `propagation_observations`

## Coverage rules

Coverage is domain-specific and is checked against the raw server/day values present in the exact interval being retired.

- `observations` requires both daily `server_observation_rollups` and daily `server_protocol_rollups`
- `group_snapshots` and `group_events` require daily `server_group_rollups`
- `propagation_observations` requires daily `server_propagation_rollups`

Topology rollups are intentionally not a prerequisite because M8.4 does not prune raw topology data.

For whole-partition retirement this exact table/month gate prevents unrelated historical gaps from blocking a safe partition. If the April `observations` partition has complete April observation/protocol rollups, for example, a missing March rollup in another domain does not block April retirement.

The bounded row-pruning fallback remains deliberately more conservative and uses the global safe-cutoff coverage gate.

## Operator workflow

Set the production PostgreSQL URL with `NNTPINTEL_DATABASE_URL` or pass `--database-url`.

Inspect current state:

```sh
nntpintel-maintenance status
```

Inspect the retention boundary, global fallback coverage and monthly retirement candidates without changing data:

```sh
nntpintel-maintenance plan
```

Create current and future monthly partitions. Keeping at least two future months prepared is recommended:

```sh
nntpintel-maintenance ensure-partitions --months-ahead 2
```

Preview all currently safe partition retirements:

```sh
nntpintel-maintenance retire-eligible
```

Retire a bounded number of eligible partitions:

```sh
nntpintel-maintenance retire-eligible --limit 4 --yes
```

Retire one known table/month explicitly:

```sh
nntpintel-maintenance retire-partition observations 2026-04 --yes
```

Use bounded row deletion only as a fallback/recovery mechanism when partition retirement is not appropriate:

```sh
nntpintel-maintenance apply --batch-size 10000 --yes
```

All destructive commands should normally be preceded by a read-only `plan` invocation and a current backup according to M8.5 once that milestone is deployed.

## Recommended schedule

A normal long-running installation should separate frequent safe lifecycle work from destructive retirement:

1. Run `status` and `ensure-partitions --months-ahead 2` daily.
2. Run `plan` daily after rollup jobs have completed.
3. Run `retire-eligible --limit 4 --yes` on a controlled daily or weekly maintenance schedule after a successful backup.
4. Review blocked/failed entries in `maintenance_runs`; do not bypass missing-rollup protection.
5. Keep row-prune `apply` out of the normal schedule. It is a recovery/fallback command, not the preferred retention mechanism.

The exact scheduler (systemd timer, cron, container scheduler or orchestration platform) is deployment-specific and belongs with M8.6. The important M8.4 invariant is that the commands are idempotent or fail closed and can be scheduled non-interactively only when destructive confirmation is explicitly supplied.

## Partition safety invariants

NNTPIntel only drops a partition when all of the following hold immediately before the destructive operation:

- the parent is one of the allowlisted raw production tables
- the derived child name is deterministic for that parent and UTC month
- the child is currently attached to the requested parent in the current PostgreSQL schema
- the child is not a DEFAULT partition
- the complete partition month ends at or before the conservative safe cutoff
- exact daily rollup coverage for the raw rows in that table/month is complete

When pre-creating a new monthly partition, NNTPIntel also refuses to create it when the DEFAULT partition already contains rows for that month. Those rows must be handled explicitly rather than being moved implicitly by maintenance code.

## Maintenance history

Production schema migration v9 owns `maintenance_runs`; runtime code does not create this schema lazily. Maintenance operations persist `running`, `success`, `failed` or `blocked` outcomes with JSON details and timestamps. A pristine production database therefore must have migrations applied before maintenance commands are used.

## Qualification

The PostgreSQL CI qualification covers:

- explicit migrations and maintenance history schema
- current/future partition creation
- DEFAULT-partition safety guards
- per-server/day rollup coverage
- blocked bounded row pruning without rollups
- successful bounded fallback pruning after rollups exist
- exact per-table/per-month partition coverage
- safe single-partition retirement
- safe enumeration and bounded bulk retirement
- unrelated historical rollup gaps not blocking an otherwise safe partition
- recent partitions blocked by the safe cutoff
- persisted maintenance status
- read-only CLI status/plan/dry-run behavior

## M8.4 completion state

M8.4 is complete when the repository has all of the following, which are now implemented and CI-qualified:

- explicit production maintenance schema migration
- persisted maintenance status
- future partition lifecycle management
- exact per-partition retention coverage
- single and bounded bulk partition retirement
- read-only planning and destructive confirmation in the production CLI
- bounded row pruning explicitly retained as fallback/recovery rather than the primary production path
- operator guidance and scheduling policy

The next production milestone is M8.5 — Backup and Restore.

## Production invariant

Long-term public statistics and retained provenance must survive raw-data pruning. NNTPIntel always prefers retaining excess raw data over deleting data whose derived historical coverage cannot be demonstrated.
