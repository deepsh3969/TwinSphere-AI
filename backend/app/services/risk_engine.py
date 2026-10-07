"""Risk engine service: derives building + campus risk from twin state.

Raw weighted scores feed physics, persistence and snapshots (Phase 1-4
behaviour). The Phase 5 stabilised view (EMA smoothing + min-delta +
level hysteresis) is published into `state.risk_published` for the AI
surfaces: /api/risk `published` block, risk.update WS events and the
risk_scores history.
"""

from __future__ import annotations

from ai.risk import RiskStability, building_risk, campus_risk, hierarchy_risk
from app.core.config import settings
from app.services.state import TwinState


def _stability(state: TwinState) -> RiskStability:
    if state.risk_stability is None:
        state.risk_stability = RiskStability(
            alpha=settings.RISK_SMOOTHING_ALPHA, min_delta=settings.RISK_MIN_DELTA)
    return state.risk_stability


def refresh_risk_hierarchy(state: TwinState, sensor_status: dict[str, dict]) -> None:
    """Campus/building/floor/zone/sensor detail (AI-cycle cadence)."""
    try:
        state.risk_hierarchy = hierarchy_risk(
            buildings=state.buildings, building_results=state.building_risk,
            zones=state.zones, sensors=state.sensors,
            sensor_status=sensor_status)
    except Exception:
        state.risk_hierarchy = getattr(state, "risk_hierarchy", None)


def publish_stabilised_risk(state: TwinState, sensor_status: dict[str, dict] | None = None) -> dict:
    """Run smoothing/hysteresis over raw building + campus scores."""
    stab = _stability(state)
    published: dict[str, dict] = {}
    published["campus"] = stab.update(
        "campus", state.risk.get("score", 0.0),
        factors=state.risk.get("factors", []),
        explanation=state.risk.get("explanation", ""),
        level=state.risk.get("level"),
    )
    for bid, res in state.building_risk.items():
        published[bid] = stab.update(
            bid, res.get("score", 0.0), factors=res.get("factors", []),
            explanation=res.get("explanation", ""), level=res.get("level"))
    state.risk_published = published
    if sensor_status is not None:
        refresh_risk_hierarchy(state, sensor_status)
    return published


def compute_risk(state: TwinState) -> dict:
    building_results: dict[str, dict] = {}
    anomaly_by_building: dict[str, float] = {}
    for a in state.anomalies:
        bid = a.get("building_id")
        if bid:
            anomaly_by_building[bid] = max(anomaly_by_building.get(bid, 0.0), float(a.get("score", 0)))

    for b in state.buildings.values():
        zones = [z for z in state.zones.values() if z.building_id == b.id]
        burning = [z for z in zones if z.status == "FIRE"]
        exits = state.exits_for(b.id)
        # an exit node is blocked when it is inside a burning/affected zone catchment
        blocked = 0
        for ex in exits:
            node = state.nodes.get(ex)
            if not node:
                continue
            near_fire = any(
                z.status in ("FIRE", "SMOKE") and abs(z.local_x + b.position_x - node["x"]) < b.size_x * 0.75
                and abs(z.local_z + b.position_z - node["z"]) < b.size_z * 0.75
                for z in zones
            )
            if near_fire or state.node_risk.get(ex, 0) >= 75:
                blocked += 1
        result = building_risk(
            occupancy=b.occupancy, capacity=b.capacity, temperature=b.temperature,
            smoke=b.smoke, air_quality=b.air_quality,
            fire_fraction=len(burning) / max(1, len(zones)),
            burning_zones=len(burning), blocked_exits=blocked, total_exits=len(exits),
            anomaly_score=anomaly_by_building.get(b.id, 0.0),
            power_ok=b.power, status=b.status,
        )
        b.risk = result["score"]
        b.risk_level = result["level"]
        building_results[b.id] = result
        state.building_risk[b.id] = result

    blocked_roads = sum(1 for r in state.roads.values() if r["blocked"])
    active_incidents = len([i for i in state.incidents if i["status"] == "ACTIVE"])
    outdoor = max((s.value for s in state.sensors.values() if s.id == "temp_outdoor"), default=26.0)
    result = campus_risk(building_results, blocked_roads=blocked_roads,
                         active_incidents=active_incidents, outdoor_temp=outdoor)
    state.risk = result

    for nid, node in state.nodes.items():
        nr = 0.0
        # building exits carry kind="EXIT" without an is_exit flag (campus seed);
        # gates carry is_exit=True. Both must propagate building risk outward.
        if node.get("is_exit") or node.get("kind") == "EXIT":
            for b in state.buildings.values():
                for ex in state.exits_for(b.id):
                    if ex == nid:
                        nr = max(nr, b.risk)
        state.node_risk[nid] = round(max(state.node_risk.get(nid, 0.0) * 0.85, nr), 1)

    for rid, road in state.roads.items():
        a_risk = state.node_risk.get(road["from_node"], 0.0)
        b_risk = state.node_risk.get(road["to_node"], 0.0)
        target_risk = max(a_risk, b_risk)
        road["risk"] = round(max(road.get("risk", 0.0) * 0.8, target_risk), 1)

    # Phase 5: stabilised publication for AI surfaces (raw stays authoritative)
    try:
        publish_stabilised_risk(state)
    except Exception:
        pass
    return result
