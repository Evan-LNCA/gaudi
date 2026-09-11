from __future__ import annotations

from gaudi.extract import DefTag, FileTags, TreeSitterParsers, extract_file
from gaudi.gitutil import GitRepo
from gaudi.mapgen import collect_tags, generate
from gaudi.rank import pagerank_defs, pagerank_files, personalization_from_seeds

from tests.support import commit_all, git, map_text


def _ft(path: str, defs: list[str], refs: list[str]) -> FileTags:
    tags = FileTags(path=path, refs=list(refs))
    for i, name in enumerate(defs, start=1):
        tags.defs.append(DefTag(path, name, "function", i, f"def {name}():"))
    return tags


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


def test_rank_is_transitive() -> None:
    files = [
        _ft("a.py", ["A"], ["B"]),
        _ft("b.py", ["B"], ["C"]),
        _ft("c.py", ["C"], []),
        _ft("d.py", ["D"], []),
    ]
    scores = pagerank_files(files)
    assert scores["c.py"] > scores["d.py"]
    assert scores["b.py"] > scores["d.py"]


def test_personalization_boosts_seed() -> None:
    files = [
        _ft("hub.py", ["Hub"], []),
        _ft("seed.py", ["Seed"], ["Hub"]),
        _ft("other.py", ["Other"], []),
    ]
    uniform = pagerank_files(files)
    perso = personalization_from_seeds(files, ["seed.py"])
    boosted = pagerank_files(files, personalization=perso)
    assert boosted["seed.py"] > uniform["seed.py"]
    assert boosted["seed.py"] > boosted["other.py"]
    symbol = personalization_from_seeds(files, ["Seed"])
    assert symbol["seed.py"] > 0


def test_def_rank_follows_inbound_share() -> None:
    files = [
        _ft("lib.py", ["hot", "cold"], []),
        _ft("a.py", ["A"], ["hot"]),
        _ft("b.py", ["B"], ["hot"]),
    ]
    scores = pagerank_defs(files)
    hot = next(d for t in files for d in t.defs if d.name == "hot")
    cold = next(d for t in files for d in t.defs if d.name == "cold")
    assert scores[hot.key] > scores[cold.key]


def test_common_ident_is_discounted() -> None:
    files = [
        _ft("a.py", ["get"], ["rare"]),
        _ft("b.py", ["get"], ["rare"]),
        _ft("c.py", ["get"], []),
        _ft("d.py", ["rare"], []),
    ]
    graph_scores = pagerank_files(files)
    assert graph_scores["d.py"] > graph_scores["c.py"]
