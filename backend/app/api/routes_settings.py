from fastapi import APIRouter, Depends, HTTPException

from app.core.audit import audit
from app.core.database import get_db
from app.core.security import require
from app.schemas.common import SettingsUpdate
from app.services import ai_service, simulation_engine as simeng
from app.services.demo import DEMO_SCRIPT, full_reset
from app.services import demo_runner
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.state import get_state, reset_state

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_settings(principal: dict = Depends(require("read"))):
    state = get_state()
    from app.core.config import settings
    return {
        "speed": state.speed,
        "clock_hour": round(state.clock_hour, 3),
        "sensor_interval": settings.SENSOR_TICK_SECONDS,
        "random_seed": settings.RANDOM_SEED,
        "llm_configured": bool(settings.LLM_API_KEY),
        "scenario_params": {
            "fire": simeng.SCENARIOS["fire"],
            "crowd": simeng.SCENARIOS["crowd"],
            "power": simeng.SCENARIOS["power"],
            "road": simeng.SCENARIOS["road"],
            "temperature": simeng.SCENARIOS["temperature"],
        },
        "dev_controls_available": True,
    }


@router.post("/settings")
def update_settings(body: SettingsUpdate, principal: dict = Depends(require("manage")),
                    db=Depends(get_db)):
    state = get_state()
    from app.core.config import settings
    changed = {}
    if body.speed is not None:
        state.speed = body.speed
        changed["speed"] = body.speed
    if body.sensor_interval is not None:
        settings.SENSOR_TICK_SECONDS = body.sensor_interval
        changed["sensor_interval"] = body.sensor_interval
    if body.random_seed is not None:
        settings.RANDOM_SEED = body.random_seed
        changed["random_seed"] = body.random_seed
    audit(db, "settings.update", actor=principal.get("username", "?"), detail=str(changed))
    return {"status": "ok", "changed": changed}


@router.get("/demo/script")
def demo_script(principal: dict = Depends(require("read"))):
    return {"steps": DEMO_SCRIPT}


@router.get("/demo/status")
def demo_status(principal: dict = Depends(require("read"))):
    """Phase 12 — current demo run (or idle)."""
    return demo_runner.current_run() or {"status": "idle"}


@router.post("/demo/run", status_code=200)
def demo_run(principal: dict = Depends(require("reset")), db=Depends(get_db)):
    """Phase 12 — run the scripted demo deterministically (single-flight)."""
    try:
        out = demo_runner.start_run(get_state())
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    audit(db, "demo.run", actor=principal.get("username", "?"),
          detail=f"demo run {out.get('id', '?')}")
    return out


@router.post("/demo/stop")
def demo_stop(principal: dict = Depends(require("reset")), db=Depends(get_db)):
    """Phase 12 — stop the current demo run (idempotent)."""
    out = demo_runner.stop_run()
    audit(db, "demo.stop", actor=principal.get("username", "?"), detail="demo stopped")
    return out


@router.post("/demo/reset")
def demo_reset(principal: dict = Depends(require("reset")), db=Depends(get_db)):
    state = get_state()
    out = demo_runner.reset_demo(state)
    audit(db, "demo.reset", actor=principal.get("username", "?"), detail="Demo state reset")
    return out


@router.post("/demo/hard-reset")
def demo_hard_reset(principal: dict = Depends(require("manage")), db=Depends(get_db)):
    state = reset_state()
    # Keep the runtime loop's state reference in sync (Phase 12): after
    # reset_state() the global state is a new object; without this the
    # runtime would keep draining the stale queue.
    from app.services.runtime import runtime
    runtime.state = state
    ai_service.warm_series(state)
    from app.services.seed import load_sensor_history
    load_sensor_history(state)
    compute_routes(state)
    compute_risk(state)
    audit(db, "demo.hard_reset", actor=principal.get("username", "?"), detail="Twin state re-initialised")
    return {"status": "reinitialised", "metrics": state.metrics()}
