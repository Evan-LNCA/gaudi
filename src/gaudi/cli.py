from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaudi import __version__
from gaudi.errors import GaudiError
from gaudi.hooks import handle_session_start, handle_stop, read_stdin_json
from gaudi.install import install
from gaudi.ledger import instruction_tokens, load_ledger_config, load_snapshots, session_start_tokens
from gaudi.mapgen import generate, status_code
from gaudi.query import run_focus, run_index, run_where
from gaudi.scorecard import (
    ab_json,
    compute_ab,
    compute_scorecard,
    render_ab,
    render_scorecard,
    scorecard_json,
)
from gaudi.ship import ShipError, check_ship


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except OSError:
            continue


def _run_stats(root: Path, *, fmt: str, ab: bool) -> int:
    try:
        data = load_snapshots(root)
        config = load_ledger_config(root)
    except RuntimeError as exc:
        raise GaudiError(str(exc)) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise GaudiError(f"Cannot read gaudi ledger config under {root}: {exc}") from exc
    if ab:
        ab_report = compute_ab(data, min_sessions=config.min_sessions)
        if fmt == "json":
            sys.stdout.write(json.dumps(ab_json(ab_report), indent=2, ensure_ascii=False) + "\n")
        else:
            sys.stdout.write(render_ab(ab_report))
        return 0
    harnesses = {session.harness for session in data.sessions}
    instruction = {name: instruction_tokens(root, name) for name in harnesses}
    card = compute_scorecard(
        data,
        cache_read_multiplier=config.cache_read_multiplier,
        instruction_tokens_by_harness=instruction,
        session_start_tokens=session_start_tokens(),
    )
    if fmt == "json":
        sys.stdout.write(json.dumps(scorecard_json(card), indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(render_scorecard(card))
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(prog="gaudi", description="Ranked signature map for AI coding agents")
    parser.add_argument("--root", type=str, default=None, help="Workspace root (default: cwd)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress warnings and the generate summary")
    parser.add_argument("--no-git", action="store_true", help="Force filesystem walk instead of git ls-files")
    sub = parser.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="Parse sources, update ignore files, and write .map")
    gen.add_argument("--map-tokens", type=int, default=None)

    sub.add_parser("status", help="Exit 0 if map matches HEAD and source-tree fingerprint")
    inst = sub.add_parser("install", help="Merge hooks/ignores, write rule/instructions, generate map")
    inst.add_argument(
        "--target",
        choices=["all", "cursor", "copilot", "claude", "agents"],
        default="all",
        help="Target environment (default: all)",
    )
    inst.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Append or replace existing instruction files without prompting",
    )
    inst.add_argument(
        "--with-ledger",
        action="store_true",
        help="Opt in to per-read/session ledger hooks for the selected --target",
    )
    sub.add_parser("check-ship", help="Fail if the map would ship in Docker or dist/build")
    sub.add_parser("hook-session-start", help="Cursor sessionStart: stdin JSON → stdout JSON")
    sub.add_parser("hook-stop", help="Cursor stop: regenerate if stale")

    focus = sub.add_parser("focus", help="Personalized PageRank neighborhood to stdout (never writes .map)")
    focus.add_argument("seeds", nargs="+", help="File path or symbol")
    focus.add_argument("--tokens", type=int, default=None)
    focus.add_argument("--format", choices=["text", "json"], default="text")

    where = sub.add_parser("where", help="Print path:line plus signature for a symbol")
    where.add_argument("symbol")
    where.add_argument("--format", choices=["text", "json"], default="text")

    index = sub.add_parser("index", help="Top hubs plus directory shape with def counts")
    index.add_argument("--tokens", type=int, default=None)
    index.add_argument("--format", choices=["text", "json"], default="text")

    stats = sub.add_parser("stats", help="Print local token scorecard (chars/4 estimate)")
    stats.add_argument("--format", choices=["text", "json"], default="text")
    stats.add_argument(
        "--ab",
        action="store_true",
        help="Compare on/off arms using per-session measured medians",
    )

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.error("a command is required")
    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    quiet = bool(args.quiet)
    no_git = bool(args.no_git)

    try:
        if args.cmd == "generate":
            result = generate(root, map_tokens=args.map_tokens, quiet=quiet, no_git=no_git)
            if not quiet:
                print(
                    f"wrote .map: {result.files} files, {result.defs} defs, "
                    f"~{result.tokens} tokens, {result.elapsed:.1f}s"
                )
            return 0
        if args.cmd == "status":
            return status_code(root, no_git=no_git)
        if args.cmd == "install":
            install(
                root,
                target=args.target,
                no_git=no_git,
                yes=args.yes,
                with_ledger=args.with_ledger,
            )
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
        if args.cmd == "focus":
            out = run_focus(
                root,
                args.seeds,
                tokens=args.tokens,
                fmt=args.format,
                no_git=no_git,
                quiet=quiet,
            )
            sys.stdout.write(out.text)
            return 0
        if args.cmd == "where":
            out = run_where(root, args.symbol, fmt=args.format, no_git=no_git)
            sys.stdout.write(out.text)
            return 0
        if args.cmd == "index":
            out = run_index(
                root,
                tokens=args.tokens,
                fmt=args.format,
                no_git=no_git,
                quiet=quiet,
            )
            sys.stdout.write(out.text)
            return 0
        if args.cmd == "stats":
            return _run_stats(root, fmt=args.format, ab=args.ab)
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
