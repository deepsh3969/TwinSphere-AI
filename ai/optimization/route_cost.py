"""Route cost function (Phase 7 §6–§7).

TOTAL COST = distance_weight * normalised_distance
           + time_weight     * normalised_time
           + risk_weight     * normalised_risk
           + congestion_weight * congestion
           + capacity_weight * capacity_penalty

Blocked edges (or edges disallowed for the traveller profile) are effectively
infinite. Weights are configurable per mode; risk strongly influences emergency
routing so a slightly longer but significantly safer route wins.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai.optimization.graph import REF_DIST, REF_TIME, RouteEdge

if TYPE_CHECKING:
    from ai.optimization.graph import RouteGraph

TRAVELER_PEDESTRIAN = "pedestrian"
TRAVELER_EMERGENCY = "emergency_vehicle"


@dataclass(frozen=True)
class CostWeights:
    distance: float
    time: float
    risk: float
    congestion: float
    capacity: float
    traveler: str = TRAVELER_PEDESTRIAN
    label: str = ""


# §7 — five route modes. These are the single source of truth for mode weights;
# the API validates `mode` against MODE_KEYS.
MODE_WEIGHTS: dict[str, CostWeights] = {
    "shortest": CostWeights(distance=1.0, time=0.0, risk=0.0, congestion=0.0,
                            capacity=0.0, label="Shortest distance"),
    "fastest": CostWeights(distance=0.1, time=1.0, risk=0.0, congestion=0.3,
                           capacity=0.1, label="Fastest travel time"),
    "safest": CostWeights(distance=0.2, time=0.1, risk=1.0, congestion=0.2,
                          capacity=0.1, label="Safest path"),
    "balanced": CostWeights(distance=0.4, time=0.5, risk=0.8, congestion=0.4,
                            capacity=0.2, label="Balanced (default)"),
    "emergency": CostWeights(distance=0.2, time=1.0, risk=0.6, congestion=0.7,
                             capacity=0.3, traveler=TRAVELER_EMERGENCY,
                             label="Emergency vehicle response"),
}
MODE_KEYS = tuple(MODE_WEIGHTS)
DEFAULT_MODE = "balanced"


def get_weights(mode: str) -> CostWeights:
    return MODE_WEIGHTS.get(mode, MODE_WEIGHTS[DEFAULT_MODE])


def edge_cost(edge: RouteEdge, weights: CostWeights,
              capacity_demand: float = 0.0) -> float:
    """Weighted traversal cost for one edge under the given mode.

    Returns math.inf when the edge is blocked or not allowed for the traveller
    (blocked_penalty — blocked edges must never be chosen).
    """
    if edge.blocked:
        return math.inf
    if weights.traveler == TRAVELER_EMERGENCY and not edge.emergency_vehicle_allowed:
        return math.inf
    if weights.traveler == TRAVELER_PEDESTRIAN and not edge.pedestrian_allowed:
        return math.inf

    dist_n = edge.distance / REF_DIST
    time_n = (edge.vehicle_time if weights.traveler == TRAVELER_EMERGENCY
              else edge.estimated_time) / REF_TIME
    risk_n = edge.risk / 100.0
    cong_n = edge.congestion
    # capacity penalty: requested flow over edge throughput (0 when within capacity)
    load = max(edge.occupancy, capacity_demand)
    cap_n = max(0.0, (load / max(1.0, edge.capacity)) - 1.0)

    return (weights.distance * dist_n
            + weights.time * time_n
            + weights.risk * risk_n
            + weights.congestion * cong_n
            + weights.capacity * cap_n)


def heuristic(graph: "RouteGraph", node_id: str, goals: set[str], weights: CostWeights) -> float:
    """Admissible heuristic: straight-line distance * distance weight.

    Every other cost component is non-negative, and euclidean distance never
    exceeds the true path distance, so A* stays optimal. When the mode ignores
    distance (weight 0) the heuristic degrades to Dijkstra automatically.
    """
    w = weights.distance
    if w <= 0.0 or not goals:
        return 0.0
    n = graph.nodes.get(node_id)
    if n is None:
        return 0.0
    best = math.inf
    for g in goals:
        gn = graph.nodes.get(g)
        if gn is None:
            continue
        d = math.dist((n.x, n.z), (gn.x, gn.z))
        if d < best:
            best = d
    return (best / REF_DIST) * w if best < math.inf else 0.0


def summarize(edge_ids: list[str], graph: "RouteGraph", weights: CostWeights) -> dict:
    """Aggregate metrics for a path (distance, time, risk, congestion, cost)."""
    distance = time_s = risk = congestion = 0.0
    max_risk = 0.0
    n = 0
    for rid in edge_ids:
        e = graph.edges.get(rid)
        if e is None:
            continue
        distance += e.distance
        time_s += e.vehicle_time if weights.traveler == TRAVELER_EMERGENCY else e.estimated_time
        risk += e.risk
        max_risk = max(max_risk, e.risk)
        congestion += e.congestion
        n += 1
    n = max(1, n)
    return {
        "distance": round(distance, 1),
        "estimated_time": round(time_s, 1),
        "risk_score": round(risk / n, 1),
        "max_risk": round(max_risk, 1),
        "congestion_score": round(congestion / n, 1),
    }
