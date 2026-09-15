#!/usr/bin/env python3
"""Shared ledger hook. Fail open. Do not import gaudi.hooks."""
from __future__ import annotations

import json
import os
import sys


def _reconfigure() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except OSError:
            pass


def _parse_argv(argv: list[str]) -> tuple[str, str | None]:
    harness = os.environ.get("GAUDI_HARNESS") or ""
    event_hint: str | None = None
    args = list(argv)
    while args:
        item = args.pop(0)
        if item == "--harness" and args:
            harness = args.pop(0)
        elif item.startswith("--harness="):
            harness = item.split("=", 1)[1]
        elif item == "--event" and args:
            event_hint = args.pop(0)
        elif item.startswith("--event="):
            event_hint = item.split("=", 1)[1]
    return harness, event_hint


def _fail_open(payload: dict, harness: str, event_hint: str | None) -> dict:
    name = str(
        payload.get("hook_event_name")
        or payload.get("hookEventName")
        or event_hint
        or ""
    )
    folded = name.replace("_", "").replace("-", "").lower()
    if folded == "beforereadfile" or (harness == "cursor" and folded in {"", "read"}):
        return {"permission": "allow"}
    if folded == "pretooluse" or harness in {"copilot", "claude"}:
        if folded in {"pretooluse", "beforereadfile", ""}:
            return {"hookSpecificOutput": {"permissionDecision": "allow"}}
    return {}


def main() -> int:
    _reconfigure()
    raw = sys.stdin.read()
    payload: dict = {}
    if raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                payload = data
        except json.JSONDecodeError:
            payload = {}
    harness, event_hint = _parse_argv(sys.argv[1:])
    fallback = _fail_open(payload, harness, event_hint)
    try:
        from gaudi.ledger import handle_hook

        out = handle_hook(payload, harness=harness, event_hint=event_hint)
    except Exception:
        out = fallback
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
