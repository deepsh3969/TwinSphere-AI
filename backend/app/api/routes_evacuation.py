"""Phase 7 — Route & Evacuation Optimization API.

Registered AFTER `routes_campus` so legacy `GET /api/routes` and
`POST /api/routes/recompute` keep their exact behaviour; all Phase 7 paths are
distinct literals (resolved before `/routes/{route_id}` inside this module).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.security import require
from app.models.entities import EvacuationRoute, RouteEvent
from app.schemas.common import RouteCalculate, RouteRecalculate
from app.services import route_service as rs
from app.services.state import get_state
from ai.optimization import MODE_KEYS, VEHICLE_KEYS

router = APIRouter(prefix="/api", tags=["routes-optimization"])


# --------------------------------------------------------------- helpers
def _check_simulation_id(provided: str | None) -> None:
    """§43 — never trust a frontend simulation id."""
    if not provided:
        return
    state = get_state()
    active = rs.active_simulation_id(state)
    if provided != active:
        if active is None:
            raise HTTPException(400, "simulation_id provided but no simulation is active")
        raise HTTPException(400, "simulation_id does not match the active simulation")


def _plan_response(plan: dict) -> dict:
    r = plan.get("route") or {}
    return {
        "route_id": plan["route_id"],
        "kind": plan.get("kind", "point"),
        "mode": plan.get("mode", "balanced"),
        "status": plan.get("status", ""),
        "reason": plan.get("reason", ""),
        "path": r.get("path", []),
        "node_path": r.get("node_path", []),
        "road_path": r.get("road_path", []),
        "origin": plan.get("origin"),
        "destination": plan.get("destination"),
        "destination_name": r.get("destination_name", ""),
        "distance": r.get("distance", 0.0),
        "estimated_time": r.get("estimated_time", 0.0),
        "risk_score": r.get("risk_score", 0.0),
        "congestion_score": r.get("congestion_score", 0.0),
        "congestion_label": r.get("congestion_label", "LOW"),
        "safety": r.get("safety", "SAFE"),
        "confidence": r.get("confidence", "HIGH"),
        "people_at_risk": plan.get("people_at_risk", 0),
        "bottlenecks": r.get("bottlenecks", []),
        "simulation_id": plan.get("simulation_id"),
        "route_version": plan.get("route_version", 1),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "source": plan.get("source", "api"),
        "alternatives": plan.get("alternatives", []),
        "evacuation": plan.get("evacuation"),
        "vehicle": plan.get("vehicle"),
    }


def _validate_mode(mode: str | None) -> str | None:
    if mode is None:
        return None
    if mode not in MODE_KEYS:
        raise HTTPException(400, f"Unknown route mode '{mode}'. Valid: {list(MODE_KEYS)}")
    return mode


# ------------------------------------------------------------ graph & calc
@router.get("/routes/graph")
def route_graph(principal: dict = Depends(require("read"))):
    """§4 — current campus graph (static topology + dynamic edge state)."""
    state = get_state()
    g = rs.get_route_graph(state)
    payload = g.to_dict()
    payload["mode"] = state.route_mode
    payload["simulation_id"] = rs.active_simulation_id(state)
    return payload


@router.post("/routes/calculate")
def calculate(body: RouteCalculate, principal: dict = Depends(require("apply")),
              db: Session = Depends(get_db)):
    """§25 — calculate a point-to-point route. 400 on bad mode/nodes/sim id."""
    state = get_state()
    _check_simulation_id(body.simulation_id)
    try:
        plan = rs.calculate(state, body.origin, body.destination, mode=body.mode,
                            people=body.people, alternatives=body.alternatives,
                            source="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "route.calculate", actor=principal.get("username", "?"),
          entity=body.origin, detail=f"{body.mode}->{body.destination}")
    return _plan_response(plan)


@router.post("/routes/recalculate")
def recalculate(body: RouteRecalculate | None = None,
                principal: dict = Depends(require("apply"))):
    """§10/§26 — force revalidation of the active plan (invalidation aware)."""
    state = get_state()
    body = body or RouteRecalculate()
    _check_simulation_id(body.simulation_id)
    if body.mode is not None:
        _validate_mode(body.mode)
        state.route_mode = body.mode
    result = rs.revalidate(state, force=True)
    if state.route_plan is None:
        raise HTTPException(404, "No active route plan to recalculate")
    return {"recalculated": True, "reason": body.reason, **result,
            "route": _plan_response(state.route_plan),
            "evacuation": _evacuation_summary(state)}


@router.get("/routes/alternatives")
def alternatives(origin: str, destination: str, mode: str = "balanced",
                 limit: int = 3, principal: dict = Depends(require("read"))):
    """§9/§21 — recommended + alternatives + cross-mode comparison."""
    state = get_state()
    try:
        data = rs.alternatives_for(state, origin, destination, mode=mode, limit=limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return data


# ------------------------------------------------------------- evacuation
@router.get("/routes/evacuation")
def evacuation_routes(mode: str | None = None,
                      principal: dict = Depends(require("read"))):
    """§8/§12 — campus evacuation overview (refreshed from effective state)."""
    state = get_state()
    _validate_mode(mode)
    campus = rs.refresh_evacuation(state, mode=mode, source="api")
    return {**_evacuation_summary(state), "buildings": campus.get("buildings", []),
            "exits": campus.get("exits", []),
            "bottlenecks": campus.get("bottlenecks", []),
            "totals": campus.get("totals", {}),
            "generated_at": campus.get("generated_at")}


@router.get("/evacuation/status")
def evacuation_status(principal: dict = Depends(require("read"))):
    """Live evacuation state + active plan summary (§8 status field)."""
    state = get_state()
    rs.refresh_evacuation(state, source="api")   # content-gated: no event spam
    return {**_evacuation_summary(state),
            "active_plan": _plan_response(state.route_plan) if state.route_plan else None,
            "route_history_recent": state.route_history[:10]}


@router.get("/evacuation/building/{building_id}")
def building_evacuation(building_id: str, mode: str | None = None,
                        principal: dict = Depends(require("read"))):
    """§15 — building plan: primary + alternatives + exit roles (activates plan)."""
    state = get_state()
    _validate_mode(mode)
    try:
        plan = rs.building_evacuation(state, building_id, mode=mode, activate=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return plan


# ---------------------------------------------------- emergency vehicles
@router.get("/routes/emergency")
def emergency_routes(vehicle: str | None = None, origin: str | None = None,
                     destination: str | None = None,
                     principal: dict = Depends(require("read"))):
    """§16 — emergency vehicle route(s) to the active incident/simulation."""
    state = get_state()
    if vehicle is not None and vehicle not in VEHICLE_KEYS:
        raise HTTPException(400, f"Unknown vehicle '{vehicle}'. Valid: {list(VEHICLE_KEYS)}")
    try:
        data = rs.emergency_routes(state, vehicle=vehicle, origin=origin,
                                   destination=destination, activate=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return data


@router.get("/emergency-response/routes")
def emergency_response_routes(vehicle: str | None = None, origin: str | None = None,
                              destination: str | None = None,
                              principal: dict = Depends(require("read"))):
    """§24 — alias surface for emergency response (all vehicles, incident target)."""
    state = get_state()
    if vehicle is not None and vehicle not in VEHICLE_KEYS:
        raise HTTPException(400, f"Unknown vehicle '{vehicle}'. Valid: {list(VEHICLE_KEYS)}")
    data = rs.emergency_routes(state, vehicle=vehicle, origin=origin,
                               destination=destination, activate=False)
    return {"vehicles": list(VEHICLE_KEYS), **data}


# ---------------------------------------------------- bottlenecks/history
@router.get("/routes/bottlenecks")
def bottlenecks(principal: dict = Depends(require("read"))):
    """§13 — structured bottleneck list (no LLM output)."""
    state = get_state()
    campus = rs.refresh_evacuation(state, source="api")
    return {"bottlenecks": campus.get("bottlenecks", []),
            "exits": campus.get("exits", []),
            "status": campus.get("status", "IDLE"),
            "simulation_id": campus.get("simulation_id")}


@router.get("/routes/history")
def route_history(limit: int = 50, simulation_id: str | None = None,
                  principal: dict = Depends(require("read")),
                  db: Session = Depends(get_db)):
    """§33 — persisted route calculations (route_events, newest first)."""
    rows = rs.history(db, limit=limit, simulation_id=simulation_id)
    return {"history": rows, "recent_in_memory": state_history()}


def state_history() -> list[dict]:
    return get_state().route_history[:10]


# ------------------------------------------------------------- single route
@router.get("/routes/{route_id}")
def get_route(route_id: str, principal: dict = Depends(require("read")),
              db: Session = Depends(get_db)):
    """§24 — active plan first, then persisted evacuation_routes row."""
    state = get_state()
    if state.route_plan and state.route_plan["route_id"] == route_id:
        return _plan_response(state.route_plan)
    row = db.get(EvacuationRoute, route_id)
    if row is None:
        raise HTTPException(404, "Route not found")
    events = db.query(RouteEvent).filter(RouteEvent.route_id == route_id) \
        .order_by(RouteEvent.created_at).all()
    return {
        "route_id": row.id, "kind": row.kind, "mode": row.mode,
        "status": row.status, "reason": row.reason,
        "origin": row.origin_id, "destination": row.exit_id,
        "path": row.node_path, "node_path": row.node_path,
        "road_path": row.road_path, "distance": row.distance,
        "estimated_time": row.eta_s, "risk_score": row.risk,
        "congestion_score": row.congestion_score,
        "people_at_risk": row.people_at_risk,
        "simulation_id": row.simulation_id, "route_version": row.route_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "events": [{"event": e.event, "reason": e.reason,
                    "route_version": e.route_version,
                    "created_at": e.created_at.isoformat()} for e in events],
    }


# ------------------------------------------------------------------ utils
def _evacuation_summary(state) -> dict:
    ev = state.evacuation or {}
    return {
        "status": ev.get("status", "IDLE"),
        "mode": ev.get("mode", state.route_mode),
        "people_at_risk": ev.get("people_at_risk", 0),
        "critical_buildings": ev.get("critical_buildings", []),
        "blocked_buildings": ev.get("blocked_buildings", []),
        "totals": ev.get("totals", {}),
        "bottleneck_count": len(ev.get("bottlenecks", [])),
        "simulation_id": ev.get("simulation_id"),
        "route_version": state.route_version,
        "generated_at": ev.get("generated_at"),
    }
