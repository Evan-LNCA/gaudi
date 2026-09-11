from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gaudi.cache import TagCache
from gaudi.errors import GaudiError
from gaudi.extract import DefTag, FileTags, ParserPort
from gaudi.mapgen import (
    _ranked_files,
    collect_tags,
    freshness_line,
    load_config,
    query_fresh,
    render_body,
    warn_if_map_hidden,
)
from gaudi.paths import DEFAULT_FOCUS_TOKENS, DEFAULT_INDEX_TOKENS, token_count
from gaudi.rank import pagerank_defs, personalization_from_seeds, pagerank_files


@dataclass
class QueryResult:
    text: str
    payload: dict


def run_focus(
    root: Path,
    seeds: list[str],
    *,
    tokens: int | None = None,
    fmt: str = "text",
    parsers: ParserPort | None = None,
    no_git: bool = False,
    quiet: bool = False,
) -> QueryResult:
    if not quiet:
        warn_if_map_hidden(root)
    budget = tokens if tokens is not None else DEFAULT_FOCUS_TOKENS
    tags, tree, head, dirty = _load(root, parsers=parsers, no_git=no_git)
    fresh = query_fresh(root, head, tree)
    try:
        personalization = personalization_from_seeds(tags, seeds)
    except LookupError as exc:
        raise GaudiError(f"No files or symbols matched: {exc}") from exc
    scores = pagerank_defs(tags, personalization=personalization)
    seed_paths = {p for p in personalization if personalization[p] > 0}
    files_meta = _ranked_files(tags, scores)
    header = (
        f"{freshness_line(head, tree, fresh=fresh)}\n"
        f"dirty: {'true' if dirty else 'false'}\n"
        f"focus: {', '.join(seeds)}\n"
        "\n"
    )
    body, shown, total = render_body(
        files_meta, budget, header_len=len(header), seed_paths=seed_paths
    )
    if not body:
        body = "(empty — no defs in focus neighborhood)\n"
    footer = f"showing {shown} of {total} files\n"
    text = header + body + footer
    payload = {
        "fresh": fresh,
        "head": head,
        "tree": tree,
        "dirty": dirty,
        "focus": seeds,
        "showing": shown,
        "total_files": total,
        "tokens": token_count(text),
        "files": _files_payload(files_meta, shown),
    }
    return QueryResult(text=_format(text, payload, fmt), payload=payload)


def run_where(
    root: Path,
    symbol: str,
    *,
    fmt: str = "text",
    parsers: ParserPort | None = None,
    no_git: bool = False,
) -> QueryResult:
    tags, tree, head, dirty = _load(root, parsers=parsers, no_git=no_git)
    matches: list[DefTag] = []
    for t in tags:
        for d in t.defs:
            if d.name == symbol:
                matches.append(d)
    matches.sort(key=lambda d: (d.path, d.line))
    if not matches:
        raise GaudiError(f"Symbol not found: {symbol}")
    fresh = query_fresh(root, head, tree)
    lines = [freshness_line(head, tree, fresh=fresh)]
    for d in matches:
        lines.append(f"{d.path}:{d.line}  {d.signature}")
    text = "\n".join(lines) + "\n"
    payload = {
        "fresh": fresh,
        "head": head,
        "tree": tree,
        "dirty": dirty,
        "symbol": symbol,
        "matches": [
            {
                "path": d.path,
                "line": d.line,
                "signature": d.signature,
                "kind": d.kind,
            }
            for d in matches
        ],
    }
    return QueryResult(text=_format(text, payload, fmt), payload=payload)


def run_index(
    root: Path,
    *,
    tokens: int | None = None,
    fmt: str = "text",
    parsers: ParserPort | None = None,
    no_git: bool = False,
    quiet: bool = False,
) -> QueryResult:
    if not quiet:
        warn_if_map_hidden(root)
    budget = tokens if tokens is not None else DEFAULT_INDEX_TOKENS
    tags, tree, head, dirty = _load(root, parsers=parsers, no_git=no_git)
    fresh = query_fresh(root, head, tree)
    file_rank = pagerank_files(tags)
    hubs = sorted(
        ((t.path, len(t.defs), file_rank.get(t.path, 0.0)) for t in tags if t.defs),
        key=lambda row: (-row[2], row[0]),
    )
    dirs: dict[str, int] = {}
    for t in tags:
        parent = t.path.rsplit("/", 1)[0] if "/" in t.path else "."
        dirs[parent] = dirs.get(parent, 0) + len(t.defs)
    dir_rows = sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))
    header = (
        f"{freshness_line(head, tree, fresh=fresh)}\n"
        f"dirty: {'true' if dirty else 'false'}\n"
        "\n"
    )
    limit = max(budget, 1) * 4
    parts = [header.rstrip(), "", "hubs:"]
    used = len("\n".join(parts)) + 1
    shown_hubs = 0
    for path, n_defs, _score in hubs:
        line = f"{path}  {n_defs} defs"
        extra = len(line) + 1
        if used + extra > limit * 0.65 and shown_hubs:
            break
        parts.append(line)
        used += extra
        shown_hubs += 1
    parts.append("")
    parts.append("dirs:")
    used += 7
    shown_dirs = 0
    for directory, n_defs in dir_rows:
        line = f"{directory}/  {n_defs} defs" if directory != "." else f".  {n_defs} defs"
        extra = len(line) + 1
        if used + extra > limit and shown_dirs:
            break
        parts.append(line)
        used += extra
        shown_dirs += 1
    omitted_hubs = max(len(hubs) - shown_hubs, 0)
    omitted_dirs = max(len(dir_rows) - shown_dirs, 0)
    if omitted_hubs or omitted_dirs:
        parts.append(f"⋮ +{omitted_hubs} more hubs, {omitted_dirs} more dirs")
    parts.append(f"showing {shown_hubs} of {len(hubs)} files")
    text = "\n".join(parts) + "\n"
    payload = {
        "fresh": fresh,
        "head": head,
        "tree": tree,
        "dirty": dirty,
        "hubs": [{"path": p, "defs": n} for p, n, _s in hubs[:shown_hubs]],
        "dirs": [{"dir": d, "defs": n} for d, n in dir_rows[:shown_dirs]],
        "showing": shown_hubs,
        "total_files": len(hubs),
        "tokens": token_count(text),
    }
    return QueryResult(text=_format(text, payload, fmt), payload=payload)


def _load(
    root: Path,
    *,
    parsers: ParserPort | None,
    no_git: bool,
) -> tuple[list[FileTags], str, str, bool]:
    from gaudi.discover import detect_lister

    config = load_config(root)
    lister = detect_lister(root, no_git=no_git, extra_excludes=config.exclude)
    cache = TagCache(root, readonly=True)
    try:
        tags, tree = collect_tags(
            root,
            lister,
            parsers=parsers,
            cache=cache,
            save=False,
            config=config,
            no_git=no_git,
        )
    finally:
        cache.close()
    return tags, tree, lister.head_sha(), lister.is_dirty()


def _files_payload(
    files_meta: list[tuple[str, list[DefTag], list[DefTag]]],
    shown: int,
) -> list[dict]:
    out: list[dict] = []
    count = 0
    for path, ranked, all_defs in files_meta:
        if not ranked:
            continue
        if count >= shown:
            break
        omitted = max(len(all_defs) - len(ranked), 0)
        out.append(
            {
                "path": path,
                "defs": [
                    {"name": d.name, "line": d.line, "signature": d.signature, "kind": d.kind}
                    for d in ranked
                ],
                "elided": omitted,
            }
        )
        count += 1
    return out


def _format(text: str, payload: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if fmt == "text":
        return text
    raise GaudiError(f"Unknown format: {fmt}")
