"""Evacuation / emergency route optimisation service (A*)."""

from __future__ import annotations

from ai.optimization import plan_route
from app.services.state import TwinState, WALK_SPEED

EXIT_NAMES = {}


def _exit_name(state: TwinState, node_id: str | None) -> str:
    if not node_id:
        return ""
    return state.nodes.get(node_id, {}).get("name", node_id)


def compute_routes(state: TwinState, primary_building: str | None = None) -> list[dict]:
    exits = [nid for nid, n in state.nodes.items() if n.get("is_exit")]
    routes: list[dict] = []
    targets = list(state.buildings.keys())
    if primary_building and primary_building in state.buildings:
        targets = [primary_building] + [b for b in targets if b != primary_building]

    for bid in targets:
        building = state.buildings[bid]
        origin_nodes = state.exits_for(bid)
        best: dict | None = None
        for origin in origin_nodes:
            plan = plan_route(state.nodes, state.roads, origin, exits,
                              node_risk=state.node_risk, walk_speed=WALK_SPEED)
            if plan is None:
                continue
            if plan["status"] == "BLOCKED" and not plan["node_path"]:
                if best is None:
                    best = plan
                continue
            if best is None or _rank(plan) < _rank(best):
                best = plan
        if best is None:
            best = {
                "origin_id": origin_nodes[0] if origin_nodes else "", "exit_id": None,
                "node_path": [], "road_path": [], "distance": 0.0, "eta_s": 0.0,
                "risk": 100.0, "status": "BLOCKED",
                "reason": "No passable route — all exits unreachable.",
            }
        best = dict(best)
        best["id"] = f"route_{bid}"
        best["building_id"] = bid
        best["building_name"] = building.name
        best["exit_name"] = _exit_name(state, best.get("exit_id"))
        best["occupancy"] = building.occupancy
        best["evac_time_s"] = round(
            best["eta_s"] * (1.0 + building.occupancy / max(1, building.capacity) * 0.8), 1
        )
        # colour rule: SAFE -> green, WARNING -> yellow, BLOCKED -> red
        routes.append(best)

    routes.sort(key=lambda r: (0 if r["building_id"] == primary_building else 1))
    state.routes = routes
    return routes


def _rank(plan: dict) -> tuple:
    status_rank = {"SAFE": 0, "WARNING": 1, "BLOCKED": 2}.get(plan["status"], 3)
    return (status_rank, plan.get("risk", 100), plan.get("evac_time_s", plan.get("eta_s", 999)))


def route_report(state: TwinState) -> dict:
    safe = [r for r in state.routes if r["status"] == "SAFE"]
    warning = [r for r in state.routes if r["status"] == "WARNING"]
    blocked = [r for r in state.routes if r["status"] == "BLOCKED"]
    return {
        "safe": [{"building": r["building_name"], "exit": r["exit_name"], "eta": r["evac_time_s"]}
                 for r in safe],
        "warning": [{"building": r["building_name"], "exit": r["exit_name"], "eta": r["evac_time_s"]}
                    for r in warning],
        "blocked": [{"building": r["building_name"], "reason": r["reason"]} for r in blocked],
        "total": len(state.routes),
    }
