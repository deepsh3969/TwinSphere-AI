"""Congestion, exit capacity and bottleneck detection (Phase 7 §12–§13).

Structured data only — no LLM recommendations. Every bottleneck carries a
location, severity, estimated demand, capacity and a structured recommendation.
"""

from __future__ import annotations

from typing import Any, Iterable

from ai.optimization.graph import EXIT_FLOW_PER_CAPACITY, RouteGraph, RouteNode

SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"

# Structured recommendation vocabulary (kept deterministic for tests/Phase 9).
RECO_DISTRIBUTE = "Distribute evacuation toward an alternative gate"
RECO_WAIT = "Hold occupants until congestion clears"
RECO_REROUTE = "Reroute around the congested segment"


def exit_flow_capacity(node: RouteNode) -> float:
    """People/minute an exit can discharge (gate_main 1.6 ≈ 500 ppm)."""
    return round(node.exit_capacity * EXIT_FLOW_PER_CAPACITY, 1)


def exit_pressure(people: float, node: RouteNode) -> float:
    """0..1+ ratio of demand vs discharge capacity over a 1-minute horizon."""
    cap = exit_flow_capacity(node)
    return round(people / max(1.0, cap), 2)


def assign_exits(graph: RouteGraph, demand_by_origin: dict[str, float],
                 candidate_exits: Iterable[str] | None = None) -> dict[str, dict]:
    """Distribute evacuation demand across exits respecting capacity (§12).

    Greedy assignment: each origin (building exit node) picks the exit with the
    lowest projected pressure among its viable options — computed by the caller
    via candidate route costs. Returns {exit_id: {people, capacity, pressure}}.
    """
    exits = list(candidate_exits or graph.exits())
    out: dict[str, dict] = {}
    for eid in exits:
        node = graph.nodes.get(eid)
        if node is None:
            continue
        out[eid] = {"exit_id": eid, "name": node.name, "people": 0.0,
                    "capacity": exit_flow_capacity(node), "pressure": 0.0}
    for _, people in demand_by_origin.items():
        if not out:
            break
        target = min(out.values(), key=lambda e: e["pressure"])
        target["people"] += float(people)
        target["pressure"] = round(target["people"] / max(1.0, target["capacity"]), 2)
    return out


def detect_bottlenecks(graph: RouteGraph, route_flows: list[dict[str, Any]],
                       exits_pressure: dict[str, dict]) -> list[dict]:
    """Detect bottlenecks across computed routes (§13).

    route_flows: [{"node_path": [...], "road_path": [...], "people": N, "label": str}]
    Returns structured bottleneck dicts sorted by severity.
    """
    edge_load: dict[str, float] = {}
    edge_labels: dict[str, set[str]] = {}
    node_load: dict[str, float] = {}
    for rf in route_flows:
        people = float(rf.get("people", 0) or 0)
        for rid in rf.get("road_path", []):
            edge_load[rid] = edge_load.get(rid, 0.0) + people
            edge_labels.setdefault(rid, set()).add(str(rf.get("label", "")))
        for nid in rf.get("node_path", []):
            node_load[nid] = node_load.get(nid, 0.0) + people

    bottlenecks: list[dict] = []
    for rid, load in edge_load.items():
        edge = graph.edge(rid)
        if edge is None:
            continue
        pressure = load / max(1.0, edge.capacity)
        risk_high = edge.risk >= 60.0
        if pressure <= 1.0 and not risk_high and edge.congestion < 0.7:
            continue
        if pressure > 1.0 or edge.congestion >= 0.7:
            severity = SEVERITY_HIGH if (pressure > 1.5 or edge.congestion >= 0.85) else SEVERITY_MEDIUM
            recommendation = RECO_DISTRIBUTE
        else:
            severity = SEVERITY_MEDIUM
            recommendation = RECO_REROUTE
        if risk_high and severity == SEVERITY_MEDIUM:
            severity = SEVERITY_HIGH
            recommendation = RECO_REROUTE
        bottlenecks.append({
            "location": edge.name or rid,
            "location_id": rid,
            "kind": "EDGE",
            "severity": severity,
            "estimated_people": int(round(load)),
            "capacity": int(round(edge.capacity)),
            "congestion": round(edge.congestion, 2),
            "risk": round(edge.risk, 1),
            "recommendation": recommendation,
            "shared_by": sorted(l for l in edge_labels.get(rid, set()) if l),
        })

    for eid, info in exits_pressure.items():
        if info["pressure"] <= 1.0:
            continue
        node = graph.nodes.get(eid)
        severity = SEVERITY_HIGH if info["pressure"] > 1.5 else SEVERITY_MEDIUM
        bottlenecks.append({
            "location": node.name if node else eid,
            "location_id": eid,
            "kind": "EXIT",
            "severity": severity,
            "estimated_people": int(round(info["people"])),
            "capacity": int(round(info["capacity"])),
            "congestion": round(min(1.0, info["pressure"] - 1.0), 2),
            "risk": round(node.risk if node else 0.0, 1),
            "recommendation": RECO_DISTRIBUTE,
            "shared_by": ["exit capacity"],
        })

    # narrow-corridor heuristic: a junction carrying very high shared load
    for nid, load in node_load.items():
        node = graph.nodes.get(nid)
        if node is None or node.is_exit:
            continue
        if load < 400:
            continue
        if any(b["location_id"] == nid for b in bottlenecks):
            continue
        bottlenecks.append({
            "location": node.name or nid,
            "location_id": nid,
            "kind": "NODE",
            "severity": SEVERITY_MEDIUM,
            "estimated_people": int(round(load)),
            "capacity": 400,
            "congestion": 0.7,
            "risk": round(node.risk, 1),
            "recommendation": RECO_REROUTE,
            "shared_by": ["junction"],
        })

    order = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}
    bottlenecks.sort(key=lambda b: (order.get(b["severity"], 3), -b["estimated_people"]))
    return bottlenecks


def congestion_label(score: float) -> str:
    if score >= 0.7:
        return "SEVERE"
    if score >= 0.45:
        return "HIGH"
    if score >= 0.25:
        return "MODERATE"
    return "LOW"
