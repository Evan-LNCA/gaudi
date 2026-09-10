from __future__ import annotations

from pathlib import Path

import pytest

from gaudi.cli import main
from gaudi.errors import GaudiError
from gaudi.gitutil import GitRepo
from gaudi.mapgen import generate, HEADER_MARK, status_code
from gaudi.paths import CONFIG_REL, MAP_REL

from tests.support import commit_all, git, init_repo, map_body, map_text, run_cli


def test_generate_writes_sha_header(git_repo) -> None:
    generate(git_repo)
    text = map_text(git_repo)
    head = GitRepo(git_repo).head_sha()
    assert HEADER_MARK in text
    assert f"head: {head}" in text
    assert "dirty: false" in text
    cfg = (git_repo / CONFIG_REL).read_text(encoding="utf-8")
    assert "2048" in cfg


def test_status_flips_after_commit_adds_function(git_repo) -> None:
    assert run_cli(git_repo, "generate") == 0
    assert run_cli(git_repo, "status") == 0
    (git_repo / "a.py").write_text(
        (git_repo / "a.py").read_text(encoding="utf-8") + "\n\ndef extra():\n    return 3\n",
        encoding="utf-8",
    )
    commit_all(git_repo, "add extra")
    assert run_cli(git_repo, "status") == 1
    assert run_cli(git_repo, "generate") == 0
    assert "def extra" in map_text(git_repo)
    assert run_cli(git_repo, "status") == 0


def test_comment_only_edit_keeps_signature_body(git_repo) -> None:
    generate(git_repo)
    before = map_body(map_text(git_repo))
    src = (git_repo / "a.py").read_text(encoding="utf-8")
    (git_repo / "a.py").write_text(src.replace("return 1", "return 1  # noise"), encoding="utf-8")
    generate(git_repo)
    after = map_body(map_text(git_repo))
    assert after == before
    assert "def foo" in after


def test_signature_change_updates_map(git_repo) -> None:
    generate(git_repo)
    before = map_body(map_text(git_repo))
    src = (git_repo / "a.py").read_text(encoding="utf-8")
    (git_repo / "a.py").write_text(src.replace("def foo():", "def foo(x):"), encoding="utf-8")
    generate(git_repo)
    after = map_body(map_text(git_repo))
    assert after != before
    assert "def foo(x):" in after


def test_token_cap_stays_near_budget(git_repo) -> None:
    generate(git_repo, map_tokens=32)
    raw = map_text(git_repo)
    approx = len(raw) / 4
    assert approx < 32 * 3
    assert "GENERATED" in raw


def test_unicode_ellipsis_utf8(git_repo) -> None:
    generate(git_repo, map_tokens=2048)
    data = (git_repo / MAP_REL).read_bytes()
    text = data.decode("utf-8")
    assert "⋮" in text
    assert b"\xe2\x8b\xae" in data


def test_js_and_ts_defs(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "js")
    (repo / "lib.js").write_text("export function alpha() {\n  return 1;\n}\n", encoding="utf-8")
    (repo / "lib.ts").write_text(
        "export function beta(x: number): number {\n  return x;\n}\n",
        encoding="utf-8",
    )
    (repo / "use.js").write_text("import { alpha } from './lib.js';\nalpha();\n", encoding="utf-8")
    commit_all(repo, "js ts")
    generate(repo)
    text = map_text(repo)
    assert "alpha" in text
    assert "beta" in text


def test_missing_git_nonzero(tmp_path: Path) -> None:
    bare = tmp_path / "notgit"
    bare.mkdir()
    with pytest.raises(GaudiError, match="Not a git repository"):
        generate(bare)
    assert main(["--root", str(bare), "generate"]) == 2


def test_empty_tree_writes_map_no_crash(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "empty")
    git(repo, "commit", "--allow-empty", "-m", "empty")
    dest = generate(repo)
    text = dest.read_text(encoding="utf-8")
    assert HEADER_MARK in text
    assert "empty" in text.lower()
    assert status_code(repo) == 0


def test_generate_creates_dot_map_at_root(git_repo) -> None:
    dest = generate(git_repo)
    assert dest == git_repo / ".map"
    assert (git_repo / ".map").is_file()
    assert (git_repo / ".gaudi" / "config.json").is_file()
    assert (git_repo / ".gaudi" / "cache" / "tags.json").is_file()


def test_generate_automatically_updates_all_ignore_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "fresh")
    (repo / "index.js").write_text("function main() {}\n", encoding="utf-8")
    commit_all(repo, "initial")

    # Pre-populate an existing .npmignore and .cursorignore, but no .gitignore or .dockerignore yet
    (repo / ".npmignore").write_text("build/\n", encoding="utf-8")
    (repo / ".cursorignore").write_text("secrets.txt\n", encoding="utf-8")

    assert not (repo / ".gitignore").exists()
    assert not (repo / ".dockerignore").exists()

    generate(repo)

    gi = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".map" in gi
    assert ".gaudi/" in gi

    di = (repo / ".dockerignore").read_text(encoding="utf-8")
    assert ".map" in di
    assert ".gaudi/" in di

    ni = (repo / ".npmignore").read_text(encoding="utf-8")
    assert "build/" in ni
    assert ".map" in ni
    assert ".gaudi/" in ni

    ci = (repo / ".cursorignore").read_text(encoding="utf-8")
    assert ".map" not in ci
