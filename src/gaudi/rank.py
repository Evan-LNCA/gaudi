from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import networkx as nx

from gaudi.extract import DefTag, FileTags

_MAX_IDENT_FILES = 20


def pagerank_defs(
    files: list[FileTags],
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    """Rank definition keys via a weighted file graph, then inbound-share split."""
    file_rank = pagerank_files(files, personalization=personalization)
    return distribute_def_rank(files, file_rank)


def pagerank_files(
    files: list[FileTags],
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    graph = _file_graph(files)
    if graph.number_of_nodes() == 0:
        return {}
    return _pagerank(graph, personalization=personalization)


def distribute_def_rank(files: list[FileTags], file_rank: dict[str, float]) -> dict[str, float]:
    defs_by_name: dict[str, list[DefTag]] = defaultdict(list)
    by_path: dict[str, FileTags] = {}
    for tags in files:
        by_path[tags.path] = tags
        for d in tags.defs:
            defs_by_name[d.name].append(d)

    inbound: dict[str, float] = defaultdict(float)
    for tags in files:
        for ref in tags.refs:
            targets = defs_by_name.get(ref, [])
            if not targets:
                continue
            files_for_ident = {t.path for t in targets}
            n_files = len(files_for_ident)
            if n_files == 0 or n_files > _MAX_IDENT_FILES:
                continue
            share = 1.0 / n_files
            counts: dict[str, int] = defaultdict(int)
            for t in targets:
                if t.path == tags.path:
                    continue
                counts[t.key] += 1
            for key, count in counts.items():
                inbound[key] += share * count

    scores: dict[str, float] = {}
    for tags in files:
        fr = file_rank.get(tags.path, 0.0)
        if not tags.defs:
            continue
        weights = [inbound.get(d.key, 0.0) + 1.0 for d in tags.defs]
        total = sum(weights)
        for d, w in zip(tags.defs, weights, strict=True):
            scores[d.key] = fr * (w / total)
    return scores


def personalization_from_seeds(files: list[FileTags], seeds: list[str]) -> dict[str, float]:
    """Map path/symbol seeds to a file personalization vector."""
    paths = {t.path for t in files}
    defs_by_name: dict[str, list[DefTag]] = defaultdict(list)
    neighbors: dict[str, set[str]] = defaultdict(set)
    graph = _file_graph(files)
    for u, v in graph.edges():
        neighbors[str(u)].add(str(v))
        neighbors[str(v)].add(str(u))
    for tags in files:
        for d in tags.defs:
            defs_by_name[d.name].append(d)

    seed_weights: dict[str, float] = defaultdict(float)
    for seed in seeds:
        norm = seed.replace("\\", "/").lstrip("./")
        matched_paths = [p for p in paths if p == norm or p.endswith("/" + norm) or p.startswith(norm)]
        if matched_paths:
            for p in matched_paths:
                seed_weights[p] += 1.0
            continue
        hits = defs_by_name.get(seed, [])
        if hits:
            for d in hits:
                seed_weights[d.path] += 1.0
            continue
        raise LookupError(seed)

    if not seed_weights:
        raise LookupError(",".join(seeds))

    hop_weights: dict[str, float] = defaultdict(float)
    for path in seed_weights:
        for nb in neighbors.get(path, ()):
            if nb not in seed_weights:
                hop_weights[nb] += 1.0

    out: dict[str, float] = {}
    seed_total = sum(seed_weights.values())
    hop_total = sum(hop_weights.values())
    for path, w in seed_weights.items():
        out[path] = 0.8 * (w / seed_total)
    if hop_total > 0:
        for path, w in hop_weights.items():
            out[path] = out.get(path, 0.0) + 0.2 * (w / hop_total)
    else:
        for path in list(out):
            out[path] = out[path] / 0.8
    return out


def _file_graph(files: list[FileTags]) -> nx.DiGraph:
    graph: nx.DiGraph = nx.DiGraph()
    defs_by_name: dict[str, list[DefTag]] = defaultdict(list)
    for tags in files:
        graph.add_node(tags.path)
        for d in tags.defs:
            defs_by_name[d.name].append(d)

    for tags in files:
        counts: dict[str, float] = defaultdict(float)
        for ref in tags.refs:
            targets = defs_by_name.get(ref, [])
            if not targets:
                continue
            defining = {t.path for t in targets}
            n_files = len(defining)
            if n_files == 0 or n_files > _MAX_IDENT_FILES:
                continue
            discount = 1.0 / n_files
            for dest in defining:
                if dest == tags.path:
                    continue
                counts[dest] += discount
        for dest, count in counts.items():
            if count <= 0:
                continue
            weight = math.sqrt(count)
            if graph.has_edge(tags.path, dest):
                graph[tags.path][dest]["weight"] += weight
            else:
                graph.add_edge(tags.path, dest, weight=weight)
    return graph


def _pagerank(
    graph: nx.DiGraph,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-6,
    personalization: dict[str, float] | None = None,
) -> dict[str, float]:
    """Power iteration with optional weights and personalization.

    Tries numpy when importable; otherwise a pure-Python loop.
    """
    nodes = sorted(graph.nodes())
    n = len(nodes)
    index = {node: i for i, node in enumerate(nodes)}
    if personalization is None:
        p = [1.0 / n] * n
    else:
        raw = [float(personalization.get(node, 0.0)) for node in nodes]
        total = sum(raw)
        p = [1.0 / n] * n if total <= 0 else [x / total for x in raw]

    out_w = [0.0] * n
    incoming: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for u, v, data in graph.edges(data=True):
        w = float(data.get("weight", 1.0))
        if w <= 0:
            continue
        ui = index[u]
        vi = index[v]
        out_w[ui] += w
        incoming[vi].append((ui, w))

    np = _try_numpy()
    if np is not None:
        return _pagerank_numpy(np, nodes, p, out_w, incoming, alpha, max_iter, tol)
    return _pagerank_python(nodes, p, out_w, incoming, alpha, max_iter, tol)


def _try_numpy() -> Any | None:
    try:
        import numpy as np
    except ImportError:
        return None
    return np


def _pagerank_python(
    nodes: list[object],
    p: list[float],
    out_w: list[float],
    incoming: list[list[tuple[int, float]]],
    alpha: float,
    max_iter: int,
    tol: float,
) -> dict[str, float]:
    n = len(nodes)
    scores = list(p)
    dangling = [i for i, w in enumerate(out_w) if w == 0.0]
    for _ in range(max_iter):
        dangling_mass = alpha * sum(scores[i] for i in dangling)
        new = [(1.0 - alpha) * p[i] + dangling_mass * p[i] for i in range(n)]
        for i in range(n):
            acc = 0.0
            for j, w in incoming[i]:
                acc += scores[j] * (w / out_w[j])
            new[i] += alpha * acc
        err = sum(abs(new[i] - scores[i]) for i in range(n))
        scores = new
        if err < n * tol:
            break
    return {str(nodes[i]): scores[i] for i in range(n)}


def _pagerank_numpy(
    np: Any,
    nodes: list[object],
    p: list[float],
    out_w: list[float],
    incoming: list[list[tuple[int, float]]],
    alpha: float,
    max_iter: int,
    tol: float,
) -> dict[str, float]:
    n = len(nodes)
    wmat = np.zeros((n, n), dtype=np.float64)
    for v, edges in enumerate(incoming):
        for u, w in edges:
            wmat[v, u] = w / out_w[u]
    p_arr = np.array(p, dtype=np.float64)
    dangling = np.array([1.0 if w == 0.0 else 0.0 for w in out_w], dtype=np.float64)
    x = p_arr.copy()
    for _ in range(max_iter):
        dangling_mass = alpha * float(x.dot(dangling))
        x_new = alpha * (wmat @ x) + dangling_mass * p_arr + (1.0 - alpha) * p_arr
        if float(np.abs(x_new - x).sum()) < n * tol:
            x = x_new
            break
        x = x_new
    return {str(nodes[i]): float(x[i]) for i in range(n)}
