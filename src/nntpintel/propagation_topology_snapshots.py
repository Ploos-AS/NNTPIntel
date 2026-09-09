from __future__ import annotations

import json
from datetime import UTC, datetime

from nntpintel.propagation_topology_compare import compare_evidence_bundles
from nntpintel.propagation_topology_conclusions import topology_conclusions
from nntpintel.propagation_topology_export import topology_evidence_bundle
from nntpintel.storage import Storage


def _ensure_schema(storage: Storage) -> None:
    with storage.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS topology_evidence_snapshots (
                id INTEGER PRIMARY KEY,
                conclusion_ref TEXT NOT NULL,
                conclusion_type TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                UNIQUE(conclusion_ref, fingerprint)
            );

            CREATE INDEX IF NOT EXISTS idx_topology_evidence_snapshots_ref_time
            ON topology_evidence_snapshots(conclusion_ref, captured_at DESC, id DESC);
            """
        )
        conn.commit()


def capture_evidence_snapshot(
    storage: Storage,
    conclusion_ref: str,
    *,
    captured_at: str | None = None,
) -> dict | None:
    _ensure_schema(storage)
    timestamp = captured_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    bundle = topology_evidence_bundle(storage, conclusion_ref, generated_at=timestamp)
    if bundle is None:
        return None

    fingerprint = str(bundle["integrity"]["fingerprint"])
    conclusion_type = str(bundle["conclusion"]["type"])
    payload = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with storage.connect() as conn:
        existing = conn.execute(
            """
            SELECT id, captured_at FROM topology_evidence_snapshots
            WHERE conclusion_ref = ? AND fingerprint = ?
            """,
            (conclusion_ref, fingerprint),
        ).fetchone()
        if existing is not None:
            return {
                "created": False,
                "snapshot_id": int(existing["id"]),
                "conclusion_ref": conclusion_ref,
                "fingerprint": fingerprint,
                "captured_at": existing["captured_at"],
            }
        cursor = conn.execute(
            """
            INSERT INTO topology_evidence_snapshots(
                conclusion_ref, conclusion_type, fingerprint, captured_at, bundle_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (conclusion_ref, conclusion_type, fingerprint, timestamp, payload),
        )
        conn.commit()
        return {
            "created": True,
            "snapshot_id": int(cursor.lastrowid),
            "conclusion_ref": conclusion_ref,
            "fingerprint": fingerprint,
            "captured_at": timestamp,
        }


def capture_topology_snapshots(storage: Storage) -> dict:
    index = topology_conclusions(storage)
    created = 0
    unchanged = 0
    skipped = 0
    snapshot_ids: list[int] = []
    for item in index["conclusions"]:
        result = capture_evidence_snapshot(storage, str(item["conclusion_ref"]))
        if result is None:
            skipped += 1
        elif result["created"]:
            created += 1
            snapshot_ids.append(int(result["snapshot_id"]))
        else:
            unchanged += 1
    return {
        "model": "nntpintel_topology_evidence_snapshot_capture",
        "conclusion_count": int(index["conclusion_count"]),
        "created_count": created,
        "unchanged_count": unchanged,
        "skipped_count": skipped,
        "snapshot_ids": snapshot_ids,
    }


def list_evidence_snapshots(
    storage: Storage,
    conclusion_ref: str,
    *,
    limit: int = 100,
) -> dict:
    _ensure_schema(storage)
    limit = max(1, min(int(limit), 500))
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, conclusion_ref, conclusion_type, fingerprint, captured_at
            FROM topology_evidence_snapshots
            WHERE conclusion_ref = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT ?
            """,
            (conclusion_ref, limit),
        ).fetchall()
    return {
        "model": "nntpintel_topology_evidence_snapshot_history",
        "conclusion_ref": conclusion_ref,
        "snapshot_count": len(rows),
        "snapshots": [dict(row) for row in rows],
    }


def get_evidence_snapshot(storage: Storage, snapshot_id: int) -> dict | None:
    _ensure_schema(storage)
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT * FROM topology_evidence_snapshots WHERE id = ?",
            (int(snapshot_id),),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "conclusion_ref": row["conclusion_ref"],
        "conclusion_type": row["conclusion_type"],
        "fingerprint": row["fingerprint"],
        "captured_at": row["captured_at"],
        "bundle": json.loads(row["bundle_json"]),
    }


def compare_evidence_snapshots(storage: Storage, before_id: int, after_id: int) -> dict | None:
    before = get_evidence_snapshot(storage, before_id)
    after = get_evidence_snapshot(storage, after_id)
    if before is None or after is None:
        return None
    result = compare_evidence_bundles(before["bundle"], after["bundle"])
    result["snapshot_ids"] = {"before": before_id, "after": after_id}
    return result


def evidence_snapshot_timeline(
    storage: Storage,
    conclusion_ref: str,
    *,
    since: str | None = None,
    limit: int = 100,
) -> dict:
    _ensure_schema(storage)
    limit = max(1, min(int(limit), 500))
    params: list[object] = [conclusion_ref]
    where = "conclusion_ref = ?"
    if since:
        where += " AND captured_at >= ?"
        params.append(since)
    params.append(limit + 1)

    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, conclusion_ref, conclusion_type, fingerprint, captured_at, bundle_json
            FROM topology_evidence_snapshots
            WHERE {where}
            ORDER BY captured_at ASC, id ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()

    entries: list[dict] = []
    previous: dict | None = None
    for row in rows[:limit]:
        bundle = json.loads(row["bundle_json"])
        summary = None
        if previous is not None:
            diff = compare_evidence_bundles(previous["bundle"], bundle)
            summary = {
                "change_count": diff["change_count"],
                "changed_sections": diff["changed_sections"],
            }
        current = {
            "snapshot_id": int(row["id"]),
            "captured_at": row["captured_at"],
            "fingerprint": row["fingerprint"],
            "conclusion_type": row["conclusion_type"],
            "change_from_previous": summary,
        }
        entries.append(current)
        previous = {"bundle": bundle}

    return {
        "model": "nntpintel_topology_evidence_snapshot_timeline",
        "conclusion_ref": conclusion_ref,
        "since": since,
        "timeline_count": len(entries),
        "has_more": len(rows) > limit,
        "timeline": entries,
        "limitations": [
            "The timeline records changes in NNTPIntel evidence bundles, not proven real-world topology changes.",
            "Snapshots are fingerprint-deduplicated, so unchanged states are intentionally omitted.",
        ],
    }
