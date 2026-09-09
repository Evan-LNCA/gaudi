from __future__ import annotations

from gaudi.extract import TreeSitterParsers, extract_file
from gaudi.gitutil import GitRepo
from gaudi.mapgen import collect_tags, generate
from gaudi.rank import pagerank_defs

from tests.support import commit_all, git, map_text


def test_foo_outranks_unreferenced_helper(git_repo) -> None:
    parsers = TreeSitterParsers()
    a = (git_repo / "a.py").read_bytes()
    b = (git_repo / "b.py").read_bytes()
    tags = [
        extract_file("a.py", a, "python", parsers),
        extract_file("b.py", b, "python", parsers),
    ]
    scores = pagerank_defs(tags)
    foo = next(d for t in tags for d in t.defs if d.name == "foo")
    helper = next(d for t in tags for d in t.defs if d.name == "helper")
    assert scores[foo.key] > scores[helper.key]


def test_generate_lists_foo_before_dropping_helper_on_tiny_budget(git_repo) -> None:
    generate(git_repo, map_tokens=40)
    text = map_text(git_repo)
    assert "def foo" in text
    foo_at = text.find("foo")
    helper_at = text.find("helper")
    if helper_at != -1:
        assert foo_at < helper_at


def test_collect_tags_skips_venv(git_repo) -> None:
    venv = git_repo / ".venv"
    venv.mkdir()
    (venv / "noise.py").write_text("def should_not_appear():\n    return 0\n", encoding="utf-8")
    git(git_repo, "add", "-f", ".venv/noise.py")
    commit_all(git_repo, "track venv by mistake")
    tags, _ = collect_tags(git_repo, GitRepo(git_repo))
    names = {d.name for t in tags for d in t.defs}
    assert "should_not_appear" not in names
