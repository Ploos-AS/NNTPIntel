from __future__ import annotations

import argparse
import json
from pathlib import Path

from nntpintel.api import serve
from nntpintel.candidates import (
    list_candidate_qualifications,
    list_candidates,
    promote_candidate,
    qualify_candidates,
    set_candidate_status,
)
from nntpintel.cycle import (
    configure_cycle_schedule,
    list_cycle_runs,
    list_cycle_schedules,
    run_candidate_cycle,
    run_due_candidate_cycles,
)
from nntpintel.discovery import (
    BUILTIN_SOURCES,
    import_seeds,
    list_sources,
    refresh_builtin_source,
    refresh_source,
    set_server_enabled,
)
from nntpintel.propagation_campaigns import (
    create_campaign,
    list_campaigns,
    run_campaign,
    run_due_campaigns,
    set_campaign_enabled,
)
from nntpintel.scheduler import SchedulerConfig, run_forever, run_once
from nntpintel.source_management import set_cycle_schedule_enabled, set_source_enabled
from nntpintel.storage import Storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nntpintel")
    parser.add_argument("--db", default="data/nntpintel.db", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-endpoint", help="register an NNTP endpoint")
    add.add_argument("host")
    add.add_argument("--port", type=int, default=119)
    add.add_argument("--tls", action="store_true", help="use implicit TLS")
    add.add_argument("--starttls", action="store_true")
    add.add_argument("--interval", type=int, default=900)
    add.add_argument("--timeout", type=float, default=10.0)

    seed_import = sub.add_parser("import-seeds", help="import NNTP candidates from a text file")
    seed_import.add_argument("file", type=Path)
    seed_import.add_argument("--source", required=True, help="stable source/provenance name")
    seed_import.add_argument("--source-ref", help="URL or other human-readable source reference")
    seed_import.add_argument(
        "--activate",
        action="store_true",
        help="enable newly discovered servers for probing; default is disabled candidates",
    )

    refresh = sub.add_parser("refresh-source", help="refresh a complete NNTP discovery source snapshot")
    refresh.add_argument("--source", required=True)
    refresh.add_argument("--url", required=True)
    refresh.add_argument("--adapter", choices=["text", "open-nntp-html"], default="text")
    refresh.add_argument("--activate", action="store_true")

    builtin = sub.add_parser("refresh-builtin-source", help="refresh a curated NNTP discovery adapter")
    builtin.add_argument("name", choices=sorted(BUILTIN_SOURCES))
    builtin.add_argument("--activate", action="store_true")

    cycle = sub.add_parser(
        "candidate-cycle",
        help="refresh one curated source and safely qualify a small candidate batch",
    )
    cycle.add_argument("name", choices=sorted(BUILTIN_SOURCES))
    cycle.add_argument("--limit", type=int, default=3)
    cycle.add_argument("--timeout", type=float, default=5.0)

    cycle_runs = sub.add_parser("list-cycle-runs", help="list recorded candidate cycle history")
    cycle_runs.add_argument("--source")
    cycle_runs.add_argument("--limit", type=int, default=100)

    cycle_schedule = sub.add_parser(
        "schedule-cycle-source",
        help="persist conservative cycle cadence for a curated discovery source",
    )
    cycle_schedule.add_argument("name", choices=sorted(BUILTIN_SOURCES))
    cycle_schedule.add_argument("--interval", type=int, default=21600)
    cycle_schedule.add_argument("--limit", type=int, default=3)
    cycle_schedule.add_argument("--timeout", type=float, default=5.0)
    cycle_schedule.add_argument("--disabled", action="store_true")
    cycle_schedule.add_argument("--run-now", action="store_true")

    sub.add_parser("list-cycle-schedules", help="list persistent candidate cycle schedules")

    source_state = sub.add_parser("set-source-enabled", help="enable or disable a discovery source")
    source_state.add_argument("name")
    source_state.add_argument("state", choices=["on", "off"])

    schedule_state = sub.add_parser(
        "set-cycle-schedule-enabled",
        help="enable or disable an existing cycle schedule without changing its cadence",
    )
    schedule_state.add_argument("name")
    schedule_state.add_argument("state", choices=["on", "off"])
    schedule_state.add_argument("--run-now", action="store_true")

    due_cycles = sub.add_parser("run-due-cycles", help="run due candidate cycles once")
    due_cycles.add_argument("--limit", type=int, default=1)

    qualify = sub.add_parser("qualify-candidates", help="safely qualify disabled discovery candidates")
    qualify.add_argument("--limit", type=int, default=5)
    qualify.add_argument("--timeout", type=float, default=5.0)

    qualifications = sub.add_parser(
        "list-candidate-qualifications",
        help="list recent candidate qualification results",
    )
    qualifications.add_argument("--limit", type=int, default=100)

    sub.add_parser("list-candidates", help="list candidate status and qualification summary")

    promote = sub.add_parser("promote-candidate", help="promote a qualified candidate into monitoring")
    promote.add_argument("host")
    promote.add_argument("--min-reachable", type=int, default=2)

    decision = sub.add_parser("set-candidate-status", help="set candidate pending/rejected/ignored")
    decision.add_argument("host")
    decision.add_argument("status", choices=["pending", "rejected", "ignored"])
    decision.add_argument("--note")

    sub.add_parser("list-sources", help="list discovery sources and imported server counts")

    server_state = sub.add_parser("set-server-enabled", help="enable or disable a discovered server")
    server_state.add_argument("host")
    server_state.add_argument("state", choices=["on", "off"])

    campaign_create = sub.add_parser(
        "create-propagation-campaign",
        help="create a bounded persistent Message-ID propagation campaign",
    )
    campaign_create.add_argument("message_id")
    campaign_create.add_argument("endpoint_ids", nargs="+", type=int)
    campaign_create.add_argument("--interval", type=int, default=300)
    campaign_create.add_argument("--timeout", type=float, default=5.0)
    campaign_create.add_argument("--max-backoff", type=int, default=21600)
    campaign_create.add_argument("--ttl", type=int, default=86400)
    campaign_create.add_argument("--stop-after-visible", type=int)

    campaign_list = sub.add_parser("list-propagation-campaigns", help="list propagation campaigns")
    campaign_list.add_argument(
        "--status", choices=["active", "completed", "expired", "disabled"]
    )
    campaign_list.add_argument("--limit", type=int, default=100)

    campaign_state = sub.add_parser(
        "set-propagation-campaign-enabled",
        help="enable or disable a non-terminal propagation campaign",
    )
    campaign_state.add_argument("campaign_id", type=int)
    campaign_state.add_argument("state", choices=["on", "off"])

    campaign_run = sub.add_parser("run-propagation-campaign", help="run one propagation campaign now")
    campaign_run.add_argument("campaign_id", type=int)

    due_campaigns = sub.add_parser("run-due-propagation-campaigns", help="run active campaigns once")
    due_campaigns.add_argument("--limit", type=int, default=2)

    sub.add_parser("list-endpoints", help="list configured endpoints")
    sub.add_parser("run-once", help="probe all currently due endpoints once")

    daemon = sub.add_parser("run", help="run the scheduler continuously")
    daemon.add_argument("--poll-seconds", type=float, default=5.0)

    api = sub.add_parser("api", help="serve the read-only JSON API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8080)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = Storage(Path(args.db))

    if args.command == "add-endpoint":
        if args.tls and args.starttls:
            raise SystemExit("--tls and --starttls are mutually exclusive")
        endpoint_id = storage.ensure_endpoint(
            args.host,
            port=args.port,
            transport="tls" if args.tls else "tcp",
            starttls=args.starttls,
            interval_seconds=args.interval,
            timeout_seconds=args.timeout,
        )
        print(endpoint_id)
        return 0

    if args.command == "import-seeds":
        lines = args.file.read_text(encoding="utf-8").splitlines()
        result = import_seeds(
            storage,
            lines,
            source=args.source,
            source_ref=args.source_ref,
            activate=args.activate,
        )
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "refresh-source":
        result = refresh_source(
            storage,
            source=args.source,
            source_ref=args.url,
            adapter=args.adapter,
            activate=args.activate,
        )
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "refresh-builtin-source":
        result = refresh_builtin_source(storage, args.name, activate=args.activate)
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "candidate-cycle":
        try:
            result = run_candidate_cycle(
                storage,
                args.name,
                limit=args.limit,
                timeout=args.timeout,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "list-cycle-runs":
        try:
            rows = list_cycle_runs(storage, source=args.source, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        for row in rows:
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "schedule-cycle-source":
        try:
            result = configure_cycle_schedule(
                storage,
                args.name,
                interval_seconds=args.interval,
                candidate_limit=args.limit,
                timeout_seconds=args.timeout,
                enabled=not args.disabled,
                run_now=args.run_now,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "list-cycle-schedules":
        for row in list_cycle_schedules(storage):
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "set-source-enabled":
        try:
            result = set_source_enabled(storage, args.name, args.state == "on")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "set-cycle-schedule-enabled":
        try:
            result = set_cycle_schedule_enabled(
                storage,
                args.name,
                args.state == "on",
                run_now=args.run_now,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "run-due-cycles":
        try:
            results = run_due_candidate_cycles(storage, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        for row in results:
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "qualify-candidates":
        for row in qualify_candidates(storage, limit=args.limit, timeout=args.timeout):
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "list-candidate-qualifications":
        for row in list_candidate_qualifications(storage, limit=args.limit):
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "list-candidates":
        for row in list_candidates(storage):
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "promote-candidate":
        try:
            result = promote_candidate(storage, args.host, min_reachable=args.min_reachable)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "set-candidate-status":
        try:
            result = set_candidate_status(storage, args.host, args.status, note=args.note)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "list-sources":
        for row in list_sources(storage):
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "set-server-enabled":
        changed = set_server_enabled(storage, args.host, args.state == "on")
        if not changed:
            raise SystemExit(f"unknown server: {args.host}")
        return 0

    if args.command == "create-propagation-campaign":
        try:
            result = create_campaign(
                storage,
                args.message_id,
                args.endpoint_ids,
                interval_seconds=args.interval,
                timeout_seconds=args.timeout,
                max_backoff_seconds=args.max_backoff,
                ttl_seconds=args.ttl,
                stop_after_visible=args.stop_after_visible,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "list-propagation-campaigns":
        try:
            rows = list_campaigns(storage, status=args.status, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        for row in rows:
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "set-propagation-campaign-enabled":
        try:
            result = set_campaign_enabled(storage, args.campaign_id, args.state == "on")
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "run-propagation-campaign":
        try:
            result = run_campaign(storage, args.campaign_id)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "run-due-propagation-campaigns":
        try:
            rows = run_due_campaigns(storage, limit=args.limit)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        for row in rows:
            print(json.dumps(row, sort_keys=True))
        return 0

    if args.command == "list-endpoints":
        for row in storage.list_endpoints():
            print(json.dumps(dict(row), sort_keys=True))
        return 0

    if args.command == "run-once":
        print(run_once(storage))
        return 0

    if args.command == "run":
        run_forever(storage, config=SchedulerConfig(poll_seconds=args.poll_seconds))
        return 0

    if args.command == "api":
        serve(storage, host=args.host, port=args.port)
        return 0

    raise AssertionError("unreachable")
