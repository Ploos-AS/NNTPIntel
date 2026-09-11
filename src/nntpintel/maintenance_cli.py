from __future__ import annotations

import argparse
import datetime
import json
import os
from collections.abc import Sequence

from nntpintel.maintenance import (
    RetentionPolicy,
    plan_retention,
    prune_raw_batches,
    retire_monthly_partition,
)
from nntpintel.maintenance_status import finish_maintenance_run, start_maintenance_run
from nntpintel.partition_lifecycle import PARTITIONED_TABLES, ensure_partition_window
from nntpintel.storage_backend import PostgresStorage


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _database_url(value: str | None) -> str:
    result = value or os.environ.get("NNTPINTEL_DATABASE_URL")
    if not result:
        raise SystemExit("PostgreSQL URL required via --database-url or NNTPINTEL_DATABASE_URL")
    return result


def _policy(args: argparse.Namespace) -> RetentionPolicy:
    return RetentionPolicy(raw_days=args.raw_days, safety_lag_hours=args.safety_lag_hours)


def _month(value: str) -> datetime.datetime:
    try:
        parsed = datetime.datetime.strptime(value, "%Y-%m").replace(tzinfo=datetime.UTC)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("month must use YYYY-MM") from exc
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nntpintel-maintenance")
    parser.add_argument("--database-url")
    parser.add_argument("--raw-days", type=int, default=90)
    parser.add_argument("--safety-lag-hours", type=int, default=48)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show production schema, partitions and recent maintenance runs")
    sub.add_parser("plan", help="show retention readiness without changing data")

    ensure = sub.add_parser("ensure-partitions", help="create current/future monthly partitions")
    ensure.add_argument("--months-ahead", type=int, default=2)

    apply = sub.add_parser("apply", help="apply bounded raw retention; requires --yes")
    apply.add_argument("--batch-size", type=int, default=10_000)
    apply.add_argument("--yes", action="store_true", help="confirm destructive raw-row deletion")

    retire = sub.add_parser("retire-partition", help="drop one eligible monthly partition")
    retire.add_argument("table", choices=PARTITIONED_TABLES)
    retire.add_argument("month", type=_month, help="partition month as YYYY-MM")
    retire.add_argument("--yes", action="store_true", help="confirm destructive partition drop")
    return parser


def _status(conn, storage: PostgresStorage) -> dict:
    partitions = [
        row["partition_name"]
        for row in conn.execute(
            """
            SELECT child.relname AS partition_name
            FROM pg_inherits i
            JOIN pg_class parent ON parent.oid = i.inhparent
            JOIN pg_class child ON child.oid = i.inhrelid
            JOIN pg_namespace n ON n.oid = child.relnamespace
            WHERE n.nspname = current_schema()
              AND parent.relname = ANY(%s)
            ORDER BY child.relname
            """,
            (list(PARTITIONED_TABLES),),
        ).fetchall()
    ]
    recent = [
        {
            "id": int(row["id"]),
            "kind": row["kind"],
            "status": row["status"],
            "started_at": row["started_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
            "detail": row["detail_json"],
        }
        for row in conn.execute(
            """
            SELECT id, kind, status, started_at, finished_at, detail_json
            FROM maintenance_runs
            ORDER BY started_at DESC, id DESC
            LIMIT 20
            """
        ).fetchall()
    ]
    return {
        "backend": storage.backend_name,
        "schema_version": storage.schema_version(),
        "partitions": partitions,
        "recent_maintenance_runs": recent,
    }


def main(argv: Sequence[str] | None = None, *, now: datetime.datetime | None = None) -> int:
    args = build_parser().parse_args(argv)
    current = (now or _utc_now()).astimezone(datetime.UTC)
    storage = PostgresStorage(_database_url(args.database_url))
    policy = _policy(args)

    with storage.connect() as conn:
        if args.command == "status":
            print(json.dumps(_status(conn, storage), sort_keys=True))
            return 0

        plan = plan_retention(conn, now=current, policy=policy)
        plan_json = {
            "cutoff": plan.cutoff.isoformat(),
            "safe_cutoff": plan.safe_cutoff.isoformat(),
            "coverage_complete": plan.coverage_complete,
            "missing_rollups": list(plan.missing_rollups),
        }

        if args.command == "plan":
            print(json.dumps(plan_json, sort_keys=True))
            return 0

        if args.command == "ensure-partitions":
            run_id = start_maintenance_run(
                conn,
                kind="partition_lifecycle",
                detail={"months_ahead": args.months_ahead},
            )
            try:
                names = ensure_partition_window(conn, now=current, months_ahead=args.months_ahead)
            except Exception as exc:
                finish_maintenance_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    detail={"months_ahead": args.months_ahead},
                )
                raise SystemExit(str(exc)) from exc
            detail = {"months_ahead": args.months_ahead, "partitions": list(names)}
            finish_maintenance_run(conn, run_id=run_id, status="success", detail=detail)
            print(json.dumps(detail, sort_keys=True))
            return 0

        if args.command == "apply":
            if not args.yes:
                print(json.dumps({"dry_run": True, "plan": plan_json}, sort_keys=True))
                return 0
            run_id = start_maintenance_run(conn, kind="raw_retention", detail=plan_json)
            try:
                deleted = prune_raw_batches(
                    conn,
                    now=current,
                    policy=policy,
                    batch_size=args.batch_size,
                )
            except RuntimeError as exc:
                finish_maintenance_run(
                    conn,
                    run_id=run_id,
                    status="blocked",
                    detail={**plan_json, "reason": str(exc)},
                )
                raise SystemExit(str(exc)) from exc
            except Exception as exc:
                finish_maintenance_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    detail={**plan_json, "reason": str(exc)},
                )
                raise
            detail = {**plan_json, "deleted": deleted}
            finish_maintenance_run(conn, run_id=run_id, status="success", detail=detail)
            print(json.dumps(detail, sort_keys=True))
            return 0

        if args.command == "retire-partition":
            partition_name = f"{args.table}_{args.month:%Y_%m}"
            if not args.yes:
                print(
                    json.dumps(
                        {"dry_run": True, "partition": partition_name, "plan": plan_json},
                        sort_keys=True,
                    )
                )
                return 0
            run_id = start_maintenance_run(
                conn,
                kind="partition_retirement",
                detail={"partition": partition_name},
            )
            try:
                retired = retire_monthly_partition(
                    conn,
                    table=args.table,
                    month=args.month,
                    now=current,
                    policy=policy,
                )
            except RuntimeError as exc:
                finish_maintenance_run(
                    conn,
                    run_id=run_id,
                    status="blocked",
                    detail={"partition": partition_name, "reason": str(exc)},
                )
                raise SystemExit(str(exc)) from exc
            except Exception as exc:
                finish_maintenance_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    detail={"partition": partition_name, "reason": str(exc)},
                )
                raise
            detail = {"partition": retired}
            finish_maintenance_run(conn, run_id=run_id, status="success", detail=detail)
            print(json.dumps(detail, sort_keys=True))
            return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
