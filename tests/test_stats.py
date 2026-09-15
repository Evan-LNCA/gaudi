from __future__ import annotations

import json
from pathlib import Path

from gaudi.cli import main
from gaudi.install import install
from gaudi.ledger import Ledger

from tests.support import run_cli


def test_stats_empty_and_json(git_repo: Path, capsys) -> None:
    assert run_cli(git_repo, "stats") == 0
    out = capsys.readouterr().out
    assert "chars/4" in out
    assert "MEASURED" in out
    assert "Not measurable locally" in out
    assert run_cli(git_repo, "stats", "--format", "json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert "measured" in payload["tier"]
    assert "attributed" in payload["tier"]
    assert "not_measurable" in payload["tier"]


def test_stats_ab_refuses_without_sessions(git_repo: Path, capsys) -> None:
    assert run_cli(git_repo, "stats", "--ab") == 0
    out = capsys.readouterr().out
    assert "min_sessions" in out
    assert run_cli(git_repo, "stats", "--ab", "--format", "json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["min_sessions"] == 10
    assert payload["overall"] is None


def test_stats_ab_json_with_seeded_sessions(git_repo: Path, capsys) -> None:
    led = Ledger(git_repo)
    try:
        for i in range(10):
            led.record_session_start(f"on-{i}", "cursor", "on")
            led.record_read(f"on-{i}", "a.py", "h-on", 10, 1, True)
            led.record_session_start(f"off-{i}", "cursor", "off")
            led.record_read(f"off-{i}", "a.py", "h-off", 40, 1, True)
        led.save()
    finally:
        led.close()
    assert main(["--root", str(git_repo), "stats", "--ab", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    cursor = payload["harnesses"][0]
    assert cursor["refused"] is False
    assert cursor["verdict"] == "on"


def test_default_install_unchanged_without_ledger(git_repo: Path) -> None:
    install(git_repo, python_cmd="python")
    hooks = json.loads((git_repo / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    blob = json.dumps(hooks)
    assert "gaudi_ledger" not in blob
    assert "gaudi_session_start" in blob
    assert not (git_repo / ".cursor" / "hooks" / "gaudi_ledger.py").exists()
    assert not (git_repo / ".github" / "hooks" / "gaudi-ledger.json").exists()
    assert not (git_repo / ".claude" / "settings.json").exists()
