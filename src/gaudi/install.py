from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path

from gaudi.errors import GaudiError
from gaudi.mapgen import generate
from gaudi.paths import (
    AGENTS_MD_REL,
    CLAUDE_LEDGER_HOOK_REL,
    CLAUDE_MD_REL,
    CLAUDE_SETTINGS_REL,
    COPILOT_INSTRUCTIONS_REL,
    COPILOT_LEDGER_HOOK_REL,
    COPILOT_LEDGER_JSON_REL,
    COPILOT_SKILL_REL,
    CURSOR_LEDGER_HOOK_REL,
    CURSOR_RULE_MARKER,
    GAUDI_MD_MARKER,
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


def _command_has_needle(entries: object, needle: str) -> bool:
    return needle in json.dumps(entries)


def merge_cursor_ledger_hooks(existing: dict, python_cmd: str) -> dict:
    merged = json.loads(json.dumps(existing)) if existing else {}
    merged.setdefault("version", 1)
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise GaudiError(".cursor/hooks.json hooks must be an object")
    base = f"{python_cmd} .cursor/hooks/gaudi_ledger.py --harness cursor"

    def _append(event: str, command: str) -> None:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise GaudiError(f".cursor/hooks.json hooks.{event} must be a list")
        if _command_has_needle(entries, "gaudi_ledger"):
            return
        entries.append({"type": "command", "command": command})

    _append("beforeReadFile", f"{base} --event beforeReadFile")
    _append("sessionStart", f"{base} --event sessionStart")
    _append("sessionEnd", f"{base} --event sessionEnd")
    _append("preCompact", f"{base} --event preCompact")
    _append("afterShellExecution", f"{base} --event afterShellExecution")
    return merged


def merge_copilot_ledger_hooks(existing: dict, python_cmd: str) -> dict:
    merged = json.loads(json.dumps(existing)) if existing else {}
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise GaudiError(".github/hooks/gaudi-ledger.json hooks must be an object")
    command = f"{python_cmd} .github/hooks/gaudi_ledger.py --harness copilot"
    env = {"GAUDI_HARNESS": "copilot"}

    def _append(event: str) -> None:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise GaudiError(f".github/hooks/gaudi-ledger.json hooks.{event} must be a list")
        if _command_has_needle(entries, "gaudi_ledger"):
            return
        entries.append({"type": "command", "command": command, "env": env})

    for event in ("PreToolUse", "PostToolUse", "SessionStart", "Stop", "PreCompact"):
        _append(event)
    return merged


def merge_claude_ledger_hooks(existing: dict, python_cmd: str) -> dict:
    merged = json.loads(json.dumps(existing)) if existing else {}
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise GaudiError(".claude/settings.json hooks must be an object")
    command = f"{python_cmd} .claude/hooks/gaudi_ledger.py --harness claude"
    env = {"GAUDI_HARNESS": "claude"}

    def _append(event: str, matcher: str | None) -> None:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise GaudiError(f".claude/settings.json hooks.{event} must be a list")
        if _command_has_needle(entries, "gaudi_ledger"):
            return
        block: dict[str, object] = {
            "hooks": [{"type": "command", "command": command, "env": env}]
        }
        if matcher is not None:
            block["matcher"] = matcher
        entries.append(block)

    _append("PreToolUse", "Read")
    _append("PostToolUse", "Bash")
    _append("SessionStart", None)
    _append("SessionEnd", None)
    _append("UserPromptSubmit", None)
    _append("PreCompact", None)
    return merged


def merge_instruction_section(existing: str, section: str) -> str:
    if GAUDI_MD_MARKER in existing:
        return existing
    body = existing.rstrip()
    if body:
        return f"{body}\n\n{section.strip()}\n"
    return f"{section.strip()}\n"


def _default_confirm(prompt: str) -> bool:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    reply = input(prompt).strip().lower()
    return reply in {"y", "yes"}


def _gate_instruction_file(
    path: Path,
    *,
    display: str,
    verb: str,
    yes: bool,
    confirm: Callable[[str], bool],
    has_marker: Callable[[str], bool],
    content: Callable[[str], str],
) -> None:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content(""), encoding="utf-8")
        return
    existing = path.read_text(encoding="utf-8")
    if has_marker(existing):
        return
    if yes or confirm(f"{display} already exists. {verb} Gaudi instructions? [y/N] "):
        path.write_text(content(existing), encoding="utf-8")


def _install_markdown_section(
    root: Path,
    rel: Path,
    section_text: str,
    *,
    yes: bool,
    confirm: Callable[[str], bool],
) -> None:
    _gate_instruction_file(
        under(root, rel),
        display=rel.as_posix(),
        verb="Append",
        yes=yes,
        confirm=confirm,
        has_marker=lambda text: GAUDI_MD_MARKER in text,
        content=lambda existing: merge_instruction_section(existing, section_text),
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_json_object(path: Path, display: str) -> dict:
    if not path.is_file():
        return {}
    existing = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(existing, dict):
        raise GaudiError(f"{display} must contain a JSON object")
    return existing


def install(
    root: Path,
    python_cmd: str | None = None,
    target: str = "all",
    *,
    no_git: bool = False,
    yes: bool = False,
    confirm: Callable[[str], bool] | None = None,
    with_ledger: bool = False,
) -> None:
    python_cmd = python_cmd or detect_python_command()
    confirm_fn = confirm or _default_confirm

    update_all_ignore_files(root)

    install_cursor = target in ("cursor", "all", "both")
    install_copilot = target in ("copilot", "all", "both")
    install_claude = target in ("claude", "all", "both")
    install_agents = target in ("agents", "all", "both")
    section_text = _asset_text("copilot-instructions-section.md")

    if install_cursor:
        rule_text = _asset_text("gaudi-map.mdc")
        if not rule_text.endswith("\n"):
            rule_text += "\n"
        _gate_instruction_file(
            under(root, RULE_REL),
            display=RULE_REL.as_posix(),
            verb="Replace",
            yes=yes,
            confirm=confirm_fn,
            has_marker=lambda text: CURSOR_RULE_MARKER in text,
            content=lambda _existing: rule_text,
        )

        _copy_asset("gaudi_session_start.py", under(root, HOOK_START_REL))
        _copy_asset("gaudi_stop.py", under(root, HOOK_STOP_REL))

        hooks_path = under(root, HOOKS_JSON_REL)
        existing = _load_json_object(hooks_path, str(hooks_path))
        if not existing:
            existing = {"version": 1, "hooks": {}}
        merged = merge_hooks_json(existing, python_cmd)
        if with_ledger:
            _copy_asset("gaudi_ledger.py", under(root, CURSOR_LEDGER_HOOK_REL))
            merged = merge_cursor_ledger_hooks(merged, python_cmd)
        _write_json(hooks_path, merged)

    if install_copilot:
        _install_markdown_section(
            root,
            COPILOT_INSTRUCTIONS_REL,
            section_text,
            yes=yes,
            confirm=confirm_fn,
        )
        _copy_asset("gaudi-skill.md", under(root, COPILOT_SKILL_REL))

    if install_claude:
        _install_markdown_section(root, CLAUDE_MD_REL, section_text, yes=yes, confirm=confirm_fn)

    if install_agents:
        _install_markdown_section(root, AGENTS_MD_REL, section_text, yes=yes, confirm=confirm_fn)

    if with_ledger and install_copilot:
        _copy_asset("gaudi_ledger.py", under(root, COPILOT_LEDGER_HOOK_REL))
        copilot_path = under(root, COPILOT_LEDGER_JSON_REL)
        copilot_existing = _load_json_object(copilot_path, copilot_path.as_posix())
        _write_json(copilot_path, merge_copilot_ledger_hooks(copilot_existing, python_cmd))

    if with_ledger and install_claude:
        _copy_asset("gaudi_ledger.py", under(root, CLAUDE_LEDGER_HOOK_REL))
        claude_path = under(root, CLAUDE_SETTINGS_REL)
        claude_existing = _load_json_object(claude_path, claude_path.as_posix())
        _write_json(claude_path, merge_claude_ledger_hooks(claude_existing, python_cmd))

    generate(root, quiet=True, no_git=no_git)
