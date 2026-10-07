"""Route optimizer orchestrator (Phase 7 §5–§7, §21, §37).

Single entry point for point-to-point calculation, mode comparison and route
validity checks. Stateless — graph + context are provided by the caller
(backend `route_service`), so this stays pure and testable.
"""

from __future__ import annotations

from typing import Any, Iterable

from ai.optimization.astar import astar
from ai.optimization.dijkstra import dijkstra
from ai.optimization.evacuation import (
    SAFETY_HIGH_RISK,
    STATUS_ALTERNATIVE,
    STATUS_BLOCKED,
    STATUS_NOT_RECOMMENDED,
    STATUS_RECOMMENDED,
    build_route_dict,
    classify_ranking,
    multi_route_search,
)
from ai.optimization.graph import RouteGraph
from ai.optimization.route_cost import DEFAULT_MODE, MODE_KEYS, get_weights

STATUS_NO_SAFE_ROUTE = "NO_SAFE_ROUTE"
DEFAULT_COMPARE_MODES = ("shortest", "fastest", "safest", "balanced")


def calculate_route(graph: RouteGraph, origin: str, destination: str,
                    mode: str = DEFAULT_MODE, people: float = 0.0,
                    alternatives: int = 0) -> dict:
    """Point-to-point route (§25). Validates endpoints, returns one route or
    NO_SAFE_ROUTE with structured failure info (§37)."""
    mode = mode if mode in MODE_KEYS else DEFAULT_MODE
    weights = get_weights(mode)

    if origin not in graph.nodes:
        return {"status": STATUS_NO_SAFE_ROUTE,
                "reason": f"Unknown origin node '{origin}'.",
                "origin": origin, "destination": destination, "mode": mode,
                "path": [], "blocked_paths": 0}
    if destination not in graph.nodes:
        return {"status": STATUS_NO_SAFE_ROUTE,
                "reason": f"Unknown destination node '{destination}'.",
                "origin": origin, "destination": destination, "mode": mode,
                "path": [], "blocked_paths": 0}

    if origin == destination:
        r = build_route_dict(graph, weights, mode, origin, [origin], [], people)
        r["status"] = STATUS_RECOMMENDED
        return r

    result = astar(graph, origin, {destination}, weights)
    if result is None:
        blocked_n = len(graph.blocked_edges())
        return {
            "status": STATUS_NO_SAFE_ROUTE,
            "reason": f"No passable route from {origin} to {destination}.",
            "origin": origin, "destination": destination, "mode": mode,
            "path": [], "node_path": [], "road_path": [],
            "distance": 0.0, "estimated_time": 0.0, "risk_score": 100.0,
            "congestion_score": 0.0,
            "blocked_paths": blocked_n,
            "blocked_edges": graph.blocked_edges()[:20],
            "available_alternatives": [e for e in graph.exits() if e != origin][:5],
        }

    node_path, road_path = result
    route = build_route_dict(graph, weights, mode, origin, node_path, road_path,
                             people=people, exit_node=destination)
    if route["safety"] == SAFETY_HIGH_RISK:
        route["status"] = STATUS_NOT_RECOMMENDED
        route["reason"] = route["reason"] or "Route crosses a high-risk segment."
    else:
        route["status"] = STATUS_RECOMMENDED
        route["reason"] = route["reason"] or "Passable route under current conditions."

    if alternatives > 0:
        alts = multi_route_search(graph, origin, [destination], weights, mode,
                                  people=people, max_routes=alternatives + 1)
        distinct = [a for a in alts
                    if tuple(a["road_path"]) != tuple(road_path)][:alternatives]
        combined = classify_ranking([route] + distinct)
        # the activated plan must be the classified RECOMMENDED row when one
        # exists (classify can promote a distinct path over the A* primary)
        best_i = next((i for i, r in enumerate(combined)
                       if r["status"] == STATUS_RECOMMENDED), 0)
        route = combined.pop(best_i)
        route["alternatives"] = combined
    return route


def compare_modes(graph: RouteGraph, origin: str, destination: str,
                  modes: Iterable[str] = DEFAULT_COMPARE_MODES,
                  people: float = 0.0) -> dict:
    """Mode comparison table (§21): shortest/fastest/safest/balanced rows."""
    rows = []
    for mode in modes:
        if mode not in MODE_KEYS:
            continue
        route = calculate_route(graph, origin, destination, mode=mode, people=people)
        rows.append({
            "mode": mode,
            "status": route.get("status", STATUS_NO_SAFE_ROUTE),
            "distance": route.get("distance", 0.0),
            "estimated_time": route.get("estimated_time", 0.0),
            "risk_score": route.get("risk_score", 100.0),
            "congestion_score": route.get("congestion_score", 0.0),
            "safety": route.get("safety", SAFETY_HIGH_RISK),
            "path": route.get("path", []),
        })
    # RECOMMENDED = lowest risk among viable, tie-break on time; full ties fall
    # back to mode preference (balanced > safest > fastest > shortest).
    pref = {"balanced": 0, "safest": 1, "fastest": 2, "shortest": 3, "emergency": 4}
    viable = [r for r in rows if r["status"] not in (STATUS_NO_SAFE_ROUTE, STATUS_BLOCKED)
              and r["safety"] != SAFETY_HIGH_RISK]
    if viable:
        best = min(viable, key=lambda r: (r["risk_score"], r["estimated_time"],
                                          pref.get(r["mode"], 9)))
        best["recommended"] = True
    return {"origin": origin, "destination": destination, "rows": rows,
            "recommended_mode": next((r["mode"] for r in rows if r.get("recommended")), None)}


def check_route_validity(graph: RouteGraph, road_path: list[str],
                         node_path: list[str], risk_delta_limit: float = 25.0,
                         prev_edge_risk: dict[str, float] | None = None,
                         congestion_limit: float = 0.75) -> dict:
    """Route validity check (§10) — cheap invalidation reasons list."""
    reasons: list[str] = []
    blocked_paths: list[str] = []
    for rid in road_path:
        edge = graph.edge(rid)
        if edge is None:
            reasons.append("edge_missing")
            blocked_paths.append(rid)
            continue
        if edge.blocked:
            reasons.append("edge_blocked")
            blocked_paths.append(rid)
            continue
        if prev_edge_risk is not None and rid in prev_edge_risk:
            if edge.risk - float(prev_edge_risk[rid]) >= risk_delta_limit:
                reasons.append("risk_increased")
            elif float(prev_edge_risk[rid]) - edge.risk >= risk_delta_limit:
                reasons.append("risk_decreased")
        if edge.congestion >= congestion_limit:
            reasons.append("congestion_increased")
    if node_path:
        dest = graph.nodes.get(node_path[-1])
        if dest is not None and not dest.is_exit and dest.kind not in ("EXIT", "GATE", "ASSEMBLY"):
            reasons.append("destination_unavailable")
        elif dest is not None and dest.risk >= 75.0:
            reasons.append("exit_unavailable")
    # de-duplicate, preserve order
    seen: set[str] = set()
    reasons = [r for r in reasons if not (r in seen or seen.add(r))]
    blocking = {"edge_blocked", "edge_missing", "exit_unavailable",
                "destination_unavailable", "risk_increased"}
    return {
        "valid": not any(r in blocking for r in reasons),
        "reasons": reasons,
        "blocked_paths": blocked_paths,
    }


def reference_dijkstra(graph: RouteGraph, origin: str, destination: str,
                       mode: str = DEFAULT_MODE):
    """Ground-truth reference (tests + audit): same cost model, no heuristic."""
    if origin not in graph.nodes or destination not in graph.nodes:
        return None
    return dijkstra(graph, origin, {destination}, get_weights(mode))
