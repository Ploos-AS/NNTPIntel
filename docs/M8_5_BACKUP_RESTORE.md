# M8.5 — Backup and restore

NNTPIntel production data is designed to retain multi-year statistics, evidence and operational history. Backup is therefore part of the production contract, not an optional convenience.

## Baseline format

The M8.5 baseline uses PostgreSQL custom-format backups created with `pg_dump --format=custom`. Ownership and privilege metadata are excluded so a backup can be restored into a clean qualification or replacement database under a different operator account.

Every backup has a sidecar JSON manifest containing:

- UTC creation timestamp
- format identifier
- backup byte size
- SHA-256 digest

`nntpintel-backup verify` checks the manifest, byte size, SHA-256 digest and whether `pg_restore --list` can read the archive.

## Commands

Create a backup:

```sh
nntpintel-backup backup /srv/backups/nntpintel-$(date -u +%Y%m%dT%H%M%SZ).dump
```

The source URL is read from `NNTPINTEL_DATABASE_URL` unless `--database-url` is supplied.

Verify a backup without modifying a database:

```sh
nntpintel-backup verify /srv/backups/nntpintel-20260912T150000Z.dump
```

Dry-run a restore. This verifies the archive and manifest but does not connect to the target database:

```sh
nntpintel-backup restore /srv/backups/nntpintel-20260912T150000Z.dump \
  --database-url postgresql://restore-user@db/nntpintel_restore
```

Perform a restore only after explicit confirmation:

```sh
nntpintel-backup restore /srv/backups/nntpintel-20260912T150000Z.dump \
  --database-url postgresql://restore-user@db/nntpintel_restore \
  --yes
```

`--clean --yes` may be used for an intentional replacement restore into an existing database. The safer normal recovery workflow is to restore into a newly created empty database, qualify it, and then switch the application to it.

## Credential handling

NNTPIntel does not pass a PostgreSQL URL containing credentials to `pg_dump` or `pg_restore` command-line arguments. URL fields are mapped into libpq `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` and optional `PGSSLMODE` environment variables for the child process.

Operators should still protect the environment, backup directory and manifest files using normal host-level access controls.

## Production policy

A production deployment should:

1. create backups on a schedule independent of the NNTP probing scheduler;
2. retain multiple generations according to an operator-defined policy;
3. copy at least one generation outside the primary database host or failure domain;
4. verify every newly created backup;
5. perform periodic restore drills into a clean PostgreSQL database;
6. monitor backup age, verification failures and restore-drill results.

A backup is not considered qualified merely because `pg_dump` exited successfully. Restore qualification is the actual recovery test.

## CI qualification

`tools/qualify_backup_restore.py` performs a live PostgreSQL round trip:

- inserts a deterministic marker row in the source database;
- creates a custom-format backup and manifest;
- verifies SHA-256 and `pg_restore --list` readability;
- creates a separate empty PostgreSQL database;
- restores the archive;
- verifies the marker row, schema version, maintenance history table and rollup schema;
- removes the qualification database.

This exercises the same PostgreSQL tooling used by operators and catches backups that are syntactically created but cannot actually restore.

## Current scope

This baseline covers logical full-database backup and restore. Later M8.5 slices may add generation rotation helpers, backup status persistence/metrics, encrypted off-host examples, and stronger post-restore semantic integrity checks. Point-in-time recovery and WAL archiving remain deployment-level PostgreSQL capabilities rather than being reimplemented by NNTPIntel.
