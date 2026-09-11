from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from gaudi.mapgen import generate, header_matches_git, is_fresh
from gaudi.paths import MAP_REL


def _workspace_root(payload: dict[str, Any]) -> Path:
    roots = payload.get("workspace_roots") or payload.get("workspaceRoots")
    if isinstance(roots, list) and roots:
        return Path(str(roots[0])).resolve()
    cwd = payload.get("cwd")
    if cwd:
        return Path(str(cwd)).resolve()
    return Path.cwd().resolve()


def handle_session_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Cheap SHA/freshness check. Never includes .map body."""
    root = _workspace_root(payload)
    try:
        fresh = header_matches_git(root)
    except Exception:
        return {
            "additional_context": (
                "Gaudi map: STALE or unavailable — run gaudi generate before querying. "
                f"Path: {MAP_REL.as_posix()}"
            )
        }
    if fresh:
        ctx = (
            f"Gaudi map: fresh ({MAP_REL.as_posix()}). "
            "Use gaudi index / gaudi focus. Cues only — Read source before editing."
        )
    else:
        ctx = (
            "Gaudi map: STALE — run gaudi generate, then gaudi index or gaudi focus. "
            f"Path: {MAP_REL.as_posix()}"
        )
    return {"additional_context": ctx}


def handle_stop(payload: dict[str, Any]) -> dict[str, Any]:
    """Regenerate if stale. Caller should fail open if gaudi cannot import."""
    root = _workspace_root(payload)
    try:
        if not is_fresh(root):
            generate(root, quiet=True)
    except Exception:
        return {}
    return {}


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("hook stdin must be a JSON object")
    return data
