# M0 — Foundation

## Mission

NNTPIntel provides longitudinal visibility into public NNTP/Usenet infrastructure.

It should answer questions such as:

- Which public NNTP servers are reachable?
- Which protocol capabilities do they expose?
- Which hierarchies and groups do they carry?
- How do availability, TLS configuration and latency change over time?
- When do groups appear, disappear, or change status?
- How quickly do selected public articles propagate between observation points?
- What can repeated observations infer about feed relationships and incidents?

## Principles

1. Passive and standards-based observation first.
2. Do not require credentials for the baseline public dataset.
3. Respect server policy, rate limits and operator opt-out.
4. Minimize traffic and cache expensive observations.
5. Keep raw observations separate from derived conclusions.
6. Timestamp and retain provenance for every observation.
7. Never represent inferred topology as confirmed fact.
8. Prefer reproducible measurements over opaque scoring.
9. Avoid article-body collection unless explicitly required by a future feature.
10. Support self-hosting from the beginning.

## Initial target protocols

- NNTP over TCP/119
- NNTPS over TCP/563
- STARTTLS where advertised
- RFC 3977 core commands
- relevant capability extensions discovered through `CAPABILITIES`

## Initial collector set

### Server probe

Records:

- DNS resolution result
- address family
- TCP connect result
- connect latency
- server greeting
- posting status from greeting
- `CAPABILITIES`
- `MODE READER` behavior
- `QUIT` behavior

### TLS probe

Records:

- direct TLS or STARTTLS
- negotiated protocol version
- cipher
- certificate subject/SANs
- issuer
- validity interval
- certificate fingerprint

### Group inventory

When supported and permitted:

- `LIST`
- `LIST ACTIVE`
- `LIST NEWSGROUPS`
- `NEWGROUPS`

The collector must use conservative scheduling and bounded response sizes.

## Non-goals for M0

- posting articles
- authentication brute force
- credential collection
- bypassing access controls
- downloading binary payloads
- mass article-body archival
- active exploitation or vulnerability scanning

## Data model direction

Core entities:

- server
- endpoint
- observation
- capability snapshot
- TLS snapshot
- hierarchy
- newsgroup
- group snapshot
- incident
- article observation
- propagation measurement

Derived and inferred data must retain links to the observations supporting it.

## Deployment direction

First-class targets:

- OCI container
- Docker Compose
- Podman
- rootless-friendly operation
- amd64
- arm64

Persistent state will live below `/data`.

SQLite is acceptable for the first single-node implementation. Schema boundaries should leave a clean migration path to PostgreSQL if later scale requires it.

## Ethics and operator controls

Future collector implementation must include:

- per-host rate limits
- global concurrency bounds
- retry backoff
- configurable exclusions
- operator opt-out list
- clear project/operator identification where applicable
- no evasion when blocked

## M0 exit criteria

M0 is complete when:

- project mission and boundaries are documented
- architecture direction is documented
- initial entities and collectors are defined
- milestone roadmap exists
- MIT license is present
- repository has a usable README
