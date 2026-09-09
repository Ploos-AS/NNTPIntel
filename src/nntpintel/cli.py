from __future__ import annotations

import argparse
import json

from .probe import probe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe one NNTP server and emit normalized JSON")
    parser.add_argument("host", help="NNTP server hostname or address")
    parser.add_argument("--port", type=int, default=None, help="server port (default: 119 or 563 with --tls)")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--tls", action="store_true", help="use implicit TLS/NNTPS")
    transport.add_argument("--starttls", action="store_true", help="upgrade a plaintext connection with STARTTLS")
    parser.add_argument("--timeout", type=float, default=10.0, help="socket timeout in seconds")
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    port = args.port if args.port is not None else (563 if args.tls else 119)
    observation = probe(
        args.host,
        port=port,
        implicit_tls=args.tls,
        starttls=args.starttls,
        timeout=args.timeout,
    )
    print(
        json.dumps(
            observation.to_dict(),
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 1 if observation.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
