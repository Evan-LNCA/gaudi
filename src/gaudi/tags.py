from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from collections.abc import Callable
from typing import Any

from gaudi.extract import _first_line, _text

try:
    from tree_sitter_language_pack import get_tags_query as _imported_get_tags_query
except ImportError:
    _pack_get_tags_query: Callable[[str], str | None] | None = None
else:
    _pack_get_tags_query = _imported_get_tags_query


@dataclass(frozen=True)
class QueryTag:
    kind: str  # "def" or "ref"
    name: str
    capture: str
    line: int
    signature: str
    name_span: tuple[int, int]


def _probe_get_tags_query() -> bool:
    return _pack_get_tags_query is not None


_HAS_PACK_TAGS_QUERY = _probe_get_tags_query()


class TagQueryEngine:
    """Compiles bundled tags.scm per language. Cached."""

    def __init__(self) -> None:
        self._queries: dict[str, Any] = {}

    def matches(self, tree: Any, language: str, source: bytes) -> list[QueryTag]:
        query = self._query(language)
        if query is None:
            return []
        from tree_sitter import QueryCursor

        cursor = QueryCursor(query)
        root = tree.root_node
        out: list[QueryTag] = []
        for _pattern, caps in cursor.matches(root):
            tag = _tag_from_match(caps, source)
            if tag is not None:
                out.append(tag)
        return out

    def _query(self, language: str) -> Any | None:
        if language in self._queries:
            return self._queries[language]
        compiled = self._compile(language)
        self._queries[language] = compiled
        return compiled

    def _compile(self, language: str) -> Any | None:
        from tree_sitter import Query
        from tree_sitter_language_pack import get_language

        try:
            lang_obj = get_language(language)
        except Exception:
            return None
        for src in (self._pack_source(language), _vendor_query(language)):
            if not src:
                continue
            try:
                return Query(lang_obj, src)
            except Exception:
                continue
        return None

    def _pack_source(self, language: str) -> str | None:
        if not _HAS_PACK_TAGS_QUERY or _pack_get_tags_query is None:
            return None
        try:
            src = _pack_get_tags_query(language)
        except Exception:
            return None
        if not src:
            return None
        return str(src)


def _vendor_query(language: str) -> str | None:
    try:
        path = resources.files("gaudi.assets").joinpath("queries", f"{language}.scm")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return None
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _as_nodes(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _tag_from_match(caps: dict[str, Any], source: bytes) -> QueryTag | None:
    name_nodes: list[Any] = []
    def_nodes: list[Any] = []
    ref_nodes: list[Any] = []
    def_capture = ""
    ref_capture = ""
    for key, raw in caps.items():
        nodes = _as_nodes(raw)
        if key == "name" or key.startswith("name."):
            name_nodes.extend(nodes)
        if key.startswith("definition"):
            def_nodes.extend(nodes)
            def_capture = key
        if "reference" in key:
            ref_nodes.extend(nodes)
            ref_capture = key
    if def_nodes:
        def_node = def_nodes[0]
        name_node = name_nodes[0] if name_nodes else def_node
        name = _text(source, name_node).strip()
        if not name:
            return None
        return QueryTag(
            kind="def",
            name=name,
            capture=def_capture or "definition",
            line=def_node.start_point[0] + 1,
            signature=_first_line(source, def_node),
            name_span=(name_node.start_byte, name_node.end_byte),
        )
    if ref_nodes or (name_nodes and ref_capture):
        node = name_nodes[0] if name_nodes else ref_nodes[0]
        name = _text(source, node).strip()
        if not name:
            return None
        return QueryTag(
            kind="ref",
            name=name,
            capture=ref_capture or "reference",
            line=node.start_point[0] + 1,
            signature=name,
            name_span=(node.start_byte, node.end_byte),
        )
    return None
