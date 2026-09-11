from __future__ import annotations

import json
from pathlib import Path

from gaudi.mapgen import generate
from gaudi.paths import CACHE_FILE, token_count
from gaudi.query import run_focus, run_index, run_where

from tests.support import commit_all, init_repo, map_text, run_cli


def test_focus_determinism_and_smaller_than_map(git_repo) -> None:
    generate(git_repo, map_tokens=2048)
    full = map_text(git_repo)
    first = run_focus(git_repo, ["foo"], tokens=64)
    second = run_focus(git_repo, ["foo"], tokens=64)
    assert first.text == second.text
    assert "fresh: true" in first.text
    assert "focus: foo" in first.text
    assert token_count(first.text) < token_count(full)
    assert len(first.text) < len(full)


def test_focus_json_and_where_index(git_repo) -> None:
    generate(git_repo)
    focused = run_focus(git_repo, ["b.py"], tokens=128, fmt="json")
    payload = json.loads(focused.text)
    assert payload["fresh"] is True
    assert payload["focus"] == ["b.py"]
    assert payload["tokens"] > 0
    where = run_where(git_repo, "foo")
    assert "a.py:" in where.text
    assert "def foo" in where.text
    assert "fresh:" in where.text
    idx = run_index(git_repo, tokens=250)
    assert "hubs:" in idx.text
    assert "dirs:" in idx.text
    assert "fresh: true" in idx.text
    assert run_cli(git_repo, "where", "foo") == 0
    assert run_cli(git_repo, "index", "--format", "json") == 0
    assert run_cli(git_repo, "focus", "foo", "--tokens", "64") == 0


def test_focus_reports_stale_after_source_edit(git_repo) -> None:
    generate(git_repo)
    (git_repo / "a.py").write_text(
        (git_repo / "a.py").read_text(encoding="utf-8") + "\n\ndef extra_focus():\n    return 1\n",
        encoding="utf-8",
    )
    out = run_focus(git_repo, ["foo"], tokens=128)
    assert "fresh: false" in out.text
    assert out.payload["fresh"] is False
    assert "extra_focus" in out.text


def test_query_commands_do_not_create_cache(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "queries-no-cache")
    (repo / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    assert not (repo / CACHE_FILE).exists()
    out = run_focus(repo, ["foo"], tokens=64)
    assert "focus: foo" in out.text
    assert not (repo / CACHE_FILE).exists()
    out = run_where(repo, "foo")
    assert "def foo" in out.text
    assert not (repo / CACHE_FILE).exists()
    out = run_index(repo, tokens=128)
    assert "hubs:" in out.text
    assert not (repo / CACHE_FILE).exists()


def test_focus_prioritizes_direct_seed_path(git_repo) -> None:
    out = run_focus(git_repo, ["b.py"], tokens=64)
    body = out.text.split("\n\n", 1)[1]
    assert body.startswith("b.py:\n")


def test_focus_path_seed_does_not_match_sibling_prefixes(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "focus-prefix")
    (repo / ".gitignore").write_text(".map\n.gaudi/\n", encoding="utf-8")
    (repo / ".dockerignore").write_text(".map\n.gaudi/\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def wanted():\n    return 1\n", encoding="utf-8")
    (repo / "src" / "application.py").write_text("def sibling():\n    return 2\n", encoding="utf-8")
    commit_all(repo, "init")
    out = run_focus(repo, ["src/app"], tokens=64)
    body = out.text.split("\n\n", 1)[1]
    assert body.startswith("src/app.py:\n")
    assert "src/application.py:" not in body
