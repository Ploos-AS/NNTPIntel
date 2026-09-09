# NNTPIntel

NNTPIntel is an open-source observability and intelligence platform for public NNTP/Usenet infrastructure.

It collects passive, standards-based observations from NNTP servers and turns them into searchable history, health information, hierarchy/group changes, and later article-propagation measurements and topology hints.

## M0 scope

Initial goals:

- discover and inventory public NNTP servers
- collect connection, banner, capability, TLS and latency observations
- collect `LIST`, `LIST ACTIVE`, `LIST NEWSGROUPS` and `NEWGROUPS` data where permitted
- normalize observations into a durable data model
- retain historical snapshots and changes
- expose a small HTTP API and web UI
- run as an OCI image
- support amd64 and arm64
- support Docker and Podman

NNTPIntel is designed for observation and measurement, not unsolicited posting, authentication attacks, abuse, or bypassing provider controls.

## Planned areas

- Servers
- Hierarchies
- Newsgroups
- TLS/security posture
- Availability and latency history
- Change and incident detection
- Article propagation
- Network/feed topology inference
- Statistics and public API

## Architecture direction

```text
collectors
    |
    v
normalized observations
    |
    v
history / change detection
    |
    +--> API
    |
    +--> Web UI
```

Collection, normalization, storage, analysis and presentation should remain separated so new measurement methods can be added without coupling them to the UI.

## Status

Early development. M0 establishes project scope, principles, architecture and milestone plan.

See [docs/M0_FOUNDATION.md](docs/M0_FOUNDATION.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## License

MIT
