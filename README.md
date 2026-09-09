# NNTPIntel

NNTPIntel is an open-source observability and intelligence platform for public NNTP/Usenet infrastructure.

It collects passive, standards-based observations from NNTP servers and turns them into searchable history, health information, hierarchy/group changes, propagation measurements, inferred topology intelligence, incidents, explainable evidence and long-term statistics.

## Current status

NNTPIntel has completed the main M1–M7 intelligence foundation and has entered the production architecture track at **M8.0**.

Implemented areas include:

- NNTP probing over TCP/119, NNTPS/563 and STARTTLS
- capabilities, greeting, posting/read-mode and TLS observations
- SQLite persistence and recurring scheduling
- safe group/hierarchy inventory and change history
- controlled NNTP-specific discovery and candidate qualification
- read-only JSON API and server-rendered web UI
- metadata-only Message-ID propagation measurements
- propagation analytics, trends and incidents
- confidence-scored inferred topology, history and anomalies
- topology incidents, impact, communities, cross-cluster intelligence and resilience analysis
- risk synthesis with evidence/data-quality overlays
- evidence provenance and per-conclusion explainability
- deterministic evidence bundles and SHA-256 fingerprints
- persisted evidence snapshots, timeline/diff, semantic change summaries and significance classification

The project is **not released yet**. The first public release will be **v0.1.0**, and it is intended to be production-ready rather than a preview build.

The current production track adds PostgreSQL, multi-year statistical rollups, retention/maintenance, public historical statistics, distributed-collection readiness, production deployment/observability and full production qualification before the first tag.

See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/M8_0_PRODUCTION_DATA_ARCHITECTURE.md](docs/M8_0_PRODUCTION_DATA_ARCHITECTURE.md).

### Development install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e . pytest ruff
pytest
ruff check .
```

### Probe examples

Plain NNTP on port 119:

```bash
nntpintel-probe news.example.net
```

Implicit TLS/NNTPS on port 563:

```bash
nntpintel-probe news.example.net --tls
```

STARTTLS on port 119:

```bash
nntpintel-probe news.example.net --starttls
```

A custom port and timeout may also be supplied:

```bash
nntpintel-probe news.example.net --port 8119 --timeout 5
```

The command exits non-zero when the observation contains an error, while still emitting the JSON observation so callers can retain failed measurements.

## Project goals

- discover and inventory public NNTP servers safely
- collect connection, banner, capability, TLS and latency observations
- collect `LIST`, `LIST ACTIVE`, `LIST NEWSGROUPS` and `NEWGROUPS` data where permitted
- measure metadata-only article propagation using Message-ID
- normalize observations into durable historical models
- retain explainable evidence and inferred topology history
- expose public web/API statistics over multiple years
- run continuously as a production service
- support PostgreSQL for production and SQLite for development/small deployments
- publish an OCI image for amd64/arm64
- support Docker and Podman
- support optional Prometheus observability

NNTPIntel is designed for observation and measurement, not unsolicited posting, authentication attacks, abuse, indiscriminate scanning or bypassing provider controls.

## Architecture direction

```text
collectors / scheduler
        |
        v
raw observations
        |
        +--> derived state / incidents / evidence
        |
        +--> rollup worker --> hourly/daily/monthly/yearly statistics
                                |
                                v
                         API / public web
```

Production collection, maintenance/rollups and public serving must be independently runnable roles so slow public queries do not block measurements.

## Production-first release policy

There is no planned preview release. v0.1.0 will only be tagged after PostgreSQL, multi-year statistics, retention, backup/restore, deployment, security, load/soak/recovery and staging qualification meet the documented production gate.

## License

MIT
