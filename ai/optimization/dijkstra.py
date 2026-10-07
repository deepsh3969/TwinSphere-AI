"""Dijkstra reference implementation (Phase 7 §5).

Used as the ground-truth fallback: A* results are asserted equal-or-better than
Dijkstra in tests, and a zero-distance-weight mode degrades to this behaviour.
"""

from __future__ import annotations

import heapq
from typing import Iterable

from ai.optimization.graph import RouteGraph
from ai.optimization.route_cost import CostWeights, edge_cost


def dijkstra(graph: RouteGraph, start: str, goals: Iterable[str],
             weights: CostWeights, blocked_nodes: set[str] | None = None,
             banned_edges: set[str] | None = None) -> tuple[list[str], list[str]] | None:
    """Lowest-cost (node_path, road_path) ignoring heuristics, or None."""
    goalset = {g for g in goals if g in graph.nodes}
    if not goalset or start not in graph.nodes or start in (blocked_nodes or set()):
        return None
    blocked_nodes = blocked_nodes or set()
    banned_edges = banned_edges or set()

    heap: list[tuple[float, str]] = [(0.0, start)]
    came_from: dict[str, tuple[str, str]] = {}
    best: dict[str, float] = {start: 0.0}
    closed: set[str] = set()

    while heap:
        cost_u, u = heapq.heappop(heap)
        if u in closed:
            continue
        if u in goalset:
            path_nodes = [u]
            path_roads: list[str] = []
            while u in came_from:
                u, rid = came_from[u]
                path_nodes.append(u)
                path_roads.append(rid)
            path_nodes.reverse()
            path_roads.reverse()
            return path_nodes, path_roads
        closed.add(u)
        for v, rid in graph.neighbors(u):
            if v in closed or v in blocked_nodes or rid in banned_edges:
                continue
            edge = graph.edge(rid)
            if edge is None:
                continue
            w = edge_cost(edge, weights)
            if w == float("inf"):
                continue
            nd = cost_u + w
            if nd < best.get(v, float("inf")):
                best[v] = nd
                came_from[v] = (u, rid)
                heapq.heappush(heap, (nd, v))
    return None
