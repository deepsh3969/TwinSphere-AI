"""Phase 4 — realtime campus simulation controls (spec §36/§37).

Endpoints:
  GET  /api/realtime/status   — authoritative simulator status
  POST /api/realtime/start    — STOPPED/PAUSED -> RUNNING
  POST /api/realtime/pause    — RUNNING -> PAUSED
  POST /api/realtime/resume   — PAUSED -> RUNNING
  POST /api/realtime/reset    — clock back to 10:00, telemetry to baseline, PAUSED
  POST /api/realtime/speed    — set speed to one of 1x/2x/5x/10x

Mutations require the `simulate` permission and are audited. Every change is
broadcast immediately as `simulation.status` + `system.status` + a `state`
frame so connected twins update without waiting for the next tick.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.database import get_db
from app.core.security import require
from app.schemas.common import RealtimeSpeed
from app.services import realtime, sensor_engine
from app.services.runtime import runtime
from app.services.state import (
    ALLOWED_SPEEDS,
    SIM_STATUS_PAUSED,
    SIM_STATUS_RUNNING,
    SIM_STATUS_STOPPED,
    TwinState,
    get_state,
)

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


async def _audit(db: Session, action: str, principal: dict, detail: str) -> None:
    await asyncio.to_thread(
        audit, db, action, actor=principal.get("username", "?"), detail=detail,
    )


async def _broadcast_change(state: TwinState) -> None:
    runtime.on_control_change()
    await realtime.broadcast_simulation_status(state)
    await realtime.broadcast_system_status(state)
    await runtime.push_state()


def _require_stoppable(state: TwinState) -> None:
    if state.sim_status == SIM_STATUS_STOPPED:
        raise HTTPException(400, "Simulation is stopped (SIMULATION_ENABLED=false) — start it first.")


@router.get("/status")
def realtime_status(principal: dict = Depends(require("read"))):
    return realtime.simulation_status(get_state())


@router.post("/start")
async def start(principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    if state.sim_status != SIM_STATUS_RUNNING:
        state.sim_status = SIM_STATUS_RUNNING
        await _audit(db, "realtime.start", principal, "Simulation started")
        await _broadcast_change(state)
    return realtime.simulation_status(state)


@router.post("/pause")
async def pause(principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    if state.sim_status == SIM_STATUS_PAUSED:
        return realtime.simulation_status(state)
    _require_stoppable(state)
    state.sim_status = SIM_STATUS_PAUSED
    await _audit(db, "realtime.pause", principal, "Simulation paused")
    await _broadcast_change(state)
    return realtime.simulation_status(state)


@router.post("/resume")
async def resume(principal: dict = Depends(require("simulate")), db: Session = Depends(get_db)):
    state = get_state()
    if state.sim_status == SIM_STATUS_RUNNING:
        return realtime.simulation_status(state)
    _require_stoppable(state)
    state.sim_status = SIM_STATUS_RUNNING
    await _audit(db, "realtime.resume", principal, "Simulation resumed")
    await _broadcast_change(state)
    return realtime.simulation_status(state)


@router.post("/reset")
async def reset(principal: dict = Depends(require("reset")), db: Session = Depends(get_db)):
    state = get_state()
    sensor_engine.reset_telemetry(state)
    state.sim_status = SIM_STATUS_PAUSED
    await _audit(db, "realtime.reset", principal,
                 "Simulation clock reset to 10:00; telemetry restored to baseline")
    await _broadcast_change(state)
    return realtime.simulation_status(state)


@router.post("/speed")
async def speed(body: RealtimeSpeed, principal: dict = Depends(require("simulate")),
                db: Session = Depends(get_db)):
    if body.speed not in ALLOWED_SPEEDS:
        allowed = ", ".join(f"{int(s)}x" for s in ALLOWED_SPEEDS)
        raise HTTPException(400, f"Invalid speed {body.speed} — allowed speeds: {allowed}")
    state = get_state()
    state.speed = float(body.speed)
    await _audit(db, "realtime.speed", principal, f"Simulation speed set to {int(body.speed)}x")
    await _broadcast_change(state)
    return realtime.simulation_status(state)
