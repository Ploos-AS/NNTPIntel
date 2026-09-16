from __future__ import annotations

from datetime import datetime, timezone

from nntpintel.storage_backend import StorageBackend

_ROLLUP_TABLES = {
    "servers": ("server_observation_rollups",),
    "groups": ("server_group_rollups", "server_group_value_rollups"),
    "protocol": ("server_protocol_rollups", "server_protocol_value_rollups"),
    "propagation": (
        "server_propagation_rollups",
        "server_propagation_value_rollups",
        "propagation_campaign_rollups",
    ),
    "topology": ("topology_rollups", "topology_value_rollups"),
}


def _timestamp_token(value: object) -> str:
    if value is None:
        return "empty"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def rollup_freshness_token(storage: StorageBackend, family: str) -> str:
    """Return a token that changes when a completed rollup family changes."""
    if storage.backend_name != "postgresql":
        raise RuntimeError("statistics freshness requires PostgreSQL")
    tables = _ROLLUP_TABLES.get(family)
    if tables is None:
        raise ValueError(f"unknown statistics rollup family: {family}")

    parts: list[str] = []
    with storage.connect() as conn:
        for table in tables:
            row = conn.execute(f"SELECT MAX(generated_at) AS generated_at FROM {table}").fetchone()
            parts.append(f"{table}={_timestamp_token(row['generated_at'] if row else None)}")
    return "|".join(parts)
