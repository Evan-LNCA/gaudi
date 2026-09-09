from __future__ import annotations

from collections import defaultdict

import networkx as nx

from gaudi.extract import DefTag, FileTags


def pagerank_defs(files: list[FileTags]) -> dict[str, float]:
    """Rank definition keys. Cross-file refs to a name flow rank to those defs."""
    graph: nx.DiGraph = nx.DiGraph()
    defs_by_name: dict[str, list[DefTag]] = defaultdict(list)
    for tags in files:
        for d in tags.defs:
            graph.add_node(d.key)
            defs_by_name[d.name].append(d)

    for tags in files:
        for ref in tags.refs:
            targets = defs_by_name.get(ref, [])
            for t in targets:
                if t.path == tags.path and t.name == ref:
                    continue
                graph.add_edge(f"ref::{tags.path}", t.key)

    if graph.number_of_nodes() == 0:
        return {}
    return _pagerank(graph)


def _pagerank(
    graph: nx.DiGraph,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-6,
) -> dict[str, float]:
    """Power iteration. Avoids NetworkX's SciPy backend (not a project dependency)."""
    nodes = list(graph.nodes())
    n = len(nodes)
    index = {node: i for i, node in enumerate(nodes)}
    scores = [1.0 / n] * n
    out_deg = [graph.out_degree(node) for node in nodes]
    incoming: list[list[int]] = [[] for _ in nodes]
    for u, v in graph.edges():
        incoming[index[v]].append(index[u])
    dangling = [i for i, deg in enumerate(out_deg) if deg == 0]
    for _ in range(max_iter):
        new = [(1.0 - alpha) / n] * n
        dangling_mass = alpha * sum(scores[i] for i in dangling) / n
        for i in range(n):
            acc = dangling_mass
            for j in incoming[i]:
                acc += alpha * scores[j] / out_deg[j]
            new[i] += acc
        err = sum(abs(new[i] - scores[i]) for i in range(n))
        scores = new
        if err < n * tol:
            break
    return {nodes[i]: scores[i] for i in range(n)}
