"""Campus route optimisation: A* over the road graph.

Cost = distance * (1 + 1.5*congestion) * (1 + 2*risk/100) + node risk penalty.
Blocked roads are impassable. The safest route is not necessarily the shortest.
"""

from __future__ import annotations

import heapq
import math


def build_graph(nodes: dict, roads: dict) -> dict[str, list[tuple[str, str, dict]]]:
    graph: dict[str, list[tuple[str, str, dict]]] = {nid: [] for nid in nodes}
    for rid, road in roads.items():
        a, b = road["from_node"], road["to_node"]
        if a in graph and b in graph:
            graph[a].append((b, rid, road))
            graph[b].append((a, rid, road))
    return graph


def edge_cost(road: dict, node_risk: dict | None, target: str) -> float | None:
    if road.get("blocked"):
        return None
    length = float(road.get("length", 1.0))
    congestion = float(road.get("congestion", 0.0))
    risk = float(road.get("risk", 0.0))
    cost = length * (1.0 + 1.5 * congestion) * (1.0 + 2.0 * risk / 100.0)
    if node_risk:
        cost += length * (node_risk.get(target, 0.0) / 100.0) * 2.0
    return cost


def a_star(graph, nodes, start: str, goals: set[str], node_risk: dict | None = None,
           blocked_nodes: set[str] | None = None) -> tuple[list[str], list[str]] | None:
    """Return (node_path, road_path) for the lowest-cost path, or None."""
    blocked_nodes = blocked_nodes or set()
    if start in blocked_nodes:
        return None

    def h(nid: str) -> float:
        if not goals:
            return 0.0
        n = nodes[nid]
        return min(math.dist((n["x"], n["z"]), (nodes[g]["x"], nodes[g]["z"])) for g in goals if g in nodes)

    open_heap: list[tuple[float, str]] = [(h(start), start)]
    came_from: dict[str, tuple[str, str]] = {}
    g_score: dict[str, float] = {start: 0.0}
    closed: set[str] = set()

    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current in goals:
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
        for neighbour, road_id, road in graph.get(current, []):
            if neighbour in blocked_nodes or neighbour in closed:
                continue
            cost = edge_cost(road, node_risk, neighbour)
            if cost is None:
                continue
            tentative = g_score[current] + cost
            if tentative < g_score.get(neighbour, math.inf):
                g_score[neighbour] = tentative
                came_from[neighbour] = (current, road_id)
                heapq.heappush(open_heap, (tentative + h(neighbour), neighbour))
    return None


def route_quality(total_cost: float, distance: float, path_risks: list[float],
                  path_congestions: list[float]) -> tuple[str, str]:
    avg_risk = sum(path_risks) / max(1, len(path_risks))
    avg_cong = sum(path_congestions) / max(1, len(path_congestions))
    if avg_risk >= 55 or (path_risks and max(path_risks) >= 75):
        return "BLOCKED", "Path crosses a high-risk zone — not recommended."
    if avg_risk >= 30 or avg_cong >= 0.6:
        return "WARNING", "Path is passable but congested or moderately risky."
    if avg_cong >= 0.35:
        return "SAFE", "Passable route with moderate traffic load."
    return "SAFE", "Lowest-cost route: clear roads, low risk exposure."


def plan_route(nodes: dict, roads: dict, start: str, goal_ids: list[str],
               node_risk: dict | None = None, walk_speed: float = 1.35,
               blocked_nodes: set[str] | None = None) -> dict | None:
    graph = build_graph(nodes, roads)
    goals = [g for g in goal_ids if g in nodes]
    if not goals or start not in nodes:
        return None
    result = a_star(graph, nodes, start, set(goals), node_risk, blocked_nodes)
    if result is None:
        return {
            "origin_id": start, "exit_id": None, "node_path": [], "road_path": [],
            "distance": 0.0, "eta_s": 0.0, "risk": 100.0, "status": "BLOCKED",
            "reason": "No passable route to any exit — all paths blocked or unsafe.",
        }
    node_path, road_path = result
    distance = sum(float(roads[r]["length"]) for r in road_path)
    risks = [float(roads[r].get("risk", 0.0)) for r in road_path] or [0.0]
    risks += [float(node_risk.get(n, 0.0)) for n in node_path] if node_risk else []
    congestions = [float(roads[r].get("congestion", 0.0)) for r in road_path]
    cost = sum(
        float(roads[r]["length"]) * (1 + 1.5 * float(roads[r].get("congestion", 0)))
        * (1 + 2 * float(roads[r].get("risk", 0)) / 100)
        for r in road_path
    )
    avg_risk = sum(risks) / max(1, len(risks))
    congestion_factor = 1.0 + (sum(congestions) / max(1, len(congestions))) * 1.5
    eta = (distance / max(0.5, walk_speed)) * congestion_factor
    status, reason = route_quality(cost, distance, risks, congestions)
    exit_id = node_path[-1]
    return {
        "origin_id": start, "exit_id": exit_id, "node_path": node_path, "road_path": road_path,
        "distance": round(distance, 1), "eta_s": round(eta, 1),
        "risk": round(avg_risk, 1), "status": status, "reason": reason,
    }


# ---------------------------------------------------------------------------
# Phase 7 — Route & Evacuation Optimization (spec §4–§17).
# Legacy helpers above (build_graph/edge_cost/a_star/route_quality/plan_route)
# stay untouched for Phase 1 consumers; Phase 7 modules are re-exported here.
# ---------------------------------------------------------------------------
from ai.optimization.graph import (  # noqa: E402
    RouteEdge,
    RouteGraph,
    RouteNode,
    get_graph,
    reset_graph_cache,
)
from ai.optimization.route_cost import (  # noqa: E402
    DEFAULT_MODE,
    MODE_KEYS,
    MODE_WEIGHTS,
    CostWeights,
    get_weights,
)
from ai.optimization.astar import astar  # noqa: E402,F401
from ai.optimization.dijkstra import dijkstra  # noqa: E402,F401
from ai.optimization.congestion import (  # noqa: E402
    congestion_label,
    detect_bottlenecks,
    exit_flow_capacity,
)
from ai.optimization.evacuation import (  # noqa: E402
    classify_ranking,
    multi_route_search,
    plan_building_evacuation,
    plan_campus_evacuation,
)
from ai.optimization.emergency_vehicle import (  # noqa: E402
    VEHICLE_KEYS,
    VEHICLE_PROFILES,
    emergency_routes_for_incident,
    plan_emergency_route,
)
from ai.optimization.optimizer import (  # noqa: E402
    STATUS_NO_SAFE_ROUTE,
    calculate_route,
    check_route_validity,
    compare_modes,
)

__all__ = [
    # legacy (Phase 1)
    "build_graph", "edge_cost", "a_star", "route_quality", "plan_route",
    # Phase 7 graph
    "RouteGraph", "RouteEdge", "RouteNode", "get_graph", "reset_graph_cache",
    # Phase 7 cost
    "CostWeights", "MODE_WEIGHTS", "MODE_KEYS", "DEFAULT_MODE", "get_weights",
    # Phase 7 search
    "astar", "dijkstra",
    # Phase 7 congestion / evacuation
    "congestion_label", "detect_bottlenecks", "exit_flow_capacity",
    "multi_route_search", "classify_ranking",
    "plan_building_evacuation", "plan_campus_evacuation",
    # Phase 7 emergency vehicle
    "VEHICLE_PROFILES", "VEHICLE_KEYS", "plan_emergency_route",
    "emergency_routes_for_incident",
    # Phase 7 optimizer
    "calculate_route", "compare_modes", "check_route_validity",
    "STATUS_NO_SAFE_ROUTE",
]
