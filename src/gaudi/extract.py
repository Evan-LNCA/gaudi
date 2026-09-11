from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from gaudi.paths import SOURCE_SUFFIXES

_IDENT_TYPES = {
    "identifier",
    "property_identifier",
    "type_identifier",
    "field_identifier",
    "shorthand_property_identifier",
}

_JS_LANGS = {"javascript", "typescript", "tsx"}

_WORKER_PARSERS: TreeSitterParsers | None = None
_SHARED_ENGINE: object | None = None


class ParserPort(Protocol):
    def parse(self, source: bytes, language: str) -> Any | None:
        """Return a tree with .root_node, or None if language unavailable."""


@dataclass(frozen=True)
class DefTag:
    path: str
    name: str
    kind: str
    line: int
    signature: str

    @property
    def key(self) -> str:
        return f"{self.path}::{self.name}@{self.line}"


@dataclass
class FileTags:
    path: str
    defs: list[DefTag] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)


_DEF_TYPES = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
    },
    "typescript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "tsx": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_spec": "type",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "mod_item": "mod",
        "type_item": "type",
        "macro_definition": "macro",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "method_declaration": "method",
        "enum_declaration": "enum",
        "record_declaration": "class",
        "constructor_declaration": "method",
    },
    "csharp": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "method_declaration": "method",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "record_declaration": "class",
        "constructor_declaration": "method",
    },
    "c": {
        "function_definition": "function",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "type_definition": "type",
    },
    "cpp": {
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
    },
    "ruby": {
        "method": "method",
        "class": "class",
        "module": "module",
        "singleton_method": "method",
    },
    "php": {
        "function_definition": "function",
        "class_declaration": "class",
        "method_declaration": "method",
        "interface_declaration": "interface",
    },
    "swift": {
        "function_declaration": "function",
        "class_declaration": "class",
        "protocol_declaration": "protocol",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
    },
    "kotlin": {
        "function_declaration": "function",
        "class_declaration": "class",
        "object_declaration": "object",
    },
    "scala": {
        "function_definition": "function",
        "class_definition": "class",
        "object_definition": "object",
        "trait_definition": "trait",
    },
    "lua": {
        "function_declaration": "function",
        "function_definition": "function",
    },
    "bash": {
        "function_definition": "function",
    },
}


class TreeSitterParsers:
    """Loads parsers via tree-sitter-language-pack. Cached per language."""

    def __init__(self) -> None:
        self._parsers: dict[str, Any] = {}

    def parse(self, source: bytes, language: str) -> Any | None:
        parser = self._get(language)
        if parser is None:
            return None
        return parser.parse(source)

    def _get(self, language: str) -> Any | None:
        if language in self._parsers:
            return self._parsers[language]
        from tree_sitter_language_pack import get_parser

        try:
            parser = get_parser(language)
        except Exception as exc:
            raise RuntimeError(f"Failed to load tree-sitter parser for {language!r}") from exc
        self._parsers[language] = parser
        return parser


def language_for_path(relative_path: str) -> str | None:
    suffix = ""
    if "." in relative_path.replace("\\", "/").split("/")[-1]:
        name = relative_path.replace("\\", "/").split("/")[-1]
        dot = name.rfind(".")
        suffix = name[dot:].lower()
    return SOURCE_SUFFIXES.get(suffix)


def extract_file(relative_path: str, source: bytes, language: str, parsers: ParserPort) -> FileTags:
    tree = parsers.parse(source, language)
    tags = FileTags(path=relative_path)
    if tree is None:
        return tags
    root = tree.root_node
    name_spans: set[tuple[int, int]] = set()
    engine = _engine_for(parsers)
    query_tags = engine.matches(tree, language, source)
    for qt in query_tags:
        if qt.kind == "def":
            name_spans.add(qt.name_span)
            tags.defs.append(
                DefTag(
                    path=relative_path,
                    name=qt.name,
                    kind=_kind_from_capture(qt.capture),
                    line=qt.line,
                    signature=qt.signature,
                )
            )
        elif qt.kind == "ref":
            tags.refs.append(qt.name)

    if language in _JS_LANGS:
        _arrow_assigns_walk(root, source, relative_path, tags.defs, name_spans)

    if not tags.defs:
        def_kinds = _DEF_TYPES.get(language, {})
        if def_kinds:
            _collect_defs_iter(root, source, relative_path, def_kinds, tags.defs, name_spans)

    if not tags.refs:
        _collect_refs_iter(root, source, tags.refs, name_spans)

    tags.defs = _dedupe_defs(tags.defs)
    return tags


def extract_file_payload(item: tuple[str, bytes, str]) -> tuple[str, dict[str, Any]]:
    """Module-level worker for ProcessPoolExecutor (Windows spawn)."""
    relative_path, source, language = item
    tags = extract_file(relative_path, source, language, _worker_parsers())
    return relative_path, file_tags_to_wire(tags)


def file_tags_to_wire(tags: FileTags) -> dict[str, Any]:
    return {
        "path": tags.path,
        "defs": [
            {
                "path": d.path,
                "name": d.name,
                "kind": d.kind,
                "line": d.line,
                "signature": d.signature,
            }
            for d in tags.defs
        ],
        "refs": list(tags.refs),
    }


def file_tags_from_wire(raw: dict[str, Any]) -> FileTags:
    defs = [
        DefTag(
            path=d["path"],
            name=d["name"],
            kind=d["kind"],
            line=d["line"],
            signature=d["signature"],
        )
        for d in raw["defs"]
    ]
    return FileTags(path=raw["path"], defs=defs, refs=list(raw["refs"]))


def _worker_parsers() -> TreeSitterParsers:
    global _WORKER_PARSERS
    if _WORKER_PARSERS is None:
        _WORKER_PARSERS = TreeSitterParsers()
    return _WORKER_PARSERS


def _engine_for(parsers: ParserPort) -> Any:
    engine = getattr(parsers, "tag_engine", None)
    if engine is not None:
        return engine
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        from gaudi.tags import TagQueryEngine

        _SHARED_ENGINE = TagQueryEngine()
    return _SHARED_ENGINE


def _kind_from_capture(capture: str) -> str:
    if "." in capture:
        return capture.split(".", 1)[1] or "symbol"
    return capture or "symbol"


def _dedupe_defs(defs: list[DefTag]) -> list[DefTag]:
    seen: set[tuple[str, int]] = set()
    out: list[DefTag] = []
    for d in defs:
        key = (d.name, d.line)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _collect_defs_iter(
    root: Any,
    source: bytes,
    path: str,
    def_kinds: dict[str, str],
    out: list[DefTag],
    name_spans: set[tuple[int, int]],
) -> None:
    stack = [root]
    while stack:
        node = stack.pop()
        ntype = node.type
        kind = def_kinds.get(ntype)
        if kind:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                name_node = _first_named_child(node, _IDENT_TYPES)
            if name_node is not None:
                name = _text(source, name_node).strip()
                if name:
                    name_spans.add((name_node.start_byte, name_node.end_byte))
                    out.append(
                        DefTag(
                            path=path,
                            name=name,
                            kind=kind,
                            line=node.start_point[0] + 1,
                            signature=_first_line(source, node),
                        )
                    )
        if ntype in {"lexical_declaration", "variable_declaration"}:
            _arrow_assigns(node, source, path, out, name_spans)
        children = node.children
        for child in reversed(children):
            stack.append(child)


def _arrow_assigns_walk(
    root: Any,
    source: bytes,
    path: str,
    out: list[DefTag],
    name_spans: set[tuple[int, int]],
) -> None:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in {"lexical_declaration", "variable_declaration"}:
            _arrow_assigns(node, source, path, out, name_spans)
        children = node.children
        for child in reversed(children):
            stack.append(child)


def _arrow_assigns(
    node: Any,
    source: bytes,
    path: str,
    out: list[DefTag],
    name_spans: set[tuple[int, int]],
) -> None:
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        value = child.child_by_field_name("value")
        if name_node is None or value is None:
            continue
        if value.type not in {"arrow_function", "function_expression", "function"}:
            continue
        name = _text(source, name_node).strip()
        if not name:
            continue
        name_spans.add((name_node.start_byte, name_node.end_byte))
        out.append(
            DefTag(
                path=path,
                name=name,
                kind="function",
                line=child.start_point[0] + 1,
                signature=_first_line(source, child),
            )
        )


def _collect_refs_iter(
    root: Any,
    source: bytes,
    out: list[str],
    name_spans: set[tuple[int, int]],
) -> None:
    stack = [root]
    while stack:
        node = stack.pop()
        span = (node.start_byte, node.end_byte)
        if node.type in _IDENT_TYPES and span not in name_spans:
            text = _text(source, node).strip()
            if text:
                out.append(text)
        children = node.children
        for child in reversed(children):
            stack.append(child)


def _first_named_child(node: Any, types: set[str]) -> Any | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _first_line(source: bytes, node: Any) -> str:
    text = _text(source, node)
    line = text.splitlines()[0] if text else ""
    return line.rstrip()
