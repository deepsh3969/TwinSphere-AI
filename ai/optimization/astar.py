"""A* pathfinding over the campus route graph (Phase 7 §5).

Modular: works on `RouteGraph` + `CostWeights`. Falls back to Dijkstra-style
search automatically when a mode's distance weight is 0 (admissible h = 0).
"""

from __future__ import annotations

import heapq
from typing import Iterable

from ai.optimization.graph import RouteGraph
from ai.optimization.route_cost import CostWeights, edge_cost, heuristic


def astar(graph: RouteGraph, start: str, goals: Iterable[str],
          weights: CostWeights, blocked_nodes: set[str] | None = None,
          banned_edges: set[str] | None = None,
          penalty_edges: dict[str, float] | None = None,
          capacity_demand: float = 0.0) -> tuple[list[str], list[str]] | None:
    """Return (node_path, road_path) with the lowest weighted cost, or None.

    banned_edges   — edges forbidden for this search (alternative generation)
    penalty_edges  — multiplicative cost penalty per edge (diversity pressure)
    """
    goalset = {g for g in goals if g in graph.nodes}
    if not goalset or start not in graph.nodes:
        return None
    blocked_nodes = blocked_nodes or set()
    banned_edges = banned_edges or set()
    penalty_edges = penalty_edges or {}
    if start in blocked_nodes:
        return None

    open_heap: list[tuple[float, str]] = [(heuristic(graph, start, goalset, weights), start)]
    came_from: dict[str, tuple[str, str]] = {}
    g_score: dict[str, float] = {start: 0.0}
    closed: set[str] = set()

    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current in goalset:
            path_nodes = [current]
            path_roads: list[str] = []
            while current in came_from:
                current, road_id = came_from[current]
                path_nodes.append(current)
                path_roads.append(road_id)
            path_nodes.reverse()
            path_roads.reverse()
            return path_nodes, path_roads
        closed.add(current)
        for neighbour, road_id in graph.neighbors(current):
            if neighbour in closed or neighbour in blocked_nodes:
                continue
            if road_id in banned_edges:
                continue
            edge = graph.edge(road_id)
            if edge is None:
                continue
            cost = edge_cost(edge, weights, capacity_demand)
            if cost == float("inf"):
                continue
            if road_id in penalty_edges:
                cost *= penalty_edges[road_id]
            tentative = g_score[current] + cost
            if tentative < g_score.get(neighbour, float("inf")):
                g_score[neighbour] = tentative
                came_from[neighbour] = (current, road_id)
                heapq.heappush(open_heap, (tentative + heuristic(graph, neighbour, goalset, weights),
                                           neighbour))
    return None
