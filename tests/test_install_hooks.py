from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from gaudi.cli import main
from gaudi.hooks import handle_session_start, handle_stop
from gaudi.install import install, merge_hooks_json
from gaudi.mapgen import generate
from gaudi.paths import AGENTS_MD_REL, CLAUDE_MD_REL, HOOKS_JSON_REL, MAP_REL, RULE_REL
from gaudi.ship import GITIGNORE_LINE, ShipError, check_ship

from tests.support import commit_all, map_text, run_cli


def test_install_idempotent_preserves_other_hooks(git_repo) -> None:
    hooks = git_repo / HOOKS_JSON_REL
    hooks.parent.mkdir(parents=True, exist_ok=True)
    hooks.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [{"type": "command", "command": "python ./hooks/noop.py"}],
                    "stop": [{"type": "prompt", "prompt": "keep me"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    install(git_repo, python_cmd="python")
    install(git_repo, python_cmd="python")
    data = json.loads(hooks.read_text(encoding="utf-8"))
    starts = data["hooks"]["sessionStart"]
    stops = data["hooks"]["stop"]
    assert sum("gaudi_session_start" in str(x.get("command", "")) for x in starts) == 1
    assert sum("gaudi_stop" in str(x.get("command", "")) for x in stops) == 1
    assert any("noop.py" in str(x.get("command", "")) for x in starts)
    assert any(x.get("prompt") == "keep me" for x in stops)
    assert "gaudi_ledger" not in json.dumps(data)
    assert (git_repo / RULE_REL).is_file()
    rule = (git_repo / RULE_REL).read_text(encoding="utf-8")
    n = len(rule.splitlines())
    assert 15 <= n <= 25, n
    gi = (git_repo / ".gitignore").read_text(encoding="utf-8")
    assert gi.count(GITIGNORE_LINE) == 1
    assert gi.count(".gaudi/") == 1
    di = (git_repo / ".dockerignore").read_text(encoding="utf-8")
    assert di.count(".map") == 1
    assert di.count(".gaudi/") == 1
    assert (git_repo / MAP_REL).is_file()
    check_ship(git_repo)


def test_check_ship_fails_when_dist_contains_map(git_repo) -> None:
    install(git_repo, python_cmd="python")
    planted = git_repo / "dist" / ".map"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("leaked\n", encoding="utf-8")
    with pytest.raises(ShipError, match="dist"):
        check_ship(git_repo)
    assert run_cli(git_repo, "check-ship") == 1


def test_check_ship_fails_without_dockerignore(tmp_path: Path, git_repo) -> None:
    generate(git_repo)
    (git_repo / ".dockerignore").unlink(missing_ok=True)
    with pytest.raises(ShipError, match="dockerignore"):
        check_ship(git_repo)


def test_check_ship_allows_non_root_map_negation(git_repo) -> None:
    (git_repo / ".dockerignore").write_text(".map\n.gaudi/\n!src/**/*.map\n", encoding="utf-8")
    check_ship(git_repo)


def test_session_start_two_lines_no_bodies(git_repo) -> None:
    generate(git_repo)
    out = handle_session_start({"workspace_roots": [str(git_repo)]})
    ctx = out["additional_context"]
    assert "Gaudi map:" in ctx
    assert "def foo" not in ctx
    assert "def helper" not in ctx
    assert "def bar" not in ctx
    assert MAP_REL.as_posix() in ctx
    assert ctx.count("\n") <= 3


def test_hook_cli_session_start_json(git_repo, capsys) -> None:
    generate(git_repo)
    payload = json.dumps({"workspace_roots": [str(git_repo)]})
    import io
    import sys

    sys.stdin = io.StringIO(payload)
    try:
        code = main(["--root", str(git_repo), "hook-session-start"])
    finally:
        sys.stdin = sys.__stdin__
    assert code == 0
    dumped = json.loads(capsys.readouterr().out)
    assert "additional_context" in dumped
    assert "def foo" not in dumped["additional_context"]


def test_stop_regenerates_when_stale(git_repo) -> None:
    generate(git_repo)
    (git_repo / "a.py").write_text(
        (git_repo / "a.py").read_text(encoding="utf-8") + "\n\ndef after_stop():\n    return 9\n",
        encoding="utf-8",
    )
    commit_all(git_repo, "stale")
    handle_stop({"workspace_roots": [str(git_repo)]})
    assert "after_stop" in map_text(git_repo)


def test_merge_hooks_detects_py_dash_three() -> None:
    merged = merge_hooks_json({}, "py -3")
    cmd = merged["hooks"]["sessionStart"][0]["command"]
    assert cmd.startswith("py -3 ")


def test_install_copilot_instructions_and_targets(git_repo) -> None:
    from gaudi.paths import CACHE_REL, COPILOT_INSTRUCTIONS_REL, COPILOT_SKILL_REL, MAP_REL, RULE_REL

    # Target: copilot only
    install(git_repo, python_cmd="python", target="copilot")
    assert (git_repo / COPILOT_INSTRUCTIONS_REL).is_file()
    text = (git_repo / COPILOT_INSTRUCTIONS_REL).read_text(encoding="utf-8")
    assert "## Gaudi Map" in text
    skill = (git_repo / COPILOT_SKILL_REL).read_text(encoding="utf-8")
    assert "name: gaudi" in skill
    assert "gaudi status" in skill
    assert "gaudi generate" in skill
    assert not (git_repo / RULE_REL).exists()
    assert not (git_repo / MAP_REL).exists()
    assert not (git_repo / CACHE_REL).exists()

    # Target: all (idempotent, adds cursor rule without duplicating copilot section)
    install(git_repo, python_cmd="python", target="all")
    assert (git_repo / RULE_REL).is_file()
    text2 = (git_repo / COPILOT_INSTRUCTIONS_REL).read_text(encoding="utf-8")
    assert text2.count("## Gaudi Map") == 1


def test_install_all_creates_claude_and_agents(git_repo) -> None:
    install(git_repo, python_cmd="python", target="all")
    for rel in (CLAUDE_MD_REL, AGENTS_MD_REL):
        path = git_repo / rel
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "## Gaudi Map" in text
        assert "gaudi index" in text


def test_install_skips_existing_claude_without_yes(git_repo, monkeypatch) -> None:
    claude = git_repo / CLAUDE_MD_REL
    original = "# Custom project notes\n"
    claude.write_text(original, encoding="utf-8")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    install(git_repo, python_cmd="python", target="all")
    assert claude.read_text(encoding="utf-8") == original


def test_install_yes_appends_claude_once(git_repo) -> None:
    claude = git_repo / CLAUDE_MD_REL
    claude.write_text("# Custom project notes\n", encoding="utf-8")
    install(git_repo, python_cmd="python", target="claude", yes=True)
    text = claude.read_text(encoding="utf-8")
    assert text.startswith("# Custom project notes")
    assert text.count("## Gaudi Map") == 1
    install(git_repo, python_cmd="python", target="claude", yes=True)
    assert claude.read_text(encoding="utf-8").count("## Gaudi Map") == 1


def test_install_confirm_callback(git_repo) -> None:
    claude = git_repo / CLAUDE_MD_REL
    original = "# Custom project notes\n"
    claude.write_text(original, encoding="utf-8")
    prompts: list[str] = []

    def refuse(prompt: str) -> bool:
        prompts.append(prompt)
        return False

    install(git_repo, python_cmd="python", target="claude", confirm=refuse)
    assert claude.read_text(encoding="utf-8") == original
    assert prompts == ["CLAUDE.md already exists. Append Gaudi instructions? [y/N] "]

    def accept(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    install(git_repo, python_cmd="python", target="claude", confirm=accept)
    text = claude.read_text(encoding="utf-8")
    assert text.startswith("# Custom project notes")
    assert text.count("## Gaudi Map") == 1
    assert prompts[-1] == "CLAUDE.md already exists. Append Gaudi instructions? [y/N] "


def test_cli_install_yes_and_target(git_repo) -> None:
    claude = git_repo / CLAUDE_MD_REL
    claude.write_text("# Custom project notes\n", encoding="utf-8")
    assert run_cli(git_repo, "install", "--target", "claude", "--yes") == 0
    assert claude.read_text(encoding="utf-8").count("## Gaudi Map") == 1
    assert not (git_repo / AGENTS_MD_REL).exists()
    assert not (git_repo / RULE_REL).exists()


def test_install_with_ledger_cursor_copilot_claude_agents(git_repo) -> None:
    install(git_repo, python_cmd="python", target="cursor", with_ledger=True)
    hooks = json.loads((git_repo / HOOKS_JSON_REL).read_text(encoding="utf-8"))
    blob = json.dumps(hooks)
    assert blob.count("gaudi_ledger") >= 1
    assert "beforeReadFile" in hooks["hooks"]
    assert (git_repo / ".cursor" / "hooks" / "gaudi_ledger.py").is_file()
    rule = (git_repo / RULE_REL).read_text(encoding="utf-8")
    assert 15 <= len(rule.splitlines()) <= 25
    assert "gaudi stats" not in rule.lower()

    install(git_repo, python_cmd="python", target="copilot", with_ledger=True, yes=True)
    copilot = git_repo / ".github" / "hooks" / "gaudi-ledger.json"
    assert copilot.is_file()
    copilot_data = json.loads(copilot.read_text(encoding="utf-8"))
    assert "PreToolUse" in copilot_data["hooks"]
    assert (git_repo / ".github" / "hooks" / "gaudi_ledger.py").is_file()
    instructions = (git_repo / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    skill = (git_repo / ".github" / "skills" / "gaudi" / "SKILL.md").read_text(encoding="utf-8")
    assert "gaudi stats" not in instructions.lower()
    assert "gaudi stats" not in skill.lower()

    settings = git_repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Bash(*)"]}, "hooks": {}}) + "\n",
        encoding="utf-8",
    )
    install(git_repo, python_cmd="python", target="claude", with_ledger=True, yes=True)
    claude = json.loads(settings.read_text(encoding="utf-8"))
    assert claude["permissions"] == {"allow": ["Bash(*)"]}
    assert "Read" in json.dumps(claude["hooks"]["PreToolUse"])
    assert (git_repo / ".claude" / "hooks" / "gaudi_ledger.py").is_file()
    claude_md = (git_repo / CLAUDE_MD_REL).read_text(encoding="utf-8")
    assert "gaudi stats" not in claude_md.lower()


def test_install_with_ledger_agents_has_no_hooks(git_repo) -> None:
    install(git_repo, python_cmd="python", target="agents", with_ledger=True, yes=True)
    agents = (git_repo / AGENTS_MD_REL).read_text(encoding="utf-8")
    assert "## Gaudi Map" in agents
    assert "gaudi stats" not in agents.lower()
    assert not (git_repo / ".cursor" / "hooks" / "gaudi_ledger.py").exists()
    assert not (git_repo / ".github" / "hooks" / "gaudi-ledger.json").exists()
    assert not (git_repo / ".claude" / "settings.json").exists()


def test_install_with_ledger_idempotent(git_repo) -> None:
    install(git_repo, python_cmd="python", target="all", with_ledger=True, yes=True)
    install(git_repo, python_cmd="python", target="all", with_ledger=True, yes=True)
    hooks = json.loads((git_repo / HOOKS_JSON_REL).read_text(encoding="utf-8"))
    starts = hooks["hooks"]["sessionStart"]
    assert sum("gaudi_ledger" in str(x.get("command", "")) for x in starts) == 1
    copilot = json.loads(
        (git_repo / ".github" / "hooks" / "gaudi-ledger.json").read_text(encoding="utf-8")
    )
    assert sum("gaudi_ledger" in json.dumps(x) for x in copilot["hooks"]["PreToolUse"]) == 1
    claude = json.loads((git_repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert json.dumps(claude["hooks"]["PreToolUse"]).count("gaudi_ledger") == 1


def test_cli_install_with_ledger_flag(git_repo) -> None:
    assert run_cli(git_repo, "install", "--target", "cursor", "--with-ledger") == 0
    hooks = json.loads((git_repo / HOOKS_JSON_REL).read_text(encoding="utf-8"))
    assert "gaudi_ledger" in json.dumps(hooks)

