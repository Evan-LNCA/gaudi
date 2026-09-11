from __future__ import annotations

import json
from pathlib import Path

import pytest

from gaudi.cli import main
from gaudi.hooks import handle_session_start, handle_stop
from gaudi.install import install, merge_hooks_json
from gaudi.mapgen import generate
from gaudi.paths import HOOKS_JSON_REL, MAP_REL, RULE_REL
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
