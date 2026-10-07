"""Operator actions: applying AI recommendations to the digital twin."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.optimization_service import compute_routes
from app.services.state import TwinState


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def get_recommendation(state: TwinState, rec_id: str) -> dict:
    rec = next((r for r in state.recommendations if r["id"] == rec_id), None)
    if rec is None:
        raise ValueError("Recommendation not found")
    return rec


def apply_recommendation(state: TwinState, rec_id: str) -> dict:
    rec = get_recommendation(state, rec_id)
    if rec["status"] == "APPLIED":
        return rec
    action = rec.get("action", "")
    payload = rec.get("payload", {})
    applied_detail = ""

    if action == "evacuate":
        bid = payload.get("building_id")
        b = state.buildings.get(bid)
        if b:
            b.evacuation_order = True
            b.status = "EVACUATING"
        route = next((r for r in state.routes if r.get("id") == payload.get("route_id")), None)
        if route:
            for rid in route.get("road_path", []):
                if rid in state.roads:
                    state.roads[rid]["risk"] = max(0.0, state.roads[rid]["risk"] * 0.45)
                    state.roads[rid]["congestion"] = min(1.0, state.roads[rid].get("congestion", 0.0) * 0.7)
            for nid in route.get("node_path", []):
                state.node_risk[nid] = max(0.0, state.node_risk.get(nid, 0.0) * 0.45)
            applied_detail = f"Primary evacuation corridor set: {route.get('building_name')} → {route.get('exit_name')}"
        compute_routes(state, primary_building=bid)
        state.alerts.append({
            "id": f"alert_{len(state.alerts) + 1}", "level": "INFO",
            "title": "Evacuation ordered",
            "message": applied_detail or f"Evacuation ordered for {bid}",
            "entity_id": bid, "created_at": _utc().isoformat(), "acknowledged": False,
        })

    elif action == "dispatch_response":
        sim = state.active_sim
        if sim and sim.scenario == "fire":
            sim.params["burn_rate"] = float(payload.get("burn_rate", 0.35))
            applied_detail = "Fire response dispatched — suppression factor active (burn rate reduced 65%)."
            sim.events.append({"t": sim.t, "kind": "response_dispatched",
                               "message": applied_detail, "data": {}})

    elif action == "activate_backup":
        b = state.buildings.get(payload.get("building_id", ""))
        if b:
            b.backup_power = True
            b.energy = max(b.energy, b.capacity * 0.006)
            applied_detail = f"Backup supply online for {b.name}; life-safety loads prioritised."

    elif action == "throttle_entry":
        sim = state.active_sim
        if sim and sim.scenario == "crowd":
            sim.params["occupancy_increase"] = min(
                float(sim.params.get("occupancy_increase", 40)), 8.0)
            applied_detail = "Entry metering active — occupancy growth throttled."

    elif action == "reroute_traffic":
        for r in state.roads.values():
            if not r["blocked"]:
                r["congestion"] = max(0.0, r.get("congestion", 0.0) - 0.25)
        compute_routes(state, primary_building=state.active_sim.target_id if state.active_sim else None)
        applied_detail = "Service traffic rerouted via ring road; congestion rebalanced."

    elif action == "heat_mitigation":
        applied_detail = "Pre-cooling schedule applied to high-occupancy buildings."
        state.alerts.append({
            "id": f"alert_{len(state.alerts) + 1}", "level": "INFO", "title": "Heat mitigation active",
            "message": applied_detail, "entity_id": None,
            "created_at": _utc().isoformat(), "acknowledged": False,
        })

    elif action == "hold_in_place":
        applied_detail = "Hold-in-place protocol published to affected zones."

    elif action == "monitor":
        applied_detail = "Monitoring schedule acknowledged."

    else:
        applied_detail = f"Action '{action}' acknowledged."

    rec["status"] = "APPLIED"
    rec["applied_at"] = _utc().isoformat()
    rec["applied_detail"] = applied_detail

    try:
        from app.services.persistence import save_recommendation_update
        save_recommendation_update(rec)
    except Exception:
        pass
    return rec
