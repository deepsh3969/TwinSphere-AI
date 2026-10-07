"""Simulation engine: fire, crowd surge, power failure, road closure, extreme temperature.

Lifecycle: CREATED -> RUNNING <-> PAUSED -> AWAITING_RECOVERY -> RECOVERING -> COMPLETED
Also: RESET (back to CREATED). Every transition is persisted and broadcast.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ai.simulation import (
    building_status,
    close_road,
    intensity_label,
    power_failure_effects,
    recovery_percent,
    reopen_road,
    road_impact,
    smoke_severity,
    validate_fire_params,
    zone_totals,
)
from ai.simulation import ignite, step_fire, suppress
from app.core.database import SessionLocal
from app.models.entities import Incident, Simulation, SimulationEvent, SystemAlert
from app.services.optimization_service import compute_routes
from app.services.state import SimulationState, TwinState

SCENARIOS = {
    "fire": {"label": "Fire Emergency", "duration": 330.0, "recover": 130.0},
    "crowd": {"label": "Crowd Surge", "duration": 300.0, "recover": 90.0},
    "power": {"label": "Power Failure", "duration": 240.0, "recover": 110.0},
    "road": {"label": "Road Closure", "duration": 300.0, "recover": 80.0},
    "temperature": {"label": "Extreme Temperature", "duration": 360.0, "recover": 120.0},
}

FIRE_TIMELINE = [
    (0, "ignition", "T+0 — Fire begins."),
    (20, "smoke_detected", "T+1 — Smoke detected by ceiling sensors."),
    (45, "risk_zone_expanding", "T+2 — Risk zone expands beyond ignition floor."),
    (75, "zones_affected", "T+3 — Adjacent zones affected by heat and smoke."),
    (110, "routes_recalculated", "T+4 — Evacuation routes recalculated around hazard."),
    (150, "people_at_risk", "T+5 — People-at-risk calculated."),
    (190, "route_optimized", "T+6 — Optimal evacuation route generated."),
    (240, "response_recommended", "T+7 — Emergency response recommendation generated."),
]


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def queue_sim_event(state: TwinState, event: str, data: dict) -> None:
    """Phase 6 §27 — queue a typed `simulation.*` WS event for the runtime loop."""
    state.pending_sim_events.append({"event": event, "data": data})
    if len(state.pending_sim_events) > 60:
        del state.pending_sim_events[: len(state.pending_sim_events) - 60]


def _validate(state: TwinState, scenario: str, target_id: str | None,
              params: dict) -> dict:
    """§52 — scenario/target/parameter validation. Raises ValueError."""
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'. Valid: {list(SCENARIOS)}")
    if target_id and scenario != "road" and target_id not in state.buildings:
        raise ValueError(f"Target building '{target_id}' not found")
    if scenario in ("fire", "crowd", "power") and not target_id:
        raise ValueError(f"Scenario '{scenario}' requires a target building")
    if scenario == "fire":
        # accept `zone_id` as an alias for `ignition_zone`
        if "zone_id" in params and not params.get("ignition_zone"):
            params["ignition_zone"] = params.pop("zone_id")
        zones = {z.id: z for z in state.zones.values() if target_id is None or z.building_id == target_id}
        params = validate_fire_params(params, zones, target_id)
    elif scenario == "crowd":
        inc = float(params.get("occupancy_increase", 40))
        if not (0 <= inc <= 300):
            raise ValueError(f"occupancy_increase must be 0..300%; got {inc}")
        params["occupancy_increase"] = inc
    elif scenario == "road":
        road_id = params.get("road_id") or _default_road(state)
        if road_id not in state.roads:
            raise ValueError(f"Road '{road_id}' not found")
        params["road_id"] = road_id
    return params


def create_simulation(state: TwinState, scenario: str, target_id: str | None,
                      params: dict | None = None, created_by: str = "operator") -> dict:
    params = _validate(state, scenario, target_id, dict(params or {}))
    cfg = SCENARIOS[scenario]
    sim = SimulationState(
        id=f"sim_{uuid.uuid4().hex[:10]}",
        scenario=scenario, target_id=target_id, params=params,
        simulation_code=f"SIM-{uuid.uuid4().hex[:6].upper()}",
        duration=cfg["duration"], recover_duration=cfg["recover"],
        phase="created",
    )
    if scenario == "fire":
        sim.params.setdefault("intensity", 5)
        sim.params.setdefault("wind", "E")
        sim.params.setdefault("ignition_zone", _default_ignition(state, target_id))
    if scenario == "crowd":
        sim.params.setdefault("occupancy_increase", 40)
    if scenario == "road":
        sim.params.setdefault("road_id", _default_road(state))
    state.active_sim = sim

    target_type = "BUILDING" if target_id in state.buildings else ("ROAD" if scenario == "road" else "CAMPUS")
    with SessionLocal() as db:
        db.add(Simulation(
            id=sim.id, simulation_code=sim.simulation_code, scenario=scenario,
            target_id=target_id, target_type=target_type, params=sim.params,
            status="CREATED", simulation_speed=state.speed,
            total_steps=60, current_step=0,
            created_by=created_by, created_at=_utc(), updated_at=_utc(),
        ))
        db.commit()
    _event(state, sim, "created", f"Simulation {cfg['label']} created.")
    queue_sim_event(state, "simulation.created", sim.to_dict())
    return sim.to_dict()


def _default_ignition(state: TwinState, building_id: str | None) -> str:
    zones = [z for z in state.zones.values() if z.building_id == building_id and z.kind != "EXIT"]
    if not zones:
        zones = list(state.zones.values())
    labs = [z for z in zones if z.kind == "LAB"]
    return (labs[0] if labs else zones[0]).id


def _default_road(state: TwinState) -> str:
    for rid in ("r_cw_cc", "r_cc_ce", "r_mid_w_cw", "r_s2_gate"):
        if rid in state.roads and not state.roads[rid]["blocked"]:
            return rid
    return next(iter(state.roads))


def _event(state: TwinState, sim: SimulationState, kind: str, message: str, data: dict | None = None) -> None:
    sim.events.append({"t": round(sim.t, 1), "kind": kind, "message": message, "data": data or {}})
    with SessionLocal() as db:
        db.add(SimulationEvent(simulation_id=sim.id, t=sim.t, kind=kind,
                               message=message, data=data or {}))
        db.commit()


def _alert(state: TwinState, level: str, title: str, message: str, entity: str | None = None) -> None:
    alert = {"id": f"alert_{len(state.alerts) + 1}", "level": level, "title": title,
             "message": message, "entity_id": entity, "created_at": _utc().isoformat(),
             "acknowledged": False, "severity": level, "type": "SIMULATION",
             "resolved_at": None}
    state.alerts.append(alert)
    with SessionLocal() as db:
        db.add(SystemAlert(level=level, type="SIMULATION", severity=level,
                           title=title, message=message, entity_id=entity,
                           entity_type="building" if entity else None, is_active=True))
        db.commit()


def _incident(state: TwinState, title: str, kind: str, building_id: str | None,
              severity: str, description: str) -> None:
    incident_code = f"INC-{uuid.uuid4().hex[:6].upper()}"
    sim_id = state.active_sim.id if state.active_sim else None
    inc = {
        "id": f"inc_{uuid.uuid4().hex[:8]}", "incident_code": incident_code,
        "title": title, "kind": kind,
        "building_id": building_id,
        "location_type": "BUILDING" if building_id else "CAMPUS",
        "location_id": building_id or "campus",
        "severity": severity, "status": "ACTIVE",
        "description": description, "risk_score": 0.0,
        "simulation_id": sim_id,
        "started_at": _utc().isoformat(), "resolved_at": None,
    }
    state.incidents.append(inc)
    with SessionLocal() as db:
        db.add(Incident(id=inc["id"], incident_code=incident_code, title=title, kind=kind,
                        building_id=building_id,
                        location_type=inc["location_type"], location_id=inc["location_id"],
                        severity=severity, status="ACTIVE", description=description,
                        started_at=_utc(), simulation_id=sim_id))
        db.commit()


def _recommend(state: TwinState, title: str, priority: str, action: str,
               rationale: str, payload: dict, entity: str | None) -> None:
    rec = {
        "id": f"rec_{uuid.uuid4().hex[:8]}", "title": title, "priority": priority,
        "entity_id": entity, "action": action, "rationale": rationale,
        "status": "PENDING", "payload": payload, "created_at": _utc().isoformat(),
        "applied_at": None,
    }
    state.recommendations.insert(0, rec)
    state.recommendations = state.recommendations[:20]
    try:
        from app.services.persistence import save_recommendation
        save_recommendation(rec)
    except Exception:
        pass


def start_simulation(state: TwinState, sim_id: str | None = None) -> dict:
    sim = state.active_sim
    if sim is None:
        raise ValueError("No simulation created")
    if sim_id and sim.id != sim_id:
        raise ValueError("Simulation not found")
    if sim.status not in ("CREATED", "PAUSED", "RESET"):
        raise ValueError(f"Cannot start simulation in status {sim.status}")
    first_start = sim.status in ("CREATED", "RESET")
    sim.status = "RUNNING"
    sim.phase = "started"
    if first_start:
        sim.started_at = state.clock
        state.status = "INCIDENT"
        if sim.scenario == "fire":
            _start_fire(state, sim)
        elif sim.scenario == "road":
            _start_road(state, sim)
        elif sim.scenario == "power":
            _start_power(state, sim)
        elif sim.scenario == "crowd":
            _start_crowd(state, sim)
        elif sim.scenario == "temperature":
            _start_temperature(state, sim)
    _event(state, sim, "started" if first_start else "resumed",
           f"{SCENARIOS[sim.scenario]['label']} {'started' if first_start else 'resumed'}.")
    _sync_db(state, sim)
    queue_sim_event(state, "simulation.started" if first_start else "simulation.resumed", sim.to_dict())
    return sim.to_dict()


def pause_simulation(state: TwinState, sim_id: str) -> dict:
    sim = _require(state, sim_id)
    if sim.status != "RUNNING":
        raise ValueError("Simulation is not running")
    sim.status = "PAUSED"
    _event(state, sim, "paused", "Simulation paused by operator.")
    _sync_db(state, sim)
    queue_sim_event(state, "simulation.paused", sim.to_dict())
    return sim.to_dict()


def resume_simulation(state: TwinState, sim_id: str) -> dict:
    sim = _require(state, sim_id)
    if sim.status != "PAUSED":
        raise ValueError("Simulation is not paused")
    sim.status = "RUNNING"
    _event(state, sim, "resumed", "Simulation resumed by operator.")
    _sync_db(state, sim)
    queue_sim_event(state, "simulation.resumed", sim.to_dict())
    return sim.to_dict()


def reset_simulation(state: TwinState, sim_id: str) -> dict:
    sim = _require(state, sim_id)
    _clear_effects(state, sim)
    sim.t = 0.0
    sim.progress = 0.0
    sim.peak_risk = 0.0
    sim.people_at_risk = 0
    sim.weighted_people = 0
    sim.affected_zones = 0
    sim.max_people_at_risk = 0
    sim.peak_temperature = 24.0
    sim.peak_smoke = 0.0
    sim.results = {}
    sim.recover_t = 0.0
    sim.phase = "created"
    sim.status = "CREATED"
    sim.events = []
    state.status = "NORMAL"
    state.recovery_progress = 100.0
    _event(state, sim, "reset", "Simulation reset to initial state.")
    _sync_db(state, sim)
    queue_sim_event(state, "simulation.reset", sim.to_dict())
    return sim.to_dict()


def recover_simulation(state: TwinState, sim_id: str) -> dict:
    sim = _require(state, sim_id)
    if sim.status in ("COMPLETED",):
        raise ValueError("Simulation already completed")
    sim.status = "RECOVERING"
    sim.phase = "recovering"
    sim.recover_t = 0.0
    state.status = "RECOVERING"
    state.recovery_progress = 0.0
    if sim.scenario == "road":
        reopen_road(state.roads, sim.params.get("road_id", ""))
        compute_routes(state, primary_building=sim.target_id)
    _event(state, sim, "recovering", "Recovery started — restoring normal operations.")
    _sync_db(state, sim)
    queue_sim_event(state, "simulation.recovery_started", sim.to_dict())
    return sim.to_dict()


def _require(state: TwinState, sim_id: str) -> SimulationState:
    sim = state.active_sim
    if sim is None or (sim_id and sim.id != sim_id):
        raise ValueError("Simulation not found")
    return sim


# ------------------------------------------------------------------ scenario starts
def _start_fire(state: TwinState, sim: SimulationState) -> None:
    target = sim.target_id or "eng"
    building = state.buildings.get(target)
    ignition_id = sim.params.get("ignition_zone") or _default_ignition(state, target)
    zones = {z.id: z.__dict__ for z in state.zones.values() if z.building_id == target}
    intensity = float(sim.params.get("intensity", 5))
    ignite(zones, ignition_id, intensity)
    _apply_zone_dicts(state, zones)
    # §20: escalation begins at ALERT (DANGER/CRITICAL follow as fire develops)
    if building:
        building.status = "ALERT"
    sim.params["burn_rate"] = 1.0
    bname = building.name if building else target
    _incident(state, f"Fire in {bname}", "FIRE", target, "HIGH",
              f"Fire ignited in {bname}. Intensity {intensity_label(intensity)} "
              f"({intensity:g}/5 scale), wind {sim.params.get('wind', 'NONE')}, "
              f"ignition zone {ignition_id}.")
    _event(state, sim, "ignition", FIRE_TIMELINE[0][2], {"zone": ignition_id})
    _alert(state, "CRITICAL", "Fire emergency", f"Fire detected in {bname}", target)


def _start_road(state: TwinState, sim: SimulationState) -> None:
    rid = sim.params.get("road_id") or _default_road(state)
    sim.params["road_id"] = rid
    road = state.roads.get(rid)
    if road:
        impact = close_road(state.roads, rid)
        _incident(state, f"Road closed: {road['name']}", "ROAD_CLOSURE", None, "MEDIUM",
                  f"{road['name']} is unavailable; traffic redistributed to "
                  f"{len(impact['affected'])} adjacent corridors.")
        _event(state, sim, "road_closed", f"{road['name']} marked unavailable.",
               {"impact": road_impact(state.roads, rid)})
        _alert(state, "WARNING", "Road closure", f"{road['name']} closed — routes recalculated", None)
        compute_routes(state, primary_building=sim.target_id)


def _start_power(state: TwinState, sim: SimulationState) -> None:
    target = sim.target_id or "eng"
    b = state.buildings.get(target)
    if not b:
        raise ValueError("Target building not found")
    b.power = False
    b.backup_power = b.has_backup_power
    b.status = "POWER_FAILURE"
    fx = power_failure_effects({"has_backup_power": b.has_backup_power,
                                "energy": b.energy}, 0.0)
    _incident(state, f"Power failure — {b.name}", "POWER", target, "HIGH",
              "Mains supply lost; building running on backup. " if b.has_backup_power
              else "Mains supply lost; no backup generator available. "
              f"Affected services: {', '.join(fx['services'])}.")
    _event(state, sim, "power_lost", f"Mains supply lost in {b.name}.",
           {"backup_power": b.backup_power, "services": fx["services"]})
    _alert(state, "CRITICAL", "Power failure", f"{b.name} lost mains power", target)
    _recommend(state, f"Activate backup supply for {b.name}", "HIGH", "activate_backup",
               "Prioritise clinic and emergency systems on the backup bus; shed non-critical loads.",
               {"building_id": target}, target)


def _start_crowd(state: TwinState, sim: SimulationState) -> None:
    target = sim.target_id or "eng"
    b = state.buildings.get(target)
    if not b:
        raise ValueError("Target building not found")
    inc = float(sim.params.get("occupancy_increase", 40))
    _incident(state, f"Crowd surge — {b.name}", "CROWD", target, "MEDIUM",
              f"Occupancy increasing by {inc:.0f}% in {b.name}.")
    _event(state, sim, "crowd_buildup", f"Occupancy in {b.name} increasing by {inc:.0f}%.")
    _alert(state, "WARNING", "Crowd surge", f"{b.name} occupancy increasing by {inc:.0f}%", target)


def _start_temperature(state: TwinState, sim: SimulationState) -> None:
    _incident(state, "Extreme temperature event", "HEAT", None, "MEDIUM",
              "Ambient temperature climbing well above seasonal norms; cooling load surging.")
    _event(state, sim, "heat_wave", "Ambient temperature rising above 38°C.")
    _alert(state, "WARNING", "Extreme temperature", "Heat event in progress — cooling load surging", None)


def _apply_zone_dicts(state: TwinState, zones: dict) -> None:
    for zid, data in zones.items():
        target = state.zones.get(zid)
        if not target:
            continue
        target.fire = data.get("fire", target.fire)
        target.smoke = data.get("smoke", target.smoke)
        target.temperature = data.get("temperature", target.temperature)
        target.status = data.get("status", target.status)


def zone_dicts(state: TwinState, building_id: str | None = None) -> dict:
    return {z.id: dict(z.__dict__) for z in state.zones.values()
            if building_id is None or z.building_id == building_id}


# ------------------------------------------------------------------ ticking
def tick_simulation(state: TwinState, dt: float) -> list[dict]:
    """Advance the active simulation by `dt` virtual seconds. Returns new events."""
    sim = state.active_sim
    if sim is None or sim.status not in ("RUNNING", "RECOVERING"):
        return []
    new_events: list[dict] = []

    if sim.status == "RECOVERING":
        sim.recover_t += dt
        state.recovery_progress = recovery_percent(sim.recover_t, sim.recover_duration)
        if sim.scenario == "fire":
            zones = zone_dicts(state, sim.target_id)
            for ev in suppress(zones, dt, factor=0.45):
                _apply_zone_dicts(state, {ev["zone_id"]: zones[ev["zone_id"]]})
            _apply_zone_dicts(state, zones)
            _update_fire_state(state, sim, zones, totals=zone_totals(zones))
        if state.recovery_progress >= 100.0:
            _complete(state, sim)
            new_events.append({"t": sim.t, "kind": "recovered",
                               "message": "SYSTEM NORMAL — recovery complete."})
            queue_sim_event(state, "simulation.recovered", sim.to_dict())
        else:
            queue_sim_event(state, "simulation.recovery_progress", {
                "simulation_id": sim.id, "scenario": sim.scenario,
                "progress": round(state.recovery_progress, 1),
                "recover_t": round(sim.recover_t, 1),
                "recover_duration": sim.recover_duration,
            })
        return new_events

    sim.t += dt
    sim.progress = min(100.0, 100.0 * sim.t / max(1.0, sim.duration))

    if sim.scenario == "fire":
        new_events.extend(_tick_fire(state, sim, dt))
    elif sim.scenario == "crowd":
        new_events.extend(_tick_crowd(state, sim))
    elif sim.scenario == "temperature":
        new_events.extend(_tick_temperature(state, sim))
    elif sim.scenario == "power":
        new_events.extend(_tick_power(state, sim))
    elif sim.scenario == "road":
        new_events.extend(_tick_road(state, sim))
    _update_peaks(state, sim)

    if sim.t >= sim.duration and sim.status == "RUNNING":
        sim.status = "AWAITING_RECOVERY"
        sim.phase = "stabilized"
        _event(state, sim, "stabilized",
               f"{SCENARIOS[sim.scenario]['label']} stabilized — awaiting operator recovery.")
        _sync_db(state, sim)
        queue_sim_event(state, "simulation.completed", {**sim.to_dict(), "awaiting_recovery": True})

    # §48 — peak campus risk seen during this run (risk is published externally
    # by the AI/risk cycle, so capture it every tick).
    sim.peak_risk = max(sim.peak_risk, float(state.risk.get("score", 0.0) or 0.0))
    return new_events


def _update_fire_state(state: TwinState, sim: SimulationState, zones: dict,
                       totals: dict) -> None:
    """Shared fire bookkeeping for RUNNING and RECOVERING ticks (§18-§20)."""
    sim.people_at_risk = totals["people_at_risk"]
    sim.weighted_people = totals["weighted_people_at_risk"]
    sim.affected_zones = totals["affected_zones"]
    sim.max_people_at_risk = max(sim.max_people_at_risk, sim.people_at_risk)
    b = state.buildings.get(sim.target_id or "")
    # §15/§48 peaks take the max of zone-model and sensor readings — the zone
    # model is the source of truth while burning, sensors after suppression.
    sim.peak_temperature = max(sim.peak_temperature, totals["max_temperature"],
                               b.temperature if b else 0.0)
    sim.peak_smoke = max(sim.peak_smoke, totals["max_smoke"],
                         b.smoke if b else 0.0)
    if b:
        # §20 building status escalation (recovery walks it back to NORMAL)
        b.status = building_status(
            any_fire=totals["max_fire"] > 0.05,
            burning_zones=totals["burning_zones"],
            max_fire=totals["max_fire"],
            smoke_severity_idx=smoke_severity(totals["max_smoke"]),
            affected_zones=totals["affected_zones"],
        ) if b.status != "POWER_FAILURE" else b.status


def _update_peaks(state: TwinState, sim: SimulationState) -> None:
    """Peak metrics for non-fire scenarios + campus-level extremes (§48)."""
    sim.max_people_at_risk = max(sim.max_people_at_risk, sim.people_at_risk)
    if sim.scenario == "fire":
        return
    scope = [z for z in state.zones.values() if sim.target_id is None
             or z.building_id == sim.target_id] or list(state.zones.values())
    sim.peak_temperature = max(sim.peak_temperature,
                               max((z.temperature for z in scope), default=24.0))
    sim.peak_smoke = max(sim.peak_smoke, max((z.smoke for z in scope), default=0.0))
    if sim.scenario == "temperature":
        sim.peak_temperature = max(sim.peak_temperature,
                                   max((b.temperature for b in state.buildings.values()), default=24.0))
    if sim.scenario == "crowd":
        bzones = [z for z in state.zones.values() if z.building_id == (sim.target_id or "")]
        # zones running hot (>=85% of their own capacity) count as affected
        sim.affected_zones = sum(1 for z in bzones
                                 if z.occupancy / max(1, z.capacity) >= 0.85)


def compute_results(state: TwinState, sim: SimulationState) -> dict:
    """§48 — honest results block built from actual simulation state."""
    totals = zone_totals(zone_dicts(state, sim.target_id)) if sim.scenario == "fire" else {}
    b = state.buildings.get(sim.target_id or "") if sim.target_id else None
    return {
        "scenario": sim.scenario,
        "scenario_label": SCENARIOS[sim.scenario]["label"],
        "target_id": sim.target_id,
        "target_name": b.name if b else (sim.params.get("road_id") if sim.scenario == "road"
                                         else "Campus"),
        "status": sim.status,
        "peak_risk": round(sim.peak_risk, 1),
        "peak_risk_level": _severity(sim.peak_risk),
        "peak_people_at_risk": sim.max_people_at_risk,
        "weighted_people_at_risk": sim.weighted_people,
        "affected_zone_count": sim.affected_zones,
        "peak_temperature": round(sim.peak_temperature, 1),
        "peak_smoke": round(sim.peak_smoke, 1),
        "smoke_band": _smoke_band(sim.peak_smoke),
        "burning_zones": totals.get("burning_zones", 0),
        "duration_s": round(sim.t, 1),
        "recovery_time_s": round(sim.recover_t, 1),
        "events": len(sim.events),
        "intensity": sim.params.get("intensity"),
        "intensity_label": intensity_label(float(sim.params.get("intensity", 5)))
        if sim.scenario == "fire" else None,
        "wind": sim.params.get("wind") if sim.scenario == "fire" else None,
    }


def _smoke_band(smoke_units: float) -> str:
    from ai.simulation import smoke_band as _band
    return _band(smoke_severity(smoke_units))


def _tick_fire(state: TwinState, sim: SimulationState, dt: float) -> list[dict]:
    events: list[dict] = []
    zones = zone_dicts(state, sim.target_id)
    model_events = step_fire(
        zones, dt=dt, intensity=float(sim.params.get("intensity", 5)),
        wind=str(sim.params.get("wind", "NONE")), burn_rate=float(sim.params.get("burn_rate", 1.0)),
    )
    _apply_zone_dicts(state, zones)
    for ev in model_events:
        events.append({"t": sim.t, "kind": "spread", "message": ev["message"], "data": ev})
        _event(state, sim, "spread", ev["message"], ev)

    totals = zone_totals(zones)
    _update_fire_state(state, sim, zones, totals)

    for threshold, kind, message in FIRE_TIMELINE[1:]:
        key = f"done_{kind}"
        if sim.t >= threshold and not sim.params.get(key):
            sim.params[key] = True
            payload: dict = {"totals": totals}
            msg = message
            if kind == "smoke_detected":
                b = state.buildings.get(sim.target_id or "")
                if b:
                    b.smoke = max(b.smoke, 45.0)
                _alert(state, "CRITICAL", "Smoke detected", message, sim.target_id)
            elif kind == "routes_recalculated":
                compute_routes(state, primary_building=sim.target_id)
                payload["routes"] = len(state.routes)
            elif kind == "people_at_risk":
                msg = f"{message} Count: {totals['people_at_risk']} people in affected zones."
            elif kind == "route_optimized":
                compute_routes(state, primary_building=sim.target_id)
                best = next((r for r in state.routes if r["building_id"] == sim.target_id
                             and r["status"] == "SAFE"), None)
                if best:
                    msg = (f"{message} Optimal path: {best['building_name']} → "
                           f"{best['exit_name']} (ETA {best['evac_time_s']:.0f}s).")
                    _recommend(state, f"Evacuate {best['building_name']} via {best['exit_name']}",
                               "CRITICAL", "evacuate",
                               f"Gate provides the lowest-risk path: risk {best['risk']}, "
                               f"ETA {best['evac_time_s']:.0f}s for {best['occupancy']} occupants.",
                               {"building_id": sim.target_id, "route_id": best["id"]}, sim.target_id)
                else:
                    msg = f"{message} No safe path — hold occupants and clear a corridor."
                    _recommend(state, f"Hold-in-place protocol for {sim.target_id}", "CRITICAL",
                               "hold_in_place", "No passable evacuation route found; protect sheltered zones first.",
                               {"building_id": sim.target_id}, sim.target_id)
            elif kind == "response_recommended":
                _recommend(state, "Dispatch fire response to ignition floor", "HIGH", "dispatch_response",
                           "Suppressing the ignition zone lowers spread rate by ~65% and prevents "
                           "adjacent zone ignition.",
                           {"building_id": sim.target_id, "burn_rate": 0.35}, sim.target_id)
                _alert(state, "CRITICAL", "Response recommended",
                       "Fire response and evacuation recommendation ready", sim.target_id)
            events.append({"t": sim.t, "kind": kind, "message": msg, "data": payload})
            _event(state, sim, kind, msg, payload)
    return events


def _tick_crowd(state: TwinState, sim: SimulationState) -> list[dict]:
    events: list[dict] = []
    b = state.buildings.get(sim.target_id or "")
    if not b:
        return events
    ratio = b.occupancy / max(1, b.capacity)
    if ratio >= 1.0 and not sim.params.get("done_overload"):
        sim.params["done_overload"] = True
        msg = f"{b.name} exceeded capacity ({b.occupancy}/{b.capacity})."
        _event(state, sim, "overloaded", msg)
        _alert(state, "CRITICAL", "Building overloaded", msg, b.id)
        _recommend(state, f"Throttle entry to {b.name}", "HIGH", "throttle_entry",
                   "Density above 100% of capacity — open overflow areas and meter entry.",
                   {"building_id": b.id}, b.id)
        events.append({"t": sim.t, "kind": "overloaded", "message": msg, "data": {}})
    elif ratio >= 0.85 and not sim.params.get("done_warning"):
        sim.params["done_warning"] = True
        msg = f"{b.name} at {ratio:.0%} capacity — crowd risk increasing."
        _event(state, sim, "density_warning", msg)
        _alert(state, "WARNING", "High crowd density", msg, b.id)
        events.append({"t": sim.t, "kind": "density_warning", "message": msg, "data": {}})
    return events


def _tick_temperature(state: TwinState, sim: SimulationState) -> list[dict]:
    events = []
    if sim.t >= 60 and not sim.params.get("done_clinic"):
        sim.params["done_clinic"] = True
        msg = "Clinic moved to standby capacity — heat-related admissions expected."
        _event(state, sim, "clinic_standby", msg)
        _recommend(state, "Pre-cool high-occupancy buildings and stage water points", "MEDIUM",
                   "heat_mitigation",
                   "Cooling load and occupancy peak together; pre-cooling reduces peak risk.",
                   {}, None)
        events.append({"t": sim.t, "kind": "clinic_standby", "message": msg, "data": {}})
    return events


def _tick_power(state: TwinState, sim: SimulationState) -> list[dict]:
    events = []
    b = state.buildings.get(sim.target_id or "")
    if not b:
        return events
    if sim.t >= 90 and not sim.params.get("done_drift"):
        sim.params["done_drift"] = True
        msg = f"{b.name} temperature rising — HVAC offline for {sim.t:.0f}s."
        _event(state, sim, "thermal_drift", msg)
        events.append({"t": sim.t, "kind": "thermal_drift", "message": msg, "data": {}})
    return events


def _tick_road(state: TwinState, sim: SimulationState) -> list[dict]:
    events = []
    if sim.t >= 40 and not sim.params.get("done_reroute"):
        sim.params["done_reroute"] = True
        compute_routes(state, primary_building=sim.target_id)
        report = ", ".join(f"{r['building_name']}→{r['exit_name']}" for r in state.routes[:3])
        msg = f"Emergency routes recalculated: {report}."
        _event(state, sim, "rerouted", msg)
        _recommend(state, "Reroute service traffic via ring road", "MEDIUM", "reroute_traffic",
                   "Primary corridor closed; ring road absorbs the displaced flow.",
                   {"road_id": sim.params.get("road_id")}, None)
        events.append({"t": sim.t, "kind": "rerouted", "message": msg, "data": {}})
    return events


def _complete(state: TwinState, sim: SimulationState) -> None:
    sim.status = "COMPLETED"
    sim.phase = "completed"
    sim.progress = 100.0
    sim.peak_risk = max(sim.peak_risk, state.risk.get("score", 0.0),
                        state.building_risk.get(sim.target_id or "", {}).get("score", 0.0))
    state.status = "NORMAL"
    state.recovery_progress = 100.0
    b = state.buildings.get(sim.target_id or "")
    if b and sim.scenario in ("fire", "crowd", "power"):
        b.status = "OPERATIONAL"
        b.power = True
        b.backup_power = False
        b.evacuation_order = False
    for inc in state.incidents:
        if inc["status"] == "ACTIVE" and (inc.get("building_id") == sim.target_id or sim.scenario in ("road", "temperature")):
            if sim.scenario == "fire" and inc.get("kind") != "FIRE":
                continue
            inc["status"] = "RESOLVED"
            inc["resolved_at"] = _utc().isoformat()
    try:
        from app.services.persistence import resolve_incidents_for
        kinds = ["FIRE", "CROWD", "POWER", "ROAD_CLOSURE", "HEAT"]
        resolve_incidents_for(sim.target_id if sim.scenario in ("fire", "crowd", "power") else None, kinds)
    except Exception:
        pass
    # prune resolved alerts from the live feed
    state.alerts = [a for a in state.alerts if a.get("entity_id") != sim.target_id or sim.scenario == "road"][:20]
    _event(state, sim, "completed", "SYSTEM NORMAL — simulation completed and recovered.")
    sim.results = compute_results(state, sim)
    queue_sim_event(state, "simulation.completed", sim.to_dict())
    _sync_db(state, sim, final=True)
    from app.services.persistence import save_completed_simulation
    save_completed_simulation(state, sim)


def _clear_effects(state: TwinState, sim: SimulationState) -> None:
    if sim.scenario == "fire":
        for z in state.zones.values():
            if z.building_id == sim.target_id:
                z.fire = 0.0
                z.smoke = 0.0
                z.temperature = 24.0
                z.status = "NORMAL"
    if sim.scenario == "road":
        reopen_road(state.roads, sim.params.get("road_id", ""))
    if sim.scenario == "power":
        b = state.buildings.get(sim.target_id or "")
        if b:
            b.power = True
            b.backup_power = False
            b.status = "OPERATIONAL"
    b = state.buildings.get(sim.target_id or "")
    if b and sim.scenario in ("fire", "crowd"):
        b.status = "OPERATIONAL"
        b.evacuation_order = False
    if b and sim.scenario == "fire":
        # hard reset restores the initial state: lingering heat/smoke would
        # keep building risk (and therefore node/road route risk) elevated.
        b.temperature = 24.0
        b.smoke = 0.0
    state.incidents = [i for i in state.incidents if not (
        i["status"] == "ACTIVE" and (i.get("building_id") == sim.target_id or sim.scenario in ("road", "temperature"))
    )]
    state.recommendations = [r for r in state.recommendations if r["status"] == "PENDING" and
                             r.get("entity_id") != sim.target_id]
    state.recovery_progress = 100.0
    state.status = "NORMAL"
    for z in state.zones.values():
        if z.status in ("FIRE", "SMOKE", "AFFECTED"):
            z.status = "NORMAL"
            z.fire = 0.0
            z.smoke = 0.0
    # hazard-derived route risk dies with the hazard (Phase 7 risk liveness)
    for nid in list(state.node_risk):
        state.node_risk[nid] = 0.0
    for road in state.roads.values():
        road["risk"] = 0.0
    compute_routes(state, primary_building=None)


def _sync_db(state: TwinState, sim: SimulationState, final: bool = False) -> None:
    with SessionLocal() as db:
        row = db.get(Simulation, sim.id)
        if row:
            row.status = sim.status
            row.progress = sim.progress
            row.peak_risk = sim.peak_risk
            row.people_affected = sim.max_people_at_risk or sim.people_at_risk
            row.severity = _severity(sim.peak_risk)
            results = dict(sim.results) if sim.results else compute_results(state, sim)
            row.result = {"phase": sim.phase, "events": len(sim.events),
                          "scenario": sim.scenario, "target_id": sim.target_id,
                          "results": results}
            row.updated_at = _utc()
            if final:
                row.ended_at = _utc()
                row.recovery_time_s = sim.recover_t
            db.commit()


def _severity(score: float) -> str:
    if score >= 81:
        return "CRITICAL"
    if score >= 61:
        return "HIGH"
    if score >= 41:
        return "MEDIUM"
    return "LOW"
