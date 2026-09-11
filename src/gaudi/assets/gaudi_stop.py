#!/usr/bin/env python3
"""Cursor stop hook. Regenerate if stale. Fail open if gaudi is missing."""
from __future__ import annotations

import json
import sys


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except OSError:
            pass
    try:
        from gaudi.hooks import handle_stop, read_stdin_json
    except ImportError:
        sys.stdout.write("{}")
        return 0
    try:
        payload = read_stdin_json()
        json.dump(handle_stop(payload), sys.stdout)
    except Exception:
        sys.stdout.write("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
