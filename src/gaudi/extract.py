from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from gaudi.paths import SOURCE_SUFFIXES


class ParserPort(Protocol):
    def parse(self, source: bytes, language: str) -> object | None:
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
}


class TreeSitterParsers:
    """Loads parsers via tree-sitter-language-pack. Cached per language."""

    def __init__(self) -> None:
        self._parsers: dict[str, object] = {}

    def parse(self, source: bytes, language: str) -> object | None:
        parser = self._get(language)
        if parser is None:
            return None
        return parser.parse(source)

    def _get(self, language: str) -> object | None:
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
    def_kinds = _DEF_TYPES.get(language, {})
    def_name_spans: set[tuple[int, int]] = set()
    _collect_defs(root, source, relative_path, def_kinds, tags.defs, def_name_spans)
    _collect_refs(root, source, tags.refs, def_name_spans)
    return tags


def _collect_defs(
    node: object,
    source: bytes,
    path: str,
    def_kinds: dict[str, str],
    out: list[DefTag],
    name_spans: set[tuple[int, int]],
) -> None:
    ntype = node.type
    kind = def_kinds.get(ntype)
    if kind:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            name_node = _first_named_child(node, {"identifier", "property_identifier", "type_identifier"})
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
    for child in node.children:
        _collect_defs(child, source, path, def_kinds, out, name_spans)

    if ntype in {"lexical_declaration", "variable_declaration"}:
        _arrow_assigns(node, source, path, out, name_spans)


def _arrow_assigns(
    node: object,
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


def _collect_refs(
    node: object,
    source: bytes,
    out: list[str],
    name_spans: set[tuple[int, int]],
) -> None:
    span = (node.start_byte, node.end_byte)
    if node.type in {"identifier", "property_identifier", "type_identifier"} and span not in name_spans:
        text = _text(source, node).strip()
        if text:
            out.append(text)
    for child in node.children:
        _collect_refs(child, source, out, name_spans)


def _first_named_child(node: object, types: set[str]) -> object | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _text(source: bytes, node: object) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _first_line(source: bytes, node: object) -> str:
    text = _text(source, node)
    line = text.splitlines()[0] if text else ""
    return line.rstrip()
