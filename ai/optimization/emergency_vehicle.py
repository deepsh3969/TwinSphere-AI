"""Emergency vehicle routing (Phase 7 §16–§17).

Separate traveller profile from pedestrian evacuation: vehicles prefer
accessibility → response time → safety → congestion, and may use edges that are
closed to pedestrians when the graph allows it (emergency_vehicle_allowed).
"""

from __future__ import annotations

from typing import Any

from ai.optimization.astar import astar
from ai.optimization.graph import RouteGraph, VEHICLE_SPEED
from ai.optimization.route_cost import CostWeights, get_weights, summarize

# Vehicle profiles: speed + which gate/depot they deploy from (§16 inputs).
VEHICLE_PROFILES: dict[str, dict[str, Any]] = {
    "fire_truck": {
        "label": "Fire Truck", "speed": VEHICLE_SPEED, "default_origin": "gate_east",
        "min_road_kind_priority": ["EMERGENCY", "PRIMARY", "INTERNAL"],
    },
    "ambulance": {
        "label": "Ambulance", "speed": VEHICLE_SPEED * 1.15, "default_origin": "gate_main",
        "min_road_kind_priority": ["EMERGENCY", "PRIMARY", "INTERNAL"],
    },
    "security": {
        "label": "Security Vehicle", "speed": VEHICLE_SPEED * 1.25,
        "default_origin": "gate_west",
        "min_road_kind_priority": ["EMERGENCY", "PRIMARY", "INTERNAL", "SERVICE"],
    },
}
VEHICLE_KEYS = tuple(VEHICLE_PROFILES)


def plan_emergency_route(graph: RouteGraph, origin: str, destination: str,
                         vehicle: str = "fire_truck") -> dict:
    """Fastest accessible route for an emergency vehicle (§16).

    Returns route, ETA, distance, risk, blocked roads avoided, restrictions.
    """
    profile = VEHICLE_PROFILES.get(vehicle, VEHICLE_PROFILES["fire_truck"])
    weights: CostWeights = get_weights("emergency")
    blocked = set(graph.blocked_edges())

    if origin not in graph.nodes:
        origin = profile["default_origin"]
    if destination not in graph.nodes:
        return {
            "status": "NO_SAFE_ROUTE",
            "reason": f"Unknown destination '{destination}'.",
            "vehicle": vehicle, "vehicle_label": profile["label"],
            "origin": origin, "destination": destination,
            "path": [], "road_path": [], "distance": 0.0, "eta_s": 0.0,
            "risk_score": 100.0, "blocked_roads_avoided": sorted(blocked),
            "access_restrictions": [],
        }

    result = astar(graph, origin, {destination}, weights)
    if result is None:
        return {
            "status": "NO_SAFE_ROUTE",
            "reason": f"No emergency-accessible route from {origin} to {destination} "
                      f"({len(blocked)} roads blocked).",
            "vehicle": vehicle, "vehicle_label": profile["label"],
            "origin": origin, "destination": destination,
            "path": [], "road_path": [], "distance": 0.0, "eta_s": 0.0,
            "risk_score": 100.0, "blocked_roads_avoided": sorted(blocked),
            "access_restrictions": [
                graph.edges[r].name or r for r in sorted(blocked)][:10],
        }

    node_path, road_path = result
    m = summarize(road_path, graph, weights)
    # vehicle traversal time uses the (congestion-aware) vehicle_time per edge
    eta = round(sum(graph.edges[r].vehicle_time for r in road_path), 1)
    # roads the vehicle could have used in free-flow but are blocked now
    avoided = sorted(blocked)
    restrictions = []
    for rid in road_path:
        e = graph.edges[rid]
        if not e.pedestrian_allowed:
            restrictions.append(f"{e.name or rid}: emergency-only")
        if e.kind and e.kind not in ("INTERNAL", "PRIMARY", "EMERGENCY"):
            restrictions.append(f"{e.name or rid}: class {e.kind}")

    status = "BLOCKED" if m["max_risk"] >= 75.0 else (
        "WARNING" if (m["risk_score"] >= 45.0 or m["congestion_score"] >= 0.6) else "SAFE")
    return {
        "status": status,
        "reason": ("Route crosses elevated risk — proceed with caution."
                   if status == "WARNING" else
                   "Fastest emergency-accessible route." if status == "SAFE"
                   else "Route crosses a critical risk segment."),
        "vehicle": vehicle, "vehicle_label": profile["label"],
        "origin": origin,
        "origin_name": graph.nodes[origin].name,
        "destination": destination,
        "destination_name": graph.nodes[destination].name,
        "path": node_path, "node_path": node_path, "road_path": road_path,
        "distance": m["distance"],
        "eta_s": eta,
        "estimated_time": eta,
        "risk_score": m["risk_score"],
        "max_risk": m["max_risk"],
        "congestion_score": m["congestion_score"],
        "blocked_roads_avoided": avoided,
        "access_restrictions": restrictions,
        "mode": "emergency",
    }


def emergency_routes_for_incident(graph: RouteGraph, incident_node: str,
                                  vehicles: list[str] | None = None) -> list[dict]:
    """One route per vehicle type from its deployment gate to the incident (§16)."""
    out = []
    for v in (vehicles or list(VEHICLE_KEYS)):
        profile = VEHICLE_PROFILES[v]
        origin = profile["default_origin"]
        if origin not in graph.nodes:
            gates = graph.exits()
            if not gates:
                continue
            origin = gates[0]
        out.append(plan_emergency_route(graph, origin, incident_node, vehicle=v))
    return out
