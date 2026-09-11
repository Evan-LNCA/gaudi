from __future__ import annotations

from pathlib import Path

from gaudi.extract import TreeSitterParsers, extract_file, language_for_path
from gaudi.mapgen import generate
from gaudi.paths import SOURCE_SUFFIXES
from gaudi.tags import _HAS_PACK_TAGS_QUERY, _vendor_query, TagQueryEngine

from tests.support import commit_all, init_repo, map_text

# One small snippet per language: (relative path, source, expected def names)
_GOLDENS: list[tuple[str, str, tuple[str, ...]]] = [
    ("mod.py", "def alpha():\n    return 1\n", ("alpha",)),
    ("mod.js", "export function beta() {\n  return 1;\n}\n", ("beta",)),
    ("mod.ts", "export function gamma(): number {\n  return 1;\n}\n", ("gamma",)),
    ("mod.tsx", "export function GammaView(): JSX.Element {\n  return <div />;\n}\n", ("GammaView",)),
    ("mod.go", "package main\n\nfunc Delta() int {\n\treturn 1\n}\n", ("Delta",)),
    ("mod.rs", "pub fn epsilon() -> i32 {\n    1\n}\n", ("epsilon",)),
    (
        "Mod.java",
        "class Zeta {\n  int eta() {\n    return 1;\n  }\n}\n",
        ("Zeta", "eta"),
    ),
    ("mod.rb", "def theta\n  1\nend\n", ("theta",)),
    ("mod.c", "int iota(void) {\n  return 1;\n}\n", ("iota",)),
]


def test_vendor_queries_cover_source_languages() -> None:
    langs = set(SOURCE_SUFFIXES.values())
    missing = [lang for lang in sorted(langs) if _vendor_query(lang) is None]
    assert missing == [], f"missing vendored tags.scm: {missing}"


def test_pack_tags_query_probe_or_vendor_fallback() -> None:
    engine = TagQueryEngine()
    src = engine._pack_source("python") or _vendor_query("python")
    assert src is not None
    assert "@definition" in src or "@name" in src
    if _HAS_PACK_TAGS_QUERY:
        pack = engine._pack_source("python")
        assert pack is None or "definition" in pack or "name" in pack


def test_golden_maps_for_eight_languages(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "langs")
    parsers = TreeSitterParsers()
    for rel, source, expected in _GOLDENS:
        (repo / rel).write_text(source, encoding="utf-8")
        lang = language_for_path(rel)
        assert lang is not None, rel
        tags = extract_file(rel, source.encode("utf-8"), lang, parsers)
        names = {d.name for d in tags.defs}
        missing = [name for name in expected if name not in names]
        assert not missing, f"{rel} ({lang}) missing {missing}; got {sorted(names)}"
    commit_all(repo, "langs")
    generate(repo)
    text = map_text(repo)
    for _rel, _source, expected in _GOLDENS:
        for name in expected:
            assert name in text, f"{name} missing from generated map"
