from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaudi.errors import GaudiError
from gaudi.gitutil import GitRepo
from gaudi.hooks import handle_session_start, handle_stop, read_stdin_json
from gaudi.install import install
from gaudi.mapgen import generate, status_code
from gaudi.ship import ShipError, check_ship


def _configure_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(prog="gaudi", description="Ranked signature map for AI coding agents")
    parser.add_argument("--root", type=str, default=None, help="Workspace root (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Parse git ls-files and write .cursor/gaudi/MAP.md")
    gen.add_argument("--map-tokens", type=int, default=None)

    sub.add_parser("status", help="Exit 0 if map matches HEAD and tracked source hashes")
    inst = sub.add_parser("install", help="Merge hooks/ignores, write rule/instructions, generate map")
    inst.add_argument(
        "--target",
        choices=["all", "cursor", "copilot"],
        default="all",
        help="Target environment (default: all)",
    )
    sub.add_parser("check-ship", help="Fail if the map would ship in Docker or dist/build")
    sub.add_parser("hook-session-start", help="Cursor sessionStart: stdin JSON → stdout JSON")
    sub.add_parser("hook-stop", help="Cursor stop: regenerate if stale")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()

    try:
        if args.cmd == "generate":
            generate(root, map_tokens=args.map_tokens)
            return 0
        if args.cmd == "status":
            GitRepo(root).require()
            return status_code(root)
        if args.cmd == "install":
            install(root, target=args.target)
            return 0
        if args.cmd == "check-ship":
            check_ship(root)
            return 0
        if args.cmd == "hook-session-start":
            payload = read_stdin_json()
            json.dump(handle_session_start(payload), sys.stdout)
            return 0
        if args.cmd == "hook-stop":
            payload = read_stdin_json()
            json.dump(handle_stop(payload), sys.stdout)
            return 0
    except ShipError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except GaudiError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
