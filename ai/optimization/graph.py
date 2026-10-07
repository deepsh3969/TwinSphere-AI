"""Campus route graph (Phase 7 §4).

Static topology is cached once per node/road identity set; dynamic edge state
(blocked, congestion, risk, occupancy, simulation modifiers) is refreshed from
the live `TwinState` each evaluation — the graph never mutates baseline data,
it *reads* the effective state (baseline + simulation modifiers), so recovery
automatically restores open roads.

Edge record (spec §4):
    id, source, destination, distance, estimated_time, capacity,
    occupancy, congestion, risk, blocked,
    pedestrian_allowed, emergency_vehicle_allowed, simulation_modifier
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Iterable

# Calibration constants (documented in docs/ROUTING.md):
#   REF_DIST / REF_TIME normalise cost components so mode weights are comparable.
#   EDGE_CAPACITY_BASE converts the stored normalised road capacity (default 1.0)
#   into throughput (people/minute) for bottleneck maths.
#   EXIT flow = exit_capacity * EXIT_FLOW_PER_CAPACITY (gate_main 1.6 -> ~500 ppm).
REF_DIST = 100.0          # metres
REF_TIME = 60.0           # seconds
EDGE_CAPACITY_BASE = 200.0    # people/min at capacity == 1.0
EXIT_FLOW_PER_CAPACITY = 312.5  # people/min per exit_capacity unit
WALK_SPEED = 1.35         # m/s (pedestrian) — mirrors app WALK_SPEED
VEHICLE_SPEED = 8.3       # m/s (~30 km/h emergency response in campus)


@dataclass
class RouteEdge:
    id: str
    source: str
    destination: str
    distance: float
    estimated_time: float          # pedestrian traversal seconds (dynamic)
    vehicle_time: float            # emergency vehicle traversal seconds (dynamic)
    capacity: float                # people/minute throughput (dynamic)
    occupancy: float               # current load estimate (people/min equivalent)
    congestion: float              # 0..1
    risk: float                    # 0..100
    blocked: bool
    pedestrian_allowed: bool
    emergency_vehicle_allowed: bool
    kind: str = "INTERNAL"
    name: str = ""
    simulation_modifier: str | None = None   # e.g. "road_closure", "crowd_surge"
    risk_prev: float = 0.0        # last observed risk (invalidation delta helper)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["destination"] = self.destination
        return d


@dataclass
class RouteNode:
    id: str
    name: str
    x: float
    z: float
    kind: str
    is_exit: bool = False
    exit_capacity: float = 1.0
    risk: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RouteGraph:
    """Undirected weighted graph over the campus road network."""

    def __init__(self) -> None:
        self.nodes: dict[str, RouteNode] = {}
        self.edges: dict[str, RouteEdge] = {}
        self.adjacency: dict[str, list[tuple[str, str]]] = {}  # node -> [(neighbor, edge_id)]
        self._topology_key: tuple | None = None

    # ------------------------------------------------------------- topology
    def build_topology(self, nodes: dict[str, dict], roads: dict[str, dict]) -> None:
        """(Re)build static topology. Cheap and idempotent; skipped when the
        node/road identity set is unchanged (cache hit)."""
        key = (tuple(sorted(nodes)), tuple(sorted(roads)))
        if key == self._topology_key:
            return
        self.nodes = {
            nid: RouteNode(
                id=nid, name=n.get("name", nid), x=float(n.get("x", 0.0)),
                z=float(n.get("z", 0.0)), kind=str(n.get("kind", "JUNCTION")),
                is_exit=bool(n.get("is_exit", False)),
                exit_capacity=float(n.get("exit_capacity", 1.0)),
            )
            for nid, n in nodes.items()
        }
        self.edges = {}
        for rid, r in roads.items():
            a, b = str(r["from_node"]), str(r["to_node"])
            if a not in self.nodes or b not in self.nodes:
                continue
            na, nb = self.nodes[a], self.nodes[b]
            dist = float(r.get("length") or math.dist((na.x, na.z), (nb.x, nb.z)))
            self.edges[rid] = RouteEdge(
                id=rid, source=a, destination=b, distance=round(dist, 2),
                estimated_time=round(dist / WALK_SPEED, 2),
                vehicle_time=round(dist / VEHICLE_SPEED, 2),
                capacity=EDGE_CAPACITY_BASE, occupancy=0.0, congestion=0.0,
                risk=0.0, blocked=False, pedestrian_allowed=True,
                emergency_vehicle_allowed=True, kind=str(r.get("kind", "INTERNAL")),
                name=str(r.get("name", rid)),
            )
        self.adjacency = {nid: [] for nid in self.nodes}
        for rid, e in self.edges.items():
            if e.source in self.adjacency and e.destination in self.adjacency:
                self.adjacency[e.source].append((e.destination, rid))
                self.adjacency[e.destination].append((e.source, rid))
        self._topology_key = key

    # -------------------------------------------------------------- dynamic
    def refresh_dynamic(self, roads: dict[str, dict], node_risk: dict[str, float] | None = None,
                        incident_node_ids: Iterable[str] = (),
                        simulation_modifier: str | None = None) -> None:
        """Update per-edge dynamic state from the effective digital twin state."""
        node_risk = node_risk or {}
        incident_nodes = set(incident_node_ids)
        for nid, node in self.nodes.items():
            node.risk = float(node_risk.get(nid, 0.0))
        for rid, e in self.edges.items():
            r = roads.get(rid)
            if r is None:
                continue
            e.blocked = bool(r.get("blocked", False))
            e.congestion = min(1.0, max(0.0, float(r.get("congestion", 0.0))))
            endpoint_risk = max(self.nodes[e.source].risk, self.nodes[e.destination].risk)
            e.risk = min(100.0, max(float(r.get("risk", 0.0)), endpoint_risk))
            # travel time grows with congestion (crowd surge / blocked detours)
            e.estimated_time = round((e.distance / WALK_SPEED) * (1.0 + 1.5 * e.congestion), 2)
            e.vehicle_time = round((e.distance / VEHICLE_SPEED) * (1.0 + 1.0 * e.congestion), 2)
            e.capacity = round(EDGE_CAPACITY_BASE * max(0.2, float(r.get("capacity", 1.0))), 1)
            e.occupancy = round(e.congestion * e.capacity, 1)
            if e.blocked:
                e.simulation_modifier = simulation_modifier or "blocked"
            elif simulation_modifier and e.congestion > 0.0:
                e.simulation_modifier = simulation_modifier
            else:
                e.simulation_modifier = None
        # incident proximity: mark edges touching incident nodes as elevated
        for nid in incident_nodes:
            for _, rid in self.adjacency.get(nid, []):
                self.edges[rid].risk = max(self.edges[rid].risk, 70.0)

    # --------------------------------------------------------------- access
    def neighbors(self, nid: str) -> list[tuple[str, str]]:
        return self.adjacency.get(nid, [])

    def edge(self, rid: str) -> RouteEdge | None:
        return self.edges.get(rid)

    def exits(self) -> list[str]:
        return [n.id for n in self.nodes.values() if n.is_exit]

    def gate_like(self) -> list[str]:
        return [n.id for n in self.nodes.values()
                if n.is_exit or n.kind in ("GATE", "ASSEMBLY")]

    def blocked_edges(self) -> list[str]:
        return [rid for rid, e in self.edges.items() if e.blocked]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "counts": {"nodes": len(self.nodes), "edges": len(self.edges)},
            "static": True,
        }


# ------------------------------------------------------------------- cache
_GRAPH: RouteGraph | None = None


def get_graph(nodes: dict[str, dict], roads: dict[str, dict]) -> RouteGraph:
    """Return the process-wide graph instance (topology cached, dynamics fresh)."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = RouteGraph()
    _GRAPH.build_topology(nodes, roads)
    return _GRAPH


def reset_graph_cache() -> None:
    global _GRAPH
    _GRAPH = None
