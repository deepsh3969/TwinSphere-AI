"""Demo mode: scripted presentation flow + full state reset."""

from __future__ import annotations

from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.state import TwinState

DEMO_SCRIPT = [
    {"id": 1, "title": "Normal campus",
     "detail": "Live digital twin running with simulated telemetry.",
     "action": {"type": "navigate", "target": "/twin"}},
    {"id": 2, "title": "Inspect Engineering Building",
     "detail": "Open the building panel: occupancy, energy, sensors, risk.",
     "action": {"type": "select_building", "target": "eng"}},
    {"id": 3, "title": "Watch live sensor changes",
     "detail": "Metrics update in real time over the WebSocket.",
     "action": {"type": "wait", "seconds": 4}},
    {"id": 4, "title": "Review AI prediction",
     "detail": "Occupancy forecast with honest confidence.",
     "action": {"type": "show_predictions", "target": "eng"}},
    {"id": 5, "title": "Start Fire Emergency",
     "detail": "Simulation Center → Fire Emergency → Engineering Building → Start.",
     "action": {"type": "start_simulation", "target": "fire",
                "building": "eng", "params": {"intensity": 6, "wind": "E"}}},
    {"id": 6, "title": "Fire spreads through the twin",
     "detail": "Smoke, risk zones, affected areas animate in 3D.",
     "action": {"type": "watch", "seconds": 12}},
    {"id": 7, "title": "Risk rises & people-at-risk appears",
     "detail": "Risk score climbs; people-at-risk and blocked routes are computed.",
     "action": {"type": "watch", "seconds": 8}},
    {"id": 8, "title": "Routes recalculated",
     "detail": "A* re-routes evacuation away from the hazard.",
     "action": {"type": "show_routes"}},
    {"id": 9, "title": "Evacuation optimization panel",
     "detail": "Route panel: mode-weighted paths, exit capacity, bottlenecks.",
     "action": {"type": "show_route_panel"}},
    {"id": 10, "title": "AI recommendation appears",
     "detail": "Analyst explains what happened and what to do.",
     "action": {"type": "show_ai"}},
    {"id": 11, "title": "Apply recommendation",
     "detail": "Evacuation corridor becomes primary; risk on that path drops.",
     "action": {"type": "apply_recommendation"}},
    {"id": 12, "title": "Recover system",
     "detail": "Recovery progresses 0 → 100%.",
     "action": {"type": "recover"}},
    {"id": 13, "title": "SYSTEM NORMAL",
     "detail": "Campus returns to normal operation. Reset demo to replay.",
     "action": {"type": "wait", "seconds": 2}},
]


def full_reset(state: TwinState) -> dict:
    sim = state.active_sim
    if sim:
        for z in state.zones.values():
            z.fire = 0.0
            z.smoke = 0.0
            z.temperature = 24.0
            z.status = "NORMAL"
    for rid in list(state.roads):
        state.roads[rid]["blocked"] = False
        state.roads[rid]["congestion"] = 0.0
        state.roads[rid]["risk"] = 0.0
    for nid in list(state.node_risk):
        state.node_risk[nid] = 0.0
    for b in state.buildings.values():
        b.status = "OPERATIONAL"
        b.power = True
        b.backup_power = False
        b.evacuation_order = False
        b.smoke = 0.0
        b.risk = 0.0
        b.risk_level = "LOW"
    state.incidents = [i for i in state.incidents if i.get("source") != "manual"
                       and i.get("id") != "inc_seed_1"] or state.incidents[:1]
    for i in state.incidents:
        if i["status"] == "ACTIVE" and i.get("kind") in ("FIRE", "CROWD", "POWER", "ROAD_CLOSURE", "HEAT"):
            i["status"] = "RESOLVED"
    state.active_sim = None
    state.recommendations = []
    state.alerts = []
    state.status = "NORMAL"
    state.recovery_progress = 100.0
    state.anomalies = []
    tracker = getattr(state, "_anomaly_tracker", None)
    if tracker is not None:
        tracker.tracked.clear()
        tracker.pending.clear()
    # Phase 7: clear route & evacuation state so a replay starts pristine
    state.route_plan = None
    state.route_history = []
    state.evacuation = {"status": "IDLE", "buildings": [], "bottlenecks": [],
                        "people_at_risk": 0}
    state.bottleneck_ids = []
    state._route_signature = None
    state._evac_sig = None
    compute_routes(state, primary_building=None)
    compute_risk(state)
    return {"status": "reset", "metrics": state.metrics()}
