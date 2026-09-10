#!/usr/bin/env python3
"""Cursor sessionStart hook. Cheap SHA check only; never dump .map."""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        from gaudi.hooks import handle_session_start, read_stdin_json
    except ImportError:
        sys.stdout.write("{}")
        return 0
    try:
        payload = read_stdin_json()
        json.dump(handle_session_start(payload), sys.stdout)
    except Exception:
        sys.stdout.write("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
