from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from gaudi.cache import TagCache, content_hash
from gaudi.extract import DefTag, FileTags, ParserPort, TreeSitterParsers, extract_file, language_for_path
from gaudi.gitutil import GitRepo
from gaudi.paths import CONFIG_REL, DEFAULT_MAP_TOKENS, MAP_REL, should_skip, under
from gaudi.rank import pagerank_defs
from gaudi.ship import update_all_ignore_files

HEADER_MARK = "GENERATED — do not hand-edit"
_HEAD_RE = re.compile(r"^head:\s*(\S+)\s*$", re.M)
_DIRTY_RE = re.compile(r"^dirty:\s*(true|false)\s*$", re.M | re.I)
_TREE_RE = re.compile(r"^tree:\s*(\S+)\s*$", re.M)


def load_map_tokens(root: Path, override: int | None = None) -> int:
    if override is not None:
        return override
    cfg_path = under(root, CONFIG_REL)
    if cfg_path.is_file():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        tokens = data.get("map_tokens", DEFAULT_MAP_TOKENS)
        return int(tokens)
    return DEFAULT_MAP_TOKENS


def write_default_config(root: Path) -> None:
    cfg_path = under(root, CONFIG_REL)
    if cfg_path.is_file():
        return
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps({"map_tokens": DEFAULT_MAP_TOKENS}, indent=2) + "\n",
        encoding="utf-8",
    )


def tree_fingerprint(files: list[tuple[str, str]]) -> str:
    """files: sorted (path, content_hash)."""
    h = hashlib.sha256()
    for path, digest in files:
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def collect_tags(
    root: Path,
    git: GitRepo,
    parsers: ParserPort | None = None,
    cache: TagCache | None = None,
) -> tuple[list[FileTags], str]:
    parsers = parsers or TreeSitterParsers()
    cache = cache or TagCache(root)
    tracked = git.ls_files()
    hashed: list[tuple[str, str]] = []
    tags_out: list[FileTags] = []
    for rel in tracked:
        norm = rel.replace("\\", "/")
        if should_skip(norm):
            continue
        lang = language_for_path(norm)
        if lang is None:
            continue
        abs_path = root / rel
        if not abs_path.is_file():
            continue
        data = abs_path.read_bytes()
        digest = content_hash(data)
        hashed.append((norm, digest))
        cached = cache.get(digest)
        if cached is not None:
            defs = [
                DefTag(
                    path=norm,
                    name=d.name,
                    kind=d.kind,
                    line=d.line,
                    signature=d.signature,
                )
                for d in cached.defs
            ]
            tags_out.append(FileTags(path=norm, defs=defs, refs=list(cached.refs)))
            continue
        tags = extract_file(norm, data, lang, parsers)
        cache.put(digest, tags)
        tags_out.append(tags)
    cache.save()
    hashed.sort()
    return tags_out, tree_fingerprint(hashed)


def render_map(
    tags: list[FileTags],
    scores: dict[str, float],
    head: str,
    dirty: bool,
    tree: str,
    map_tokens: int,
) -> str:
    header = (
        f"{HEADER_MARK}\n"
        f"head: {head}\n"
        f"dirty: {'true' if dirty else 'false'}\n"
        f"tree: {tree}\n"
        "\n"
    )
    budget = max(map_tokens, 1) * 4
    by_file: dict[str, FileTags] = {t.path: t for t in tags}
    file_score: dict[str, float] = {}
    keep: dict[str, list] = {}
    for t in tags:
        ranked = sorted(t.defs, key=lambda d: scores.get(d.key, 0.0), reverse=True)
        file_score[t.path] = max((scores.get(d.key, 0.0) for d in t.defs), default=0.0)
        keep[t.path] = ranked

    ordered_files = sorted(by_file.keys(), key=lambda p: (-file_score.get(p, 0.0), p))
    body_parts: list[str] = []
    used = len(header)

    for path in ordered_files:
        defs = keep[path]
        if not defs:
            continue
        selected = []
        for d in defs:
            trial = _render_file(path, _source_order(selected + [d]))
            extra = len(trial) + (1 if body_parts else 0)
            if selected and used + extra > budget:
                break
            selected.append(d)
        if not selected:
            continue
        block = _render_file(path, _source_order(selected))
        extra = len(block) + (2 if body_parts else 0)
        if body_parts and used + extra > budget:
            break
        body_parts.append(block)
        used += extra if body_parts else len(block)

    if not body_parts:
        body = "(empty — no Python/JavaScript/TypeScript defs)\n"
    else:
        body = "\n".join(body_parts) + "\n"
    return header + body


def _source_order(defs: list) -> list:
    return sorted(defs, key=lambda d: d.line)


def _render_file(path: str, defs: list) -> str:
    lines = [f"{path}:"]
    prev_line: int | None = None
    for d in defs:
        if prev_line is not None and d.line > prev_line + 1:
            lines.append("⋮...")
        lines.append(f"│{d.signature}")
        prev_line = d.line
    return "\n".join(lines)


def generate(root: Path, map_tokens: int | None = None, parsers: ParserPort | None = None) -> Path:
    git = GitRepo(root)
    git.require()
    update_all_ignore_files(root)
    write_default_config(root)
    tokens = load_map_tokens(root, map_tokens)
    tags, tree = collect_tags(root, git, parsers=parsers)
    scores = pagerank_defs(tags)
    text = render_map(tags, scores, git.head_sha(), git.is_dirty(), tree, tokens)
    dest = under(root, MAP_REL)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    return dest


def parse_header(map_text: str) -> tuple[str, bool, str] | None:
    head = _HEAD_RE.search(map_text)
    dirty = _DIRTY_RE.search(map_text)
    tree = _TREE_RE.search(map_text)
    if not head or not dirty or not tree:
        return None
    return head.group(1), dirty.group(1).lower() == "true", tree.group(1)


def is_fresh(root: Path, parsers: ParserPort | None = None) -> bool:
    git = GitRepo(root)
    git.require()
    map_path = under(root, MAP_REL)
    if not map_path.is_file():
        return False
    parsed = parse_header(map_path.read_text(encoding="utf-8"))
    if parsed is None:
        return False
    head, dirty, tree = parsed
    if head != git.head_sha():
        return False
    if dirty != git.is_dirty():
        return False
    _, current_tree = collect_tags(root, git, parsers=parsers)
    return tree == current_tree


def status_code(root: Path) -> int:
    return 0 if is_fresh(root) else 1


def header_matches_git(root: Path) -> bool:
    """Cheap freshness: MAP header SHA + dirty vs git. No re-parse."""
    git = GitRepo(root)
    git.require()
    map_path = under(root, MAP_REL)
    if not map_path.is_file():
        return False
    parsed = parse_header(map_path.read_text(encoding="utf-8"))
    if parsed is None:
        return False
    head, dirty, _tree = parsed
    return head == git.head_sha() and dirty == git.is_dirty()
