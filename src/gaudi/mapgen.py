from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pathspec import PathSpec

from gaudi.cache import TagCache, content_hash
from gaudi.discover import SourceLister, compile_exclude_spec, detect_lister
from gaudi.extract import (
    DefTag,
    FileTags,
    ParserPort,
    TreeSitterParsers,
    extract_file,
    extract_file_payload,
    file_tags_from_wire,
    language_for_path,
)
from gaudi.gitutil import GitRepo
from gaudi.paths import (
    CONFIG_REL,
    DEFAULT_MAP_TOKENS,
    MAP_REL,
    POOL_MIN_BYTES,
    POOL_MIN_FILES,
    GaudiConfig,
    should_skip,
    token_count,
    under,
)
from gaudi.rank import pagerank_defs
from gaudi.ship import update_all_ignore_files

HEADER_MARK = "GENERATED — do not hand-edit"
_HEAD_RE = re.compile(r"^head:\s*(\S+)\s*$", re.M)
_DIRTY_RE = re.compile(r"^dirty:\s*(true|false)\s*$", re.M | re.I)
_TREE_RE = re.compile(r"^tree:\s*(\S+)\s*$", re.M)


@dataclass
class GenerateResult:
    path: Path
    files: int
    defs: int
    tokens: int
    elapsed: float
    text: str


def load_config(root: Path, map_tokens: int | None = None) -> GaudiConfig:
    cfg = GaudiConfig()
    cfg_path = under(root, CONFIG_REL)
    if cfg_path.is_file():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if "map_tokens" in data:
            cfg.map_tokens = int(data["map_tokens"])
        if "max_file_bytes" in data:
            cfg.max_file_bytes = int(data["max_file_bytes"])
        exclude = data.get("exclude", [])
        if isinstance(exclude, list):
            cfg.exclude = [str(x) for x in exclude]
        elif exclude:
            raise ValueError(f"{cfg_path} exclude must be a list")
    if map_tokens is not None:
        cfg.map_tokens = map_tokens
    return cfg


def load_map_tokens(root: Path, override: int | None = None) -> int:
    return load_config(root, override).map_tokens


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
    source: GitRepo | SourceLister | None = None,
    parsers: ParserPort | None = None,
    cache: TagCache | None = None,
    *,
    save: bool = True,
    config: GaudiConfig | None = None,
    no_git: bool = False,
) -> tuple[list[FileTags], str]:
    parsers = parsers or TreeSitterParsers()
    config = config or load_config(root)
    created_cache = cache is None
    cache = cache or TagCache(root, readonly=not save)
    lister = _as_lister(root, source, no_git=no_git, extra=config.exclude)
    exclude = compile_exclude_spec(config)
    try:
        tags_out, tree, live = _collect_from_lister(
            root, lister, parsers, cache, config, exclude
        )
        if save:
            cache.prune(live)
            cache.save()
        return tags_out, tree
    finally:
        if created_cache:
            cache.close()


def _as_lister(
    root: Path,
    source: GitRepo | SourceLister | None,
    *,
    no_git: bool,
    extra: list[str],
) -> SourceLister:
    if source is None:
        return detect_lister(root, no_git=no_git, extra_excludes=extra)
    if isinstance(source, GitRepo):
        from gaudi.discover import GitLister

        return GitLister(root, source)
    return source


def _collect_from_lister(
    root: Path,
    lister: SourceLister,
    parsers: ParserPort,
    cache: TagCache,
    config: GaudiConfig,
    exclude: PathSpec,
) -> tuple[list[FileTags], str, set[str]]:
    hashed: list[tuple[str, str]] = []
    tags_out: list[FileTags] = []
    live: set[str] = set()
    misses: list[tuple[str, bytes, str, str]] = []
    for rel in lister.list_rel_paths():
        norm = rel.replace("\\", "/")
        if should_skip(norm) or exclude.match_file(norm):
            continue
        lang = language_for_path(norm)
        if lang is None:
            continue
        abs_path = root / rel
        if not abs_path.is_file():
            continue
        try:
            size = abs_path.stat().st_size
        except OSError:
            continue
        if size > config.max_file_bytes:
            continue
        data = abs_path.read_bytes()
        if _skip_generated_or_minified(norm, data):
            continue
        digest = content_hash(data)
        hashed.append((norm, digest))
        live.add(digest)
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
        misses.append((norm, data, lang, digest))

    extracted = _extract_misses(misses, parsers)
    for digest, tags in extracted:
        cache.put(digest, tags)
        tags_out.append(tags)

    hashed.sort()
    return tags_out, tree_fingerprint(hashed), live


def _extract_misses(
    misses: list[tuple[str, bytes, str, str]],
    parsers: ParserPort,
) -> list[tuple[str, FileTags]]:
    if not misses:
        return []
    total_bytes = sum(len(item[1]) for item in misses)
    use_pool = len(misses) >= POOL_MIN_FILES and total_bytes >= POOL_MIN_BYTES
    if not use_pool:
        out: list[tuple[str, FileTags]] = []
        for rel, data, lang, digest in misses:
            out.append((digest, extract_file(rel, data, lang, parsers)))
        return out
    jobs = [(rel, data, lang) for rel, data, lang, _digest in misses]
    digest_by_path = {rel: digest for rel, _data, _lang, digest in misses}
    with ProcessPoolExecutor() as pool:
        wired = list(pool.map(extract_file_payload, jobs))
    out = []
    for rel, payload in wired:
        out.append((digest_by_path[rel], file_tags_from_wire(payload)))
    return out


def _skip_generated_or_minified(relative_path: str, data: bytes) -> bool:
    name = Path(relative_path).name.lower()
    if ".min." in name:
        return True
    if name.endswith(".generated.ts") or name.endswith(".g.cs"):
        return True
    head = data[:400]
    if b"@generated" in head or head.lstrip().startswith((b"// Generated", b"# Generated")):
        return True
    if len(data) < 4096:
        return False
    newlines = data.count(b"\n")
    if newlines == 0:
        return True
    return (len(data) / newlines) > 500


def render_map(
    tags: list[FileTags],
    scores: dict[str, float],
    head: str,
    dirty: bool,
    tree: str,
    map_tokens: int,
) -> str:
    header = _header(head, dirty, tree)
    files_meta = _ranked_files(tags, scores)
    body, shown, total = render_body(files_meta, map_tokens, header_len=len(header))
    if not body:
        body = "(empty — no supported-language defs)\n"
    footer = f"showing {shown} of {total} files\n"
    return header + body + footer


def _header(head: str, dirty: bool, tree: str) -> str:
    return (
        f"{HEADER_MARK}\n"
        f"head: {head}\n"
        f"dirty: {'true' if dirty else 'false'}\n"
        f"tree: {tree}\n"
        "\n"
    )


def freshness_line(head: str, tree: str, *, fresh: bool) -> str:
    state = "true" if fresh else "false"
    return f"fresh: {state}  head: {head}  tree: {tree}"


def query_fresh(root: Path, head: str, tree: str) -> bool:
    """True when this live head+tree matches `.map`, or when no map exists yet.

    Query commands parse the current tree, so missing `.map` still counts as
    fresh. A present but mismatched map means the saved artifact is stale.
    """
    map_path = under(root, MAP_REL)
    if not map_path.is_file():
        return True
    try:
        parsed = parse_header(map_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Cannot read map header from {map_path}") from exc
    if parsed is None:
        return False
    map_head, _dirty, map_tree = parsed
    return map_head == head and map_tree == tree


def _ranked_files(
    tags: list[FileTags], scores: dict[str, float]
) -> list[tuple[str, list[DefTag], list[DefTag]]]:
    rows: list[tuple[str, list[DefTag], list[DefTag], float]] = []
    for t in tags:
        ranked = sorted(t.defs, key=lambda d: scores.get(d.key, 0.0), reverse=True)
        file_score = max((scores.get(d.key, 0.0) for d in t.defs), default=0.0)
        rows.append((t.path, ranked, t.defs, file_score))
    rows.sort(key=lambda row: (-row[3], row[0]))
    return [(path, ranked, all_defs) for path, ranked, all_defs, _ in rows]


def render_body(
    files_meta: list[tuple[str, list[DefTag], list[DefTag]]],
    map_tokens: int,
    *,
    header_len: int,
    seed_paths: set[str] | None = None,
) -> tuple[str, int, int]:
    budget = max(map_tokens, 1) * 4
    footer_reserve = len("showing 99999 of 99999 files\n")
    limit = max(budget - footer_reserve, header_len + 1)
    body_parts: list[str] = []
    used = header_len
    shown = 0
    total = sum(1 for _path, ranked, _all in files_meta if ranked)
    ordered = files_meta
    if seed_paths:
        seeded = [row for row in files_meta if row[0] in seed_paths and row[1]]
        rest = [row for row in files_meta if row[0] not in seed_paths]
        ordered = seeded + rest

    for path, ranked, all_defs in ordered:
        if not ranked:
            continue
        selected: list[DefTag] = []
        omitted = 0
        for d in ranked:
            trial_defs = _source_order(selected + [d])
            trial = _render_file(path, trial_defs, omitted=0)
            extra = len(trial) + (1 if body_parts else 0)
            if selected and used + extra > limit:
                omitted = len(ranked) - len(selected)
                break
            selected.append(d)
        if not selected:
            continue
        if omitted:
            block = _render_file(path, _source_order(selected), omitted=omitted)
        else:
            leftover = len(all_defs) - len(selected)
            block = _render_file(path, _source_order(selected), omitted=max(leftover, 0))
        extra = len(block) + (1 if body_parts else 0)
        if body_parts and used + extra > limit:
            break
        body_parts.append(block)
        used += extra
        shown += 1

    if not body_parts:
        return "", 0, total
    return "\n".join(body_parts) + "\n", shown, total


def _source_order(defs: list[DefTag]) -> list[DefTag]:
    return sorted(defs, key=lambda d: d.line)


def _render_file(path: str, defs: list[DefTag], omitted: int = 0) -> str:
    lines = [f"{path}:"]
    prev_line: int | None = None
    for d in defs:
        if prev_line is not None and d.line > prev_line + 1:
            lines.append("⋮...")
        lines.append(f"│{d.signature}")
        prev_line = d.line
    if omitted > 0:
        lines.append(f"⋮ +{omitted} more defs")
    return "\n".join(lines)


def generate(
    root: Path,
    map_tokens: int | None = None,
    parsers: ParserPort | None = None,
    *,
    quiet: bool = False,
    no_git: bool = False,
) -> GenerateResult:
    started = time.perf_counter()
    write_default_config(root)
    update_all_ignore_files(root)
    if not quiet:
        warn_if_map_hidden(root)
    config = load_config(root, map_tokens)
    lister = detect_lister(root, no_git=no_git, extra_excludes=config.exclude)
    tags, tree = collect_tags(
        root, lister, parsers=parsers, save=True, config=config, no_git=no_git
    )
    scores = pagerank_defs(tags)
    text = render_map(tags, scores, lister.head_sha(), lister.is_dirty(), tree, config.map_tokens)
    dest = under(root, MAP_REL)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    elapsed = time.perf_counter() - started
    n_defs = sum(len(t.defs) for t in tags)
    return GenerateResult(
        path=dest,
        files=len(tags),
        defs=n_defs,
        tokens=token_count(text),
        elapsed=elapsed,
        text=text,
    )


def parse_header(map_text: str) -> tuple[str, bool, str] | None:
    head = _HEAD_RE.search(map_text)
    dirty = _DIRTY_RE.search(map_text)
    tree = _TREE_RE.search(map_text)
    if not head or not dirty or not tree:
        return None
    return head.group(1), dirty.group(1).lower() == "true", tree.group(1)


def is_fresh(root: Path, parsers: ParserPort | None = None, *, no_git: bool = False) -> bool:
    map_path = under(root, MAP_REL)
    if not map_path.is_file():
        return False
    parsed = parse_header(map_path.read_text(encoding="utf-8"))
    if parsed is None:
        return False
    head, _dirty, tree = parsed
    lister = detect_lister(root, no_git=no_git)
    if head != lister.head_sha():
        return False
    cache = TagCache(root, readonly=True)
    try:
        _, current_tree = collect_tags(
            root,
            lister,
            parsers=parsers,
            cache=cache,
            save=False,
            no_git=no_git,
        )
    finally:
        cache.close()
    return tree == current_tree


def status_code(root: Path, *, no_git: bool = False) -> int:
    return 0 if is_fresh(root, no_git=no_git) else 1


def header_matches_git(root: Path, *, no_git: bool = False) -> bool:
    """Cheap freshness: MAP header SHA vs current HEAD. No re-parse, ignores dirty."""
    lister = detect_lister(root, no_git=no_git)
    map_path = under(root, MAP_REL)
    if not map_path.is_file():
        return False
    parsed = parse_header(map_path.read_text(encoding="utf-8"))
    if parsed is None:
        return False
    head, _dirty, _tree = parsed
    return head == lister.head_sha()


def warn_if_map_hidden(root: Path) -> None:
    for name in (".gitignore", ".cursorignore"):
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Cannot read {path}") from exc
        if _glob_hides_dot_map(text):
            print(
                f"warning: {name} has a *.map pattern that may hide .map from the agent",
                file=sys.stderr,
            )


def _glob_hides_dot_map(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if line in {"*.map", "**/*.map", "./*.map"}:
            return True
    return False
