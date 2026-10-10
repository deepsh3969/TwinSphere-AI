from fastapi import APIRouter, Depends

from app.core.database import db_status
from app.core.metrics import snapshot as metrics_snapshot
from app.core.security import get_current_principal
from app.services.state import get_state
from app.services.simulation_engine import SCENARIOS
from app.services.ai_service import ai_status

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    state = get_state()
    database = db_status()
    return {
        "status": "ok" if database else "degraded",
        "backend": "ok",
        "database": "ok" if database else "unavailable",
        "simulation_engine": "ok",
        "ai_engine": "ok",
        "version": "1.0.0",
        "uptime_state": state.status,
        "connected_clients": 0,
    }


@router.get("/api/system/status")
def system_status(principal: dict = Depends(get_current_principal)):
    state = get_state()
    return {
        "health": {
            "backend": True,
            "database": db_status(),
            "simulation": state.active_sim.status if state.active_sim else "idle",
            "ai": True,
        },
        "ai": ai_status(state),
        "metrics": state.metrics(),
        "clock_hour": round(state.clock_hour, 2),
        "speed": state.speed,
        "sim_status": state.sim_status,
        "status": state.status,
        "recovery_progress": state.recovery_progress,
        "scenarios": {k: v["label"] for k, v in SCENARIOS.items()},
    }


@router.get("/api/system/metrics")
def system_metrics(principal: dict = Depends(get_current_principal)):
    """Phase 11 — safe, bounded operational counters (uptime, HTTP, ws, sim)."""
    return metrics_snapshot()
