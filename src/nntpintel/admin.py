from __future__ import annotations

import argparse
import json
from pathlib import Path

from nntpintel.scheduler import SchedulerConfig, run_forever, run_once
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

    sub.add_parser("list-endpoints", help="list configured endpoints")
    sub.add_parser("run-once", help="probe all currently due endpoints once")

    daemon = sub.add_parser("run", help="run the scheduler continuously")
    daemon.add_argument("--poll-seconds", type=float, default=5.0)

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

    raise AssertionError("unreachable")
