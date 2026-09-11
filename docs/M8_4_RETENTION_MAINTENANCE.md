# M8.4 — Retention and maintenance

NNTPIntel treats raw-data pruning as a destructive production operation. It is blocked unless the long-term statistical rollups required for public historical service have coverage through the retention safety boundary.

## Initial policy

- raw observation retention is configurable; the initial code default is 90 days
- a configurable safety lag (default 48 hours) keeps recent raw data beyond the nominal cutoff
- pruning is bounded by batch size
- the first retained raw tables are `observations`, `group_snapshots`, `group_events`, and `propagation_observations`
- rollup tables are never pruned by raw retention
- topology evidence snapshots, incidents, campaigns and normalized entity state are not raw-retention targets
- all maintenance timestamps are timezone-aware UTC

## Safety gate

Before deletion, NNTPIntel checks daily rollup coverage for availability/latency, TLS/capabilities, groups/hierarchies, propagation and topology/evidence. Missing coverage blocks retention rather than silently deleting source data.

This is intentionally conservative. Later M8.4 slices will add partition lifecycle management, persisted maintenance runs/status, scheduling and stronger per-domain coverage/integrity checks.

## Production invariant

Long-term public statistics and retained provenance must survive raw-data pruning. A maintenance implementation must prefer retaining excess raw data over deleting data whose derived coverage cannot be demonstrated.
