# NNTPIntel

NNTPIntel is an open-source observability and intelligence platform for public NNTP/Usenet infrastructure.

It collects passive, standards-based observations from NNTP servers and turns them into searchable history, health information, hierarchy/group changes, and later article-propagation measurements and topology hints.

## Current status

M1 probe engine is now implemented. It can probe a single NNTP endpoint over plaintext TCP, implicit TLS/NNTPS, or STARTTLS and emit normalized JSON containing connection latency, greeting/posting status, capabilities, MODE READER response, TLS metadata, and errors.

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

See [docs/M0_FOUNDATION.md](docs/M0_FOUNDATION.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## License

MIT
