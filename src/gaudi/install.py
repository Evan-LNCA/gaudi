from __future__ import annotations

import json
import subprocess
from importlib import resources
from pathlib import Path

from gaudi.errors import GaudiError
from gaudi.mapgen import generate
from gaudi.paths import (
    COPILOT_INSTRUCTIONS_REL,
    COPILOT_SKILL_REL,
    HOOK_START_REL,
    HOOK_STOP_REL,
    HOOKS_JSON_REL,
    RULE_REL,
    under,
)
from gaudi.ship import update_all_ignore_files


def detect_python_command() -> str:
    candidates = (["python"], ["py", "-3"], ["python3"])
    for cmd in candidates:
        try:
            proc = subprocess.run(
                [*cmd, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, OSError):
            continue
        if proc.returncode == 0:
            return " ".join(cmd)
    raise GaudiError("Python 3.11+ not found (tried python, py -3, python3)")


def _asset_text(name: str) -> str:
    return resources.files("gaudi.assets").joinpath(name).read_text(encoding="utf-8")


def _copy_asset(name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = resources.files("gaudi.assets").joinpath(name).read_bytes()
    dest.write_bytes(data)
    if dest.suffix == ".py" and not data.endswith(b"\n"):
        dest.write_bytes(data + b"\n")


def merge_hooks_json(existing: dict, python_cmd: str) -> dict:
    merged = json.loads(json.dumps(existing)) if existing else {}
    merged.setdefault("version", 1)
    hooks = merged.setdefault("hooks", {})
    start_cmd = f"{python_cmd} .cursor/hooks/gaudi_session_start.py"
    stop_cmd = f"{python_cmd} .cursor/hooks/gaudi_stop.py"

    def _append(event: str, needle: str, command: str) -> None:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise GaudiError(f".cursor/hooks.json hooks.{event} must be a list")
        for item in entries:
            if isinstance(item, dict) and needle in str(item.get("command", "")):
                return
        entries.append({"type": "command", "command": command})

    _append("sessionStart", "gaudi_session_start", start_cmd)
    _append("stop", "gaudi_stop", stop_cmd)
    return merged


def merge_copilot_instructions(existing: str, section: str) -> str:
    marker = "## Gaudi Map"
    if marker in existing:
        return existing
    body = existing.rstrip()
    if body:
        return f"{body}\n\n{section.strip()}\n"
    return f"{section.strip()}\n"


def install(
    root: Path,
    python_cmd: str | None = None,
    target: str = "all",
    *,
    no_git: bool = False,
) -> None:
    python_cmd = python_cmd or detect_python_command()

    install_cursor = target in ("cursor", "all", "both")
    install_copilot = target in ("copilot", "all", "both")
    write_generated_outputs = target in ("cursor", "all", "both")

    if install_cursor:
        rule_text = _asset_text("gaudi-map.mdc")
        rule_path = under(root, RULE_REL)
        rule_path.parent.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(rule_text if rule_text.endswith("\n") else rule_text + "\n", encoding="utf-8")

        _copy_asset("gaudi_session_start.py", under(root, HOOK_START_REL))
        _copy_asset("gaudi_stop.py", under(root, HOOK_STOP_REL))

        hooks_path = under(root, HOOKS_JSON_REL)
        if hooks_path.is_file():
            existing = json.loads(hooks_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise GaudiError(f"{hooks_path} must contain a JSON object")
        else:
            existing = {"version": 1, "hooks": {}}
        merged = merge_hooks_json(existing, python_cmd)
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    if install_copilot:
        copilot_file = under(root, COPILOT_INSTRUCTIONS_REL)
        copilot_file.parent.mkdir(parents=True, exist_ok=True)
        existing_text = copilot_file.read_text(encoding="utf-8") if copilot_file.is_file() else ""
        section_text = _asset_text("copilot-instructions-section.md")
        merged_text = merge_copilot_instructions(existing_text, section_text)
        copilot_file.write_text(merged_text, encoding="utf-8")
        _copy_asset("gaudi-skill.md", under(root, COPILOT_SKILL_REL))

    if write_generated_outputs:
        update_all_ignore_files(root)
        generate(root, quiet=True, no_git=no_git)
