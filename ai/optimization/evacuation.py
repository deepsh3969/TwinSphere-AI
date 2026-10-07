"""Evacuation optimisation engine (Phase 7 §8–§15, §17).

Pure functions: takes a `RouteGraph` + a plain scenario dict (built by the
backend from the effective digital-twin state) and returns structured routes —
recommended + alternatives, exit assignment, people-at-risk, bottlenecks,
EVACUATION_CRITICAL detection. No LLM output; structured data only.
"""

from __future__ import annotations

from typing import Any

from ai.optimization.astar import astar
from ai.optimization.congestion import (
    congestion_label,
    detect_bottlenecks,
    exit_flow_capacity,
    exit_pressure,
)
from ai.optimization.graph import RouteGraph
from ai.optimization.route_cost import (
    DEFAULT_MODE,
    CostWeights,
    get_weights,
    summarize,
)

SAFETY_SAFE = "SAFE"
SAFETY_WARNING = "WARNING"
SAFETY_HIGH_RISK = "HIGH_RISK"

STATUS_RECOMMENDED = "RECOMMENDED"
STATUS_ALTERNATIVE = "ALTERNATIVE"
STATUS_NOT_RECOMMENDED = "NOT_RECOMMENDED"
STATUS_BLOCKED = "BLOCKED"

EXIT_PRIMARY = "PRIMARY"
EXIT_SECONDARY = "SECONDARY"
EXIT_UNAVAILABLE = "UNAVAILABLE"

MAX_ALTERNATIVES = 3           # recommended + up to 2 alternatives (§9)
ALT_PENALTY = 1.9              # diversity pressure for subsequent searches


def _safety(risk: float, max_risk: float, congestion: float) -> str:
    if risk >= 55.0 or max_risk >= 75.0:
        return SAFETY_HIGH_RISK
    if risk >= 30.0 or congestion >= 0.6:
        return SAFETY_WARNING
    return SAFETY_SAFE


def _confidence(safety: str) -> str:
    return {SAFETY_SAFE: "HIGH", SAFETY_WARNING: "MEDIUM",
            SAFETY_HIGH_RISK: "LOW"}[safety]


def build_route_dict(graph: RouteGraph, weights: CostWeights, mode: str,
                     origin: str, node_path: list[str], road_path: list[str],
                     people: float = 0.0, exit_node: str | None = None) -> dict:
    """Metrics + classification for one concrete path (§8/§9 fields)."""
    m = summarize(road_path, graph, weights)
    safety = _safety(m["risk_score"], m["max_risk"], m["congestion_score"])
    destination = exit_node or (node_path[-1] if node_path else None)
    dest_node = graph.nodes.get(destination or "")
    origin_node = graph.nodes.get(origin)
    dest_is_exit = bool(dest_node) and (dest_node.is_exit or dest_node.kind == "EXIT")
    exit_capacity = exit_flow_capacity(dest_node) if dest_is_exit else None

    # evacuation throughput: traversal + queue pressure at the exit (§12)
    base_time = m["estimated_time"]
    queue_s = 0.0
    if exit_capacity and people > 0:
        queue_s = (people / max(1.0, exit_capacity)) * 60.0
    evac_time = round(base_time + queue_s, 1)

    reasons = []
    if safety == SAFETY_HIGH_RISK:
        reasons.append("Path crosses a high-risk segment — not recommended.")
    elif safety == SAFETY_WARNING:
        reasons.append("Passable but congested or moderately risky.")
    if dest_is_exit:
        p = exit_pressure(people, dest_node)
        if p > 1.0:
            reasons.append(f"Exit demand {int(people)} exceeds capacity "
                           f"{int(exit_capacity)} people/min.")
    return {
        "origin": origin,
        "origin_name": origin_node.name if origin_node else origin,
        "destination": destination,
        "destination_name": dest_node.name if dest_node else (destination or ""),
        "mode": mode,
        "path": list(node_path),
        "node_path": list(node_path),
        "road_path": list(road_path),
        "distance": m["distance"],
        "estimated_time": evac_time,
        "traversal_time": base_time,
        "queue_time": round(queue_s, 1),
        "risk_score": m["risk_score"],
        "max_risk": m["max_risk"],
        "congestion_score": m["congestion_score"],
        "congestion_label": congestion_label(m["congestion_score"]),
        "safety": safety,
        "status": STATUS_ALTERNATIVE,
        "confidence": _confidence(safety),
        "people": int(round(people)),
        "exit_capacity": exit_capacity,
        "reason": " ".join(reasons),
        "bottlenecks": [],
    }


def _blocked_route(origin: str, mode: str, reason: str, blocked_paths: int) -> dict:
    return {
        "origin": origin,
        "origin_name": origin,
        "destination": None,
        "destination_name": "",
        "mode": mode,
        "path": [], "node_path": [], "road_path": [],
        "distance": 0.0, "estimated_time": 0.0, "traversal_time": 0.0, "queue_time": 0.0,
        "risk_score": 100.0, "max_risk": 100.0,
        "congestion_score": 0.0, "congestion_label": "LOW",
        "safety": SAFETY_HIGH_RISK, "status": STATUS_BLOCKED,
        "confidence": "LOW", "people": 0, "exit_capacity": None,
        "reason": reason, "blocked_paths": blocked_paths, "bottlenecks": [],
    }


def multi_route_search(graph: RouteGraph, origin: str, goals: list[str],
                       weights: CostWeights, mode: str,
                       people: float = 0.0,
                       max_routes: int = MAX_ALTERNATIVES) -> list[dict]:
    """Best route + distinct alternatives (§9).

    Strategy: (1) run A* to the full goal set (best overall), then (2) run one
    search per goal/exit to surface *different* destinations, then (3) apply
    increasing edge penalties to force structurally different paths. Results are
    de-duplicated by road signature and ranked.
    """
    goals = [g for g in goals if g in graph.nodes]
    if origin not in graph.nodes or not goals:
        return [_blocked_route(origin, mode, "Origin or destinations unknown.", 0)]

    candidates: list[dict] = []
    seen: set[tuple[str, ...]] = set()

    def _try(result, exit_node: str | None) -> None:
        if result is None:
            return
        node_path, road_path = result
        sig = tuple(road_path)
        if not road_path or sig in seen:
            return
        seen.add(sig)
        candidates.append(build_route_dict(
            graph, weights, mode, origin, node_path, road_path,
            people=people, exit_node=exit_node))

    first = astar(graph, origin, set(goals), weights)
    _try(first, first[0][-1] if first else None)
    # per-exit candidates (different destination gates)
    for g in goals:
        if len(candidates) >= max_routes * 2:
            break
        _try(astar(graph, origin, {g}, weights), g)
    # penalised re-runs for structurally distinct alternatives
    used: set[str] = set()
    for _ in range(max_routes):
        penalty = {rid: ALT_PENALTY for rid in used}
        res = astar(graph, origin, set(goals), weights, penalty_edges=penalty)
        if res is None:
            break
        _try(res, res[0][-1])
        used.update(res[1])

    candidates.sort(key=lambda r: (0 if r["path"] else 1, r["risk_score"],
                                   r["estimated_time"], r["distance"]))
    return candidates[:max_routes]


def classify_ranking(routes: list[dict]) -> list[dict]:
    """Assign RECOMMENDED / ALTERNATIVE / NOT_RECOMMENDED statuses (§9)."""
    viable = [r for r in routes if r["path"] and r["safety"] != SAFETY_HIGH_RISK]
    best = None
    if viable:
        best = min(viable, key=lambda r: (r["risk_score"], r["estimated_time"]))
        best["status"] = STATUS_RECOMMENDED
        if not best["reason"]:
            best["reason"] = "Lowest-risk passable route to a viable exit."
    for r in routes:
        if not r["path"]:
            r["status"] = STATUS_BLOCKED
            if not r["reason"]:
                r["reason"] = "No passable route — all paths blocked or unsafe."
        elif r is best:
            continue
        elif r["safety"] == SAFETY_HIGH_RISK:
            r["status"] = STATUS_NOT_RECOMMENDED
            if not r["reason"]:
                r["reason"] = "Route crosses a high-risk segment."
        else:
            r["status"] = STATUS_ALTERNATIVE
            if not r["reason"]:
                r["reason"] = "Viable fallback if the recommended route degrades."
    return routes


def plan_building_evacuation(graph: RouteGraph, building: dict,
                             mode: str = DEFAULT_MODE) -> dict:
    """Full evacuation plan for one building (§8, §14, §15).

    building: {id, name, occupancy, capacity, status, exits: [node_ids],
               people_at_risk, affected}
    """
    weights = get_weights(mode)
    bid = building.get("id", "")
    origins = [e for e in building.get("exits", []) if e in graph.nodes]
    goal_exits = graph.exits()
    people = float(building.get("people_at_risk", building.get("occupancy", 0)) or 0)

    if not origins:
        plan = _blocked_route(bid, mode, "Building has no mapped exits.", 0)
        return _finalize_building(graph, building, plan, [], mode, people)

    best_routes: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for origin in origins:
        routes = multi_route_search(graph, origin, goal_exits, weights, mode, people)
        for r in routes:
            sig = tuple(r["road_path"])
            if r["road_path"] and sig not in seen:
                seen.add(sig)
                best_routes.append(r)
    best_routes.sort(key=lambda r: (0 if r["path"] else 1, r["risk_score"],
                                    r["estimated_time"]))
    classify_ranking(best_routes)
    # keep recommended + alternatives (§9), but never drop a viable exit option
    kept = [r for r in best_routes if r["status"] == STATUS_RECOMMENDED]
    kept += [r for r in best_routes if r["status"] == STATUS_ALTERNATIVE][:MAX_ALTERNATIVES - 1]
    kept += [r for r in best_routes
             if r["status"] in (STATUS_NOT_RECOMMENDED, STATUS_BLOCKED)][:1]
    if not kept and best_routes:
        kept = best_routes[:1]
    return _finalize_building(graph, building, kept[0] if kept else None, kept, mode, people)


def _finalize_building(graph: RouteGraph, building: dict, primary: dict | None,
                       routes: list[dict], mode: str, people: float) -> dict:
    bid = building.get("id", "")
    name = building.get("name", bid)
    origins = building.get("exits", [])
    viable = [r for r in routes if r["path"] and r["status"] != STATUS_BLOCKED]
    recommended = next((r for r in routes if r["status"] == STATUS_RECOMMENDED), None)

    # exit roles (§15): primary = recommended destination, secondary = next distinct
    exits_used: list[dict] = []
    if recommended:
        exits_used.append({"node_id": recommended["destination"],
                           "name": recommended["destination_name"],
                           "role": EXIT_PRIMARY, "available": True})
    for r in routes:
        if r.get("destination") and all(r["destination"] != e["node_id"] for e in exits_used):
            exits_used.append({"node_id": r["destination"], "name": r["destination_name"],
                               "role": EXIT_SECONDARY,
                               "available": r["status"] != STATUS_BLOCKED})
    for oid in origins:
        node = graph.nodes.get(oid)
        if node and all(oid != e["node_id"] for e in exits_used):
            exits_used.append({"node_id": oid, "name": node.name,
                               "role": EXIT_UNAVAILABLE if not viable else EXIT_SECONDARY,
                               "available": False})
    all_blocked = bool(origins) and not viable
    # A path that exists but crosses high-risk segments has no RECOMMENDED
    # ranking — people at risk (or heavy route risk) must still activate the
    # plan, otherwise a burning building would de-escalate to READY/STANDBY.
    has_path = any(r.get("path") for r in routes)
    max_route_risk = max((r.get("risk_score", 0.0) for r in routes), default=0.0)
    status = "EVACUATION_CRITICAL" if all_blocked else (
        "ACTIVE" if has_path and (people > 0 or max_route_risk >= 30) else "READY")

    primary_dict = primary or _blocked_route(origins[0] if origins else bid, mode,
                                             "All exits from this building are blocked.",
                                             len(graph.blocked_edges()))
    if all_blocked:
        primary_dict["reason"] = f"All exits from {name} are blocked."
        primary_dict["status"] = STATUS_BLOCKED

    # people at risk integration (§14)
    occupancy = int(building.get("occupancy", 0) or 0)
    capacity = max(1, int(building.get("capacity", 1) or 1))
    par = int(people if people else occupancy)

    return {
        "building_id": bid,
        "building_name": name,
        "status": status,
        "mode": mode,
        "people_at_risk": par,
        "occupancy": occupancy,
        "occupancy_pct": round(100.0 * occupancy / capacity, 1),
        "affected": bool(building.get("affected", False)),
        "primary_route": primary_dict,
        "routes": routes,
        "exits": exits_used,
        "primary_exit": primary_dict.get("destination_name") or "",
        "secondary_exit": next((e["name"] for e in exits_used
                                if e["role"] == EXIT_SECONDARY), ""),
        "estimated_evacuation_s": primary_dict.get("estimated_time", 0.0),
        "route_risk": primary_dict.get("risk_score", 100.0),
        "route_status": primary_dict.get("status", STATUS_BLOCKED),
        "has_safe_route": bool(viable),
        "reason": primary_dict.get("reason", ""),
    }


def plan_campus_evacuation(graph: RouteGraph, buildings: list[dict],
                           mode: str = DEFAULT_MODE) -> dict:
    """Campus-wide evacuation with exit-capacity distribution (§12–§14)."""
    # first pass: routes per building (uncapped) to learn destinations
    demand: dict[str, float] = {}
    plans: dict[str, dict] = {}
    for b in buildings:
        plan = plan_building_evacuation(graph, b, mode=mode)
        plans[b.get("id", "")] = plan
        dest = plan["primary_route"].get("destination")
        if dest and plan["has_safe_route"]:
            demand[dest] = demand.get(dest, 0.0) + float(plan["people_at_risk"])

    exits_pressure = {eid: {"exit_id": eid, "name": graph.nodes[eid].name,
                            "people": round(v, 1),
                            "capacity": exit_flow_capacity(graph.nodes[eid]),
                            "pressure": exit_pressure(v, graph.nodes[eid])}
                      for eid, v in demand.items() if eid in graph.nodes}

    flows = [{"label": p["building_name"],
              "node_path": p["primary_route"].get("node_path", []),
              "road_path": p["primary_route"].get("road_path", []),
              "people": p["people_at_risk"]}
             for p in plans.values() if p["primary_route"].get("road_path")]
    bottlenecks = detect_bottlenecks(graph, flows, exits_pressure)

    par_total = sum(p["people_at_risk"] for p in plans.values())
    critical = [p for p in plans.values() if p["status"] == "EVACUATION_CRITICAL"]
    blocked = [p for p in plans.values() if not p["has_safe_route"]]
    active = [p for p in plans.values() if p["status"] in ("ACTIVE", "EVACUATION_CRITICAL")]

    if critical or (blocked and len(blocked) == len(plans)):
        evac_status = "CRITICAL"
    elif active:
        evac_status = "ACTIVE"
    elif any(p["affected"] for p in plans.values()):
        evac_status = "STANDBY"
    else:
        evac_status = "IDLE"

    return {
        "status": evac_status,
        "mode": mode,
        "people_at_risk": par_total,
        "buildings": list(plans.values()),
        "exits": sorted(exits_pressure.values(), key=lambda e: -e["people"]),
        "bottlenecks": bottlenecks,
        "critical_buildings": [p["building_id"] for p in critical],
        "blocked_buildings": [p["building_id"] for p in blocked],
        "totals": {
            "buildings": len(plans),
            "safe_routes": sum(1 for p in plans.values() if p["has_safe_route"]),
            "blocked_routes": len(blocked),
            "bottlenecks": len(bottlenecks),
        },
    }
