"""Route & evacuation optimisation service (Phase 7 §8–§44).

Bridges the pure `ai.optimization` engines to the live `TwinState`:

* effective state = baseline campus data + simulation modifiers already applied
  to `state.roads` / `state.node_risk` / zones — the engine READS this state and
  never mutates baseline data (§27); recovery restores roads automatically.
* plan lifecycle: calculate → validity checks → invalidate → recalculate with
  `route_version` bumps (§11) and structured reasons (§10).
* typed WS events (`route.*`, `evacuation.*`, `bottleneck.*`,
  `emergency_route.*`) are queued on `state.pending_sim_events` and flushed by
  the runtime through `manager.emit` (same transport as Phase 6).
* persistence: `evacuation_routes` rows (current plan) + `route_events`
  history (§33) for Phase 9 analytics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ai.optimization import (
    DEFAULT_MODE,
    MODE_KEYS,
    STATUS_NO_SAFE_ROUTE,
    VEHICLE_KEYS,
    VEHICLE_PROFILES,
    calculate_route,
    check_route_validity,
    compare_modes,
    get_graph,
    plan_building_evacuation,
    plan_campus_evacuation,
    plan_emergency_route,
)
from app.services.state import TwinState

HISTORY_CAP = 40
AFFECTED_STATUSES = ("FIRE", "SMOKE", "AFFECTED")
# adoption rule for "environment improved" recalcs (§32): only switch when the
# new route is genuinely better, never for noise.
IMPROVE_RISK_DELTA = 10.0
IMPROVE_TIME_RATIO = 0.85


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def queue_route_event(state: TwinState, event: str, data: dict) -> None:
    """Queue a typed route-family WS event for the runtime flush (§26)."""
    state.pending_sim_events.append({"event": event, "data": data})
    if len(state.pending_sim_events) > 60:
        del state.pending_sim_events[: len(state.pending_sim_events) - 60]


def active_simulation_id(state: TwinState) -> str | None:
    sim = state.active_sim
    if sim and sim.status in ("RUNNING", "PAUSED", "AWAITING_RECOVERY", "RECOVERING"):
        return sim.id
    return None


# --------------------------------------------------------------- graph/state
def get_route_graph(state: TwinState, refresh: bool = True):
    """Effective route graph: cached topology + fresh dynamic edge state (§4)."""
    g = get_graph(state.nodes, state.roads)
    if refresh:
        g.refresh_dynamic(state.roads, state.node_risk)
    return g


def people_at_risk_for(state: TwinState, building_id: str) -> tuple[int, bool]:
    """(people_at_risk, affected) for a building (§14).

    people_at_risk = occupants in FIRE/SMOKE/AFFECTED zones + occupancy above
    safe capacity (crowd surge). Affected = any hazard zone or elevated status.
    """
    b = state.buildings.get(building_id)
    if b is None:
        return 0, False
    zones = [z for z in state.zones.values() if z.building_id == building_id]
    affected_zones = [z for z in zones if z.status in AFFECTED_STATUSES]
    par = sum(z.occupancy for z in affected_zones)
    if b.occupancy > b.capacity:
        par += b.occupancy - b.capacity
    affected = bool(affected_zones) or b.status in ("ALERT", "DANGER", "CRITICAL")
    return int(par), affected


def building_inputs(state: TwinState) -> list[dict]:
    out = []
    for bid, b in state.buildings.items():
        par, affected = people_at_risk_for(state, bid)
        out.append({
            "id": bid, "name": b.name, "occupancy": b.occupancy,
            "capacity": b.capacity, "status": b.status,
            "exits": state.exits_for(bid), "people_at_risk": par,
            "affected": affected,
        })
    return out


def campus_people_at_risk(state: TwinState) -> int:
    if state.active_sim and state.active_sim.people_at_risk:
        return int(state.active_sim.people_at_risk)
    return sum(people_at_risk_for(state, bid)[0] for bid in state.buildings)


# --------------------------------------------------------------- plan helpers
def _edge_risk_snapshot(g, road_path: list[str]) -> dict[str, float]:
    return {rid: round(g.edges[rid].risk, 1) for rid in road_path if rid in g.edges}


def _new_plan(state: TwinState, g, route: dict, *, kind: str, mode: str,
              origin: str | None, destination: str | None, source: str,
              reason: str = "", building_id: str | None = None,
              evacuation: dict | None = None) -> dict:
    state.route_version += 1
    primary = {k: v for k, v in route.items() if k != "alternatives"}
    alternatives = list(route.get("alternatives") or [])
    now = _iso(_utc())
    return {
        "route_id": f"rte_{uuid.uuid4().hex[:10]}",
        "kind": kind,
        "mode": mode,
        "status": primary.get("status", STATUS_NO_SAFE_ROUTE),
        "route_version": state.route_version,
        "simulation_id": active_simulation_id(state),
        "created_at": now,
        "updated_at": now,
        "source": source,
        "reason": reason or primary.get("reason", ""),
        "origin": origin or primary.get("origin"),
        "destination": destination or primary.get("destination"),
        "building_id": building_id,
        "route": primary,
        "alternatives": alternatives,
        "edge_risk": _edge_risk_snapshot(g, primary.get("road_path", [])),
        "evacuation": evacuation,
        "people_at_risk": primary.get("people", 0),
    }


def _activate_plan(state: TwinState, plan: dict, event: str, data_extra: dict | None = None,
                   persist: bool = True) -> dict:
    state.route_plan = plan
    state.route_history.insert(0, {
        "route_id": plan["route_id"], "kind": plan["kind"], "mode": plan["mode"],
        "status": plan["status"], "route_version": plan["route_version"],
        "origin": plan["origin"], "destination": plan["destination"],
        "reason": plan["reason"], "created_at": plan["created_at"],
        "simulation_id": plan["simulation_id"],
        "distance": plan["route"].get("distance", 0.0),
        "estimated_time": plan["route"].get("estimated_time", 0.0),
        "risk_score": plan["route"].get("risk_score", 0.0),
    })
    del state.route_history[HISTORY_CAP:]
    payload = {
        "route_id": plan["route_id"], "kind": plan["kind"], "mode": plan["mode"],
        "status": plan["status"], "route_version": plan["route_version"],
        "simulation_id": plan["simulation_id"], "origin": plan["origin"],
        "destination": plan["destination"], "reason": plan["reason"],
        "route": plan["route"],
        "alternatives": plan["alternatives"],
        "people_at_risk": plan["people_at_risk"],
        "timestamp": plan["updated_at"],
    }
    if data_extra:
        payload.update(data_extra)
    queue_route_event(state, event, payload)
    if persist:
        persist_plan(state, plan, event=event, reason=plan["reason"])
    return plan


# ------------------------------------------------------------- calculations
def calculate(state: TwinState, origin: str, destination: str,
              mode: str = DEFAULT_MODE, people: float = 0.0,
              alternatives: int = 1, source: str = "api",
              activate: bool = True, event: str | None = None) -> dict:
    """§25 — validated point-to-point calculation. Raises ValueError → 400."""
    if mode not in MODE_KEYS:
        raise ValueError(f"Unknown route mode '{mode}'. Valid: {list(MODE_KEYS)}")
    g = get_route_graph(state)
    if origin not in g.nodes:
        raise ValueError(f"Unknown origin node '{origin}'")
    if destination not in g.nodes:
        raise ValueError(f"Unknown destination node '{destination}'")
    route = calculate_route(g, origin, destination, mode=mode, people=people,
                            alternatives=max(0, alternatives))
    state.route_mode = mode
    plan = _new_plan(state, g, route, kind="point", mode=mode, origin=origin,
                     destination=destination, source=source)
    if activate:
        event_name = event or ("route.calculated" if source == "api"
                               else "route.recalculated")
        _activate_plan(state, plan, event=event_name)
    return plan


def alternatives_for(state: TwinState, origin: str, destination: str,
                     mode: str = DEFAULT_MODE, limit: int = 3) -> dict:
    """§9/§21 — recommended + alternatives + cross-mode comparison (no activation)."""
    if mode not in MODE_KEYS:
        raise ValueError(f"Unknown route mode '{mode}'. Valid: {list(MODE_KEYS)}")
    g = get_route_graph(state)
    if origin not in g.nodes:
        raise ValueError(f"Unknown origin node '{origin}'")
    if destination not in g.nodes:
        raise ValueError(f"Unknown destination node '{destination}'")
    route = calculate_route(g, origin, destination, mode=mode,
                            alternatives=max(1, limit - 1))
    routes = [route] + list(route.get("alternatives") or [])
    for r in routes:
        r.pop("alternatives", None)
    return {
        "origin": origin, "destination": destination, "mode": mode,
        "routes": routes[:limit],
        "comparison": compare_modes(g, origin, destination),
        "simulation_id": active_simulation_id(state),
        "route_version": state.route_version,
    }


def refresh_evacuation(state: TwinState, mode: str | None = None,
                       source: str = "auto") -> dict:
    """§8/§12/§14 — campus evacuation overview, cached in `state.evacuation`."""
    mode = mode or state.route_mode
    g = get_route_graph(state)
    campus = plan_campus_evacuation(g, building_inputs(state), mode=mode)
    campus["simulation_id"] = active_simulation_id(state)
    campus["people_at_risk"] = campus.get("people_at_risk") or campus_people_at_risk(state)
    campus["generated_at"] = _iso(_utc())
    campus["route_version"] = state.route_version

    prev = state.evacuation or {}
    content_sig = (
        campus["status"],
        tuple((b["building_id"], b["primary_exit"], b["route_status"])
              for b in campus["buildings"]),
        tuple(b["location_id"] for b in campus["bottlenecks"]),
    )
    changed = content_sig != state._evac_sig
    state._evac_sig = content_sig

    prev_status = prev.get("status", "IDLE")
    new_status = campus["status"]
    if changed and new_status != prev_status:
        if new_status in ("ACTIVE", "CRITICAL") and prev_status in ("IDLE", "STANDBY", "READY"):
            queue_route_event(state, "evacuation.started", {
                "status": new_status, "previous_status": prev_status,
                "people_at_risk": campus["people_at_risk"],
                "critical_buildings": campus["critical_buildings"],
                "simulation_id": campus["simulation_id"],
            })
        elif new_status in ("IDLE", "STANDBY") and prev_status in ("ACTIVE", "CRITICAL"):
            queue_route_event(state, "evacuation.completed", {
                "status": new_status, "previous_status": prev_status,
                "reason": "risk returned to safe levels",
                "simulation_id": campus["simulation_id"],
            })
        elif new_status in ("ACTIVE", "CRITICAL"):
            queue_route_event(state, "evacuation.updated", {
                "status": new_status, "previous_status": prev_status,
                "people_at_risk": campus["people_at_risk"],
                "critical_buildings": campus["critical_buildings"],
            })
    elif changed and new_status == prev_status and new_status in ("ACTIVE", "CRITICAL"):
        queue_route_event(state, "evacuation.updated", {
            "status": new_status,
            "people_at_risk": campus["people_at_risk"],
            "critical_buildings": campus["critical_buildings"],
        })

    # bottleneck transitions (§13, §26)
    prev_bn = set(state.bottleneck_ids or [])
    now_bn = {b["location_id"] for b in campus["bottlenecks"]}
    for b in campus["bottlenecks"]:
        if b["location_id"] not in prev_bn:
            queue_route_event(state, "bottleneck.detected", {
                "bottleneck": b, "simulation_id": campus["simulation_id"],
            })
    for loc in sorted(prev_bn - now_bn):
        queue_route_event(state, "bottleneck.cleared", {
            "location_id": loc, "simulation_id": campus["simulation_id"],
        })
    state.bottleneck_ids = sorted(now_bn)

    state.evacuation = campus
    return campus


def building_evacuation(state: TwinState, building_id: str,
                        mode: str | None = None, activate: bool = True) -> dict:
    """§15 — single-building evacuation plan (primary + alternatives + exits)."""
    if building_id not in state.buildings:
        raise ValueError(f"Unknown building '{building_id}'")
    mode = mode or state.route_mode
    if mode not in MODE_KEYS:
        raise ValueError(f"Unknown route mode '{mode}'. Valid: {list(MODE_KEYS)}")
    g = get_route_graph(state)
    binput = next(b for b in building_inputs(state) if b["id"] == building_id)
    plan = plan_building_evacuation(g, binput, mode=mode)
    plan["simulation_id"] = active_simulation_id(state)
    plan["route_version"] = state.route_version
    plan["generated_at"] = _iso(_utc())
    if activate:
        routes = plan.get("routes") or []
        primary = plan.get("primary_route") or (routes[0] if routes else
                                                {"status": STATUS_NO_SAFE_ROUTE})
        wrapper = _new_plan(state, g, {**primary, "alternatives": routes[1:]},
                            kind="evacuation", mode=mode,
                            origin=primary.get("origin"),
                            destination=primary.get("destination"),
                            source="api", building_id=building_id,
                            reason=plan.get("reason", ""))
        wrapper["evacuation"] = plan
        wrapper["people_at_risk"] = plan["people_at_risk"]
        _activate_plan(state, wrapper, event="route.calculated",
                       data_extra={"evacuation_status": plan["status"]})
        plan["route_version"] = state.route_version
    return plan


# ------------------------------------------------------- emergency vehicles
def _incident_node(state: TwinState, g) -> str | None:
    """Best response target: active incident building exit, else sim target."""
    for inc in state.incidents:
        if inc.get("status") != "ACTIVE":
            continue
        if inc.get("location_type") == "BUILDING" and inc.get("building_id"):
            exits = state.exits_for(inc["building_id"])
            for ex in exits:
                if ex in g.nodes:
                    return ex
        elif inc.get("location_type") == "ROAD" and inc.get("location_id"):
            road = state.roads.get(inc["location_id"])
            if road:
                for nid in (road["to_node"], road["from_node"]):
                    if nid in g.nodes:
                        return nid
    sim = state.active_sim
    if sim and sim.target_id and sim.scenario in ("fire", "crowd", "power"):
        for ex in state.exits_for(sim.target_id):
            if ex in g.nodes:
                return ex
    return None


def emergency_routes(state: TwinState, vehicle: str | None = None,
                     origin: str | None = None, destination: str | None = None,
                     activate: bool = True) -> dict:
    """§16 — emergency vehicle route(s) from deployment gate to incident."""
    if vehicle is not None and vehicle not in VEHICLE_KEYS:
        raise ValueError(f"Unknown vehicle '{vehicle}'. Valid: {list(VEHICLE_KEYS)}")
    g = get_route_graph(state)
    dest = destination or _incident_node(state, g)
    if dest is None:
        return {
            "status": STATUS_NO_SAFE_ROUTE,
            "reason": "No active incident or simulation to respond to.",
            "routes": [], "incident_node": None,
            "simulation_id": active_simulation_id(state),
            "generated_at": _iso(_utc()),
        }
    if destination is not None and destination not in g.nodes:
        raise ValueError(f"Unknown destination node '{destination}'")

    vehicles = [vehicle] if vehicle else list(VEHICLE_KEYS)
    routes = []
    for v in vehicles:
        v_origin = origin or VEHICLE_PROFILES[v]["default_origin"]
        if v_origin not in g.nodes:
            gates = g.exits()
            if not gates:
                continue
            v_origin = gates[0]
        routes.append(plan_emergency_route(g, v_origin, dest, vehicle=v))

    result = {
        "status": "ok" if routes else STATUS_NO_SAFE_ROUTE,
        "incident_node": dest,
        "incident_name": g.nodes[dest].name,
        "routes": routes,
        "simulation_id": active_simulation_id(state),
        "generated_at": _iso(_utc()),
    }
    if activate and routes:
        best = min((r for r in routes if r.get("road_path")),
                   key=lambda r: (r.get("eta_s", 1e9), r.get("risk_score", 100.0)),
                   default=None)
        if best:
            wrapper = _new_plan(state, g, {**best, "alternatives": []},
                                kind="emergency", mode="emergency",
                                origin=best.get("origin"),
                                destination=best.get("destination"),
                                source="api", reason=best.get("reason", ""))
            wrapper["vehicle"] = best.get("vehicle")
            _activate_plan(state, wrapper, event="emergency_route.updated",
                           data_extra={"vehicle_routes": routes,
                                       "incident_node": dest})
    return result


# ------------------------------------------------- validity / re-route (§10)
def _signature(state: TwinState) -> tuple:
    """Coarse environment fingerprint — events fire only when this changes.

    Deliberately excludes volatile per-tick values (raw risk score, occupancy):
    blocked roads, building/incident statuses, risk *level* (coarse score
    bucket), congestion pattern and simulation phase are what actually change
    route topology or quality (§10, §36).
    """
    blocked = tuple(sorted(rid for rid, r in state.roads.items() if r.get("blocked")))
    congestion = tuple(sorted(round(float(r.get("congestion", 0.0)), 1)
                              for r in state.roads.values()))
    statuses = tuple(sorted((bid, b.status) for bid, b in state.buildings.items()))
    incidents = tuple(sorted((str(i.get("id")), i.get("status"))
                             for i in state.incidents))
    sim = state.active_sim
    sim_sig = None
    if sim:
        sim_sig = (sim.id, sim.status, int(sim.t // 10), int(state.recovery_progress))
    risk = state.risk or {}
    return (blocked, congestion, statuses, incidents, state.status,
            risk.get("level", "LOW"), int(float(risk.get("score", 0)) // 10),
            sim_sig)


def _plan_validity(state: TwinState, g, plan: dict) -> dict:
    route = plan.get("route") or {}
    v = check_route_validity(g, route.get("road_path", []) or [],
                             route.get("node_path", []) or [],
                             prev_edge_risk=plan.get("edge_risk"))
    # absolute safety flip (§10): a route that has become HIGH_RISK is invalid
    # even if risk crept up gradually below the delta threshold.
    road_path = route.get("road_path") or []
    if v["valid"] and road_path and route.get("safety") not in (None, "HIGH_RISK"):
        edges = [g.edges[r] for r in road_path if r in g.edges]
        if edges:
            avg = sum(e.risk for e in edges) / len(edges)
            worst = max(e.risk for e in edges)
            if avg >= 55.0 or worst >= 75.0:
                v["valid"] = False
                v["reasons"] = ["risk_increased"] + v["reasons"]
    return v


def _is_better(candidate: dict, current: dict) -> bool:
    c_risk = candidate.get("risk_score", 100.0)
    c_time = candidate.get("estimated_time", 1e9)
    k_risk = current.get("risk_score", 100.0)
    k_time = current.get("estimated_time", 1e9)
    if c_risk <= k_risk - IMPROVE_RISK_DELTA:
        return True
    if c_time <= k_time * IMPROVE_TIME_RATIO and c_risk <= k_risk + 5.0:
        return True
    return False


def revalidate(state: TwinState, force: bool = False) -> dict:
    """Dynamic re-routing (§10) — cheap per-tick check, events on real change.

    Called by the runtime every sensor tick. Recomputes only when the coarse
    signature changed or the active plan became invalid; version bumps and WS
    events fire only on genuine transitions (§36 performance rule).
    """
    sig = _signature(state)
    sig_changed = sig != state._route_signature
    if sig_changed:
        state._route_signature = sig

    plan = state.route_plan
    result = {"changed": False, "invalidated": False, "evacuation": False,
              "route_version": state.route_version}
    if not force and not sig_changed and plan is None:
        return result

    g = get_route_graph(state)

    # 1) campus evacuation cache + status/bottleneck events (first: the
    #    auto-plan below depends on the refreshed status)
    if sig_changed or force:
        refresh_evacuation(state, source="auto")
        result["evacuation"] = True

    # 2) active plan validity / improvement
    if plan is not None and plan.get("kind") in ("point", "emergency"):
        validity = _plan_validity(state, g, plan)
        if not validity["valid"] or force:
            reason = (validity["reasons"][0] if validity["reasons"] else "forced")
            queue_route_event(state, "route.invalidated", {
                "route_id": plan["route_id"], "route_version": plan["route_version"],
                "reason": reason, "reasons": validity["reasons"],
                "blocked_paths": validity["blocked_paths"],
                "simulation_id": plan.get("simulation_id"),
            })
            result["invalidated"] = True
            new_plan = calculate(state, plan["origin"], plan["destination"],
                                 mode=plan["mode"],
                                 people=float(plan.get("people_at_risk") or 0),
                                 alternatives=1, source="auto")
            result.update({"changed": True, "route_version": new_plan["route_version"],
                           "route_id": new_plan["route_id"], "reason": reason})
        elif sig_changed:
            candidate = calculate_route(g, plan["origin"], plan["destination"],
                                        mode=plan["mode"],
                                        people=float(plan.get("people_at_risk") or 0),
                                        alternatives=0)
            if candidate.get("road_path") != plan["route"].get("road_path") \
                    and _is_better(candidate, plan["route"]):
                new_plan = calculate(state, plan["origin"], plan["destination"],
                                     mode=plan["mode"],
                                     people=float(plan.get("people_at_risk") or 0),
                                     alternatives=1, source="auto",
                                     event="route.updated")
                result.update({"changed": True,
                               "route_version": new_plan["route_version"]})
            else:
                plan["edge_risk"] = _edge_risk_snapshot(
                    g, plan["route"].get("road_path", []))
                plan["updated_at"] = _iso(_utc())

    elif plan is not None and plan.get("kind") == "evacuation" and sig_changed:
        building_id = plan.get("building_id")
        if building_id and building_id in state.buildings:
            fresh = building_evacuation(state, building_id, mode=plan["mode"],
                                        activate=False)
            plan["evacuation"] = fresh
            plan["route"] = fresh.get("primary_route") or plan["route"]
            plan["alternatives"] = (fresh.get("routes") or [])[1:]
            plan["people_at_risk"] = fresh.get("people_at_risk", 0)
            plan["status"] = plan["route"].get("status", plan["status"])
            plan["edge_risk"] = _edge_risk_snapshot(g, plan["route"].get("road_path", []))
            plan["updated_at"] = _iso(_utc())
            if fresh.get("has_safe_route"):
                result["changed"] = True

    # 3) auto-plan: when an incident is active and no plan exists, activate the
    #    most at-risk building's evacuation plan so the 3D scene always shows
    #    the response route during an emergency (§8/§28).
    if plan is None and (sig_changed or force):
        evac = state.evacuation or {}
        if evac.get("status") in ("ACTIVE", "CRITICAL"):
            target = (evac.get("critical_buildings") or [None])[0]
            if target is None:
                pool = [b for b in evac.get("buildings", []) if b.get("has_safe_route")]
                pool = pool or evac.get("buildings", [])
                if pool:
                    target = max(pool, key=lambda b: b.get("people_at_risk", 0)).get("building_id")
            if target and target in state.buildings:
                building_evacuation(state, target, activate=True)
                result["changed"] = True
                result["route_version"] = state.route_version
    return result


def ensure_initial(state: TwinState) -> None:
    """Startup: baseline signature + cached campus overview (no events)."""
    state._route_signature = _signature(state)
    refresh_evacuation(state, source="boot")
    # boot-time refresh queues status events only on transitions; clear them so
    # a fresh process does not emit historical lifecycle events.
    state.pending_sim_events.clear()


# ------------------------------------------------------------- persistence
def persist_plan(state: TwinState, plan: dict, event: str = "calculated",
                 reason: str = "") -> None:
    """§33/§34 — upsert current plan row + append route_events history."""
    try:
        from app.core.database import SessionLocal
        from app.models.entities import EvacuationRoute, RouteEvent

        r = plan.get("route") or {}
        now = _utc()
        with SessionLocal() as db:
            db.merge(EvacuationRoute(
                id=plan["route_id"],
                origin_id=str(r.get("origin") or plan.get("origin") or ""),
                exit_id=str(r.get("destination") or plan.get("destination") or ""),
                node_path=r.get("node_path", []), road_path=r.get("road_path", []),
                distance=float(r.get("distance", 0.0)),
                eta_s=float(r.get("estimated_time", 0.0)),
                risk=float(r.get("risk_score", 0.0)),
                status=_db_status(r.get("status", "")),
                reason=str(r.get("reason") or reason or ""),
                is_primary=True,
                simulation_id=plan.get("simulation_id") or "",
                mode=plan.get("mode", DEFAULT_MODE),
                congestion_score=float(r.get("congestion_score", 0.0)),
                route_version=int(plan.get("route_version", 1)),
                people_at_risk=int(plan.get("people_at_risk") or 0),
                kind=plan.get("kind", "point"),
                created_at=now,
            ))
            db.add(RouteEvent(
                id=f"rev_{uuid.uuid4().hex[:10]}",
                route_id=plan["route_id"],
                simulation_id=plan.get("simulation_id") or "",
                event=event.replace("route.", "").replace("emergency_route.", "emergency_"),
                origin=str(plan.get("origin") or ""),
                destination=str(plan.get("destination") or ""),
                mode=plan.get("mode", DEFAULT_MODE),
                path=r.get("node_path", []),
                distance=float(r.get("distance", 0.0)),
                eta_s=float(r.get("estimated_time", 0.0)),
                risk_score=float(r.get("risk_score", 0.0)),
                congestion_score=float(r.get("congestion_score", 0.0)),
                route_version=int(plan.get("route_version", 1)),
                reason=str(reason or plan.get("reason") or ""),
                created_at=now,
            ))
            db.commit()
    except Exception:  # persistence must never break routing (§37)
        import logging
        logging.getLogger("route_service").exception("route persistence failed")


def _db_status(status: str) -> str:
    """Map Phase 7 statuses onto the 16-char column (keeps legacy values)."""
    allowed = {"RECOMMENDED", "ALTERNATIVE", "NOT_RECOMMENDED", "BLOCKED",
               "NO_SAFE_ROUTE", "SAFE", "WARNING"}
    return status if status in allowed else "SAFE"


def history(db, limit: int = 50, simulation_id: str | None = None) -> list[dict]:
    """§33 — persisted route calculation history (newest first)."""
    from app.models.entities import RouteEvent

    q = db.query(RouteEvent).order_by(RouteEvent.created_at.desc())
    if simulation_id:
        q = q.filter(RouteEvent.simulation_id == simulation_id)
    rows = q.limit(max(1, min(200, limit))).all()
    return [{
        "id": r.id, "route_id": r.route_id, "simulation_id": r.simulation_id,
        "event": r.event, "origin": r.origin, "destination": r.destination,
        "mode": r.mode, "path": r.path, "distance": r.distance,
        "eta_s": r.eta_s, "risk_score": r.risk_score,
        "congestion_score": r.congestion_score, "route_version": r.route_version,
        "reason": r.reason, "created_at": r.created_at.isoformat(),
    } for r in rows]
