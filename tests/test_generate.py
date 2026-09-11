from __future__ import annotations

import os
from pathlib import Path

import pytest

from gaudi.cli import main
from gaudi.gitutil import GitRepo
from gaudi.mapgen import generate, HEADER_MARK, status_code
from gaudi.paths import CACHE_FILE, CONFIG_REL, MAP_REL, token_count

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


def test_missing_git_succeeds(tmp_path: Path) -> None:
    bare = tmp_path / "notgit"
    bare.mkdir()
    (bare / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    result = generate(bare)
    text = result.path.read_text(encoding="utf-8")
    assert HEADER_MARK in text
    assert "head: NOGIT" in text
    assert "def foo" in text
    assert main(["--root", str(bare), "generate"]) == 0


def test_empty_tree_writes_map_no_crash(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "empty")
    git(repo, "commit", "--allow-empty", "-m", "empty")
    dest = generate(repo)
    text = dest.text
    assert HEADER_MARK in text
    assert "empty" in text.lower()
    assert status_code(repo) == 0


def test_generate_creates_dot_map_at_root(git_repo) -> None:
    dest = generate(git_repo)
    assert dest.path == git_repo / ".map"
    assert (git_repo / ".map").is_file()
    assert (git_repo / ".gaudi" / "config.json").is_file()
    assert (git_repo / CACHE_FILE).is_file()


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


def test_untracked_not_ignored_file_appears(git_repo) -> None:
    (git_repo / "fresh_untracked.py").write_text(
        "def untracked_symbol():\n    return 0\n",
        encoding="utf-8",
    )
    generate(git_repo)
    assert "untracked_symbol" in map_text(git_repo)


def test_readme_edit_does_not_stale_map(git_repo) -> None:
    generate(git_repo)
    assert status_code(git_repo) == 0
    (git_repo / "README.md").write_text("notes only\n", encoding="utf-8")
    assert status_code(git_repo) == 0


def test_status_does_not_write_cache(git_repo) -> None:
    generate(git_repo)
    cache = git_repo / CACHE_FILE
    os.utime(cache, (1_700_000_000, 1_700_000_000))
    assert status_code(git_repo) == 0
    assert cache.stat().st_mtime == 1_700_000_000


def test_cache_prunes_dead_hashes(git_repo) -> None:
    from gaudi.cache import TagCache
    from gaudi.extract import FileTags

    generate(git_repo)
    cache = TagCache(git_repo)
    dead = "ab" * 32
    cache.put(dead, FileTags(path="gone.py"))
    cache.save()
    assert dead in cache.hashes()
    cache.close()
    generate(git_repo)
    cache2 = TagCache(git_repo, readonly=True)
    try:
        assert dead not in cache2.hashes()
    finally:
        cache2.close()


def test_warns_on_star_map_ignore(git_repo, capsys) -> None:
    gi = git_repo / ".gitignore"
    gi.write_text(gi.read_text(encoding="utf-8") + "*.map\n", encoding="utf-8")
    generate(git_repo)
    err = capsys.readouterr().err
    assert "*.map" in err
    generate(git_repo, quiet=True)
    err_quiet = capsys.readouterr().err
    assert "*.map" not in err_quiet


def test_generate_summary_and_quiet(git_repo, capsys) -> None:
    assert run_cli(git_repo, "generate") == 0
    out = capsys.readouterr().out
    assert "wrote .map:" in out
    assert "files" in out
    assert "defs" in out
    assert "tokens" in out
    assert run_cli(git_repo, "--quiet", "generate") == 0
    assert capsys.readouterr().out.strip() == ""


def test_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_token_accounting_includes_elision(git_repo) -> None:
    result = generate(git_repo, map_tokens=24)
    text = result.text
    assert "⋮" in text
    counted = token_count(text)
    assert counted == result.tokens
    assert counted <= 24 * 3
    assert "more defs" in text or "showing" in text


def test_deep_nesting_does_not_recursion_error(tmp_path: Path) -> None:
    from gaudi.extract import TreeSitterParsers, extract_file

    repo = init_repo(tmp_path / "deep")
    depth = 1200
    inner = "return 1;"
    for i in range(depth, 0, -1):
        inner = f"function d{i}() {{\n{inner}\n}}"
    source = f"{inner}\n"
    (repo / "deep.js").write_text(source, encoding="utf-8")
    commit_all(repo, "deep")
    parsers = TreeSitterParsers()
    tags = extract_file("deep.js", source.encode("utf-8"), "javascript", parsers)
    names = {d.name for d in tags.defs}
    assert "d1" in names
    assert "d1200" in names
    generate(repo)
    assert "d1" in map_text(repo)
