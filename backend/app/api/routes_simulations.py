from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.ratelimit import limit
from app.core.security import require
from app.models.entities import Simulation, SimulationEvent
from app.schemas.common import SimulationCreate
from app.services import simulation_engine as simeng
from app.services.state import get_state

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


@router.get("")
def list_simulations(principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.query(Simulation).order_by(Simulation.created_at.desc()).limit(50).all()
    state = get_state()
    active = state.active_sim.to_dict() if state.active_sim else None
    return {
        "active": active,
        "history": [
            {
                "id": r.id, "simulation_code": r.simulation_code,
                "scenario": r.scenario, "scenario_type": r.scenario,
                "target_id": r.target_id, "target_type": r.target_type,
                "status": r.status, "progress": r.progress, "peak_risk": r.peak_risk,
                "people_affected": r.people_affected, "recovery_time_s": r.recovery_time_s,
                "severity": r.severity,
                "simulation_speed": r.simulation_speed,
                "current_step": r.current_step, "total_steps": r.total_steps,
                "created_at": r.created_at.isoformat(),
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "params": r.params, "parameters": r.params,
                "result": r.result, "results": r.result,
            }
            for r in rows
        ],
    }


@router.post("", status_code=201)
def create_simulation(body: SimulationCreate, principal: dict = Depends(require("simulate")),
                      _: None = Depends(limit("simulation")),
                      db: Session = Depends(get_db)):
    state = get_state()
    if body.target_id and body.target_id not in state.buildings and body.scenario != "road":
        raise HTTPException(404, "Target building not found")
    if state.active_sim and state.active_sim.status in ("RUNNING", "PAUSED", "AWAITING_RECOVERY", "RECOVERING"):
        raise HTTPException(409, "An active simulation is already running. "
                                 "Please stop or recover the current simulation first.")
    try:
        sim = simeng.create_simulation(state, body.scenario, body.target_id, body.params,
                                       created_by=principal.get("username", "operator"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "simulation.create", actor=principal.get("username", "?"),
          entity=body.target_id or "", detail=body.scenario)
    return sim


@router.get("/active")
def active_simulation(principal: dict = Depends(require("read"))):
    state = get_state()
    return state.active_sim.to_dict() if state.active_sim else None


@router.get("/{sim_id}")
def get_simulation(sim_id: str, principal: dict = Depends(require("read")),
                   db: Session = Depends(get_db)):
    """Phase 6 §53 — single simulation by id (active first, then history)."""
    state = get_state()
    if state.active_sim and state.active_sim.id == sim_id:
        return state.active_sim.to_dict()
    row = db.get(Simulation, sim_id)
    if row is None:
        raise HTTPException(404, "Simulation not found")
    return {
        "id": row.id, "simulation_code": row.simulation_code,
        "scenario": row.scenario, "scenario_type": row.scenario,
        "target_id": row.target_id, "target_type": row.target_type,
        "status": row.status, "progress": row.progress, "peak_risk": row.peak_risk,
        "people_affected": row.people_affected, "recovery_time_s": row.recovery_time_s,
        "severity": row.severity, "params": row.params, "parameters": row.params,
        "results": (row.result or {}).get("results", row.result),
        "created_at": row.created_at.isoformat(),
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
    }


@router.get("/{sim_id}/results")
def simulation_results(sim_id: str, principal: dict = Depends(require("read")),
                       db: Session = Depends(get_db)):
    """Phase 6 §48 — results block (computed live for the active run)."""
    state = get_state()
    sim = state.active_sim
    if sim and sim.id == sim_id:
        return {"simulation_id": sim_id, "status": sim.status, "live": True,
                "results": simeng.compute_results(state, sim)}
    row = db.get(Simulation, sim_id)
    if row is None:
        raise HTTPException(404, "Simulation not found")
    results = (row.result or {}).get("results") or {
        "scenario": row.scenario, "peak_risk": row.peak_risk,
        "recovery_time_s": row.recovery_time_s, "status": row.status,
    }
    return {"simulation_id": sim_id, "status": row.status, "live": False,
            "results": results,
            "created_at": row.created_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None}


def _sim_or_404(state, sim_id: str) -> None:
    if state.active_sim is None or state.active_sim.id != sim_id:
        raise HTTPException(404, "Simulation not found")


@router.post("/{sim_id}/start")
def start(sim_id: str, principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    _sim_or_404(state, sim_id)
    try:
        out = simeng.start_simulation(state, sim_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "simulation.start", actor=principal.get("username", "?"), entity=sim_id)
    return out


@router.post("/{sim_id}/pause")
def pause(sim_id: str, principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    _sim_or_404(state, sim_id)
    try:
        out = simeng.pause_simulation(state, sim_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "simulation.pause", actor=principal.get("username", "?"), entity=sim_id)
    return out


@router.post("/{sim_id}/resume")
def resume(sim_id: str, principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    _sim_or_404(state, sim_id)
    try:
        out = simeng.resume_simulation(state, sim_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "simulation.resume", actor=principal.get("username", "?"), entity=sim_id)
    return out


@router.post("/{sim_id}/reset")
def reset(sim_id: str, principal: dict = Depends(require("reset")), db: Session = Depends(get_db)):
    state = get_state()
    _sim_or_404(state, sim_id)
    try:
        out = simeng.reset_simulation(state, sim_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "simulation.reset", actor=principal.get("username", "?"), entity=sim_id)
    return out


@router.post("/{sim_id}/recover")
def recover(sim_id: str, principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    _sim_or_404(state, sim_id)
    try:
        out = simeng.recover_simulation(state, sim_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit(db, "simulation.recover", actor=principal.get("username", "?"), entity=sim_id)
    return out


@router.get("/{sim_id}/events")
def events(sim_id: str, principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    rows = db.query(SimulationEvent).filter(SimulationEvent.simulation_id == sim_id) \
        .order_by(SimulationEvent.t).all()
    state = get_state()
    live = state.active_sim.events if state.active_sim and state.active_sim.id == sim_id else []
    return {
        "persisted": [{"t": r.t, "kind": r.kind, "message": r.message, "data": r.data} for r in rows],
        "live": live,
    }
