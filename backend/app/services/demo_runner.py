"""Phase 12 — scripted, deterministic, single-flight demo runner.

Runs the DEMO_SCRIPT steps against the in-process twin state (no HTTP loop),
so a presentation can be reproduced from a known initial state without
frontend timing dependencies.  Only one demo may run at a time; resets are
idempotent and never touch unrelated user data or audit history.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

from app.services.demo import DEMO_SCRIPT, full_reset
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.state import TwinState, get_state

log = logging.getLogger("twinsphere.demo")

_lock = threading.Lock()
_current: dict | None = None  # {id, step_index, status, started_at, log[]}


def current_run() -> dict | None:
    with _lock:
        return dict(_current) if _current else None


def _set(step_index: int | None, status: str, entry: str | None = None) -> None:
    global _current
    with _lock:
        if _current is None:
            return
        if step_index is not None:
            _current["step_index"] = step_index
        _current["status"] = status
        if entry is not None:
            _current["log"].append(entry)
            if len(_current["log"]) > 100:
                _current["log"] = _current["log"][-100:]


def _apply_action(state: TwinState, action: dict) -> str:
    """Apply one demo action directly to state.  Returns a short note."""
    atype = action.get("type", "")
    if atype in ("navigate", "wait", "watch", "show_predictions",
                 "show_routes", "show_route_panel", "show_ai"):
        # Frontend-only cues; nothing to mutate server-side.
        return atype
    if atype == "select_building":
        return f"select:{action.get('target', '?')}"
    if atype == "start_simulation":
        from app.services import simulation_engine as simeng

        scenario = action.get("target", "fire")
        building = action.get("building")
        params = action.get("params") or {}
        # Full reset first so a rerun starts from the same state.
        full_reset(state)
        sim = simeng.create_simulation(
            state, scenario, building, params, created_by="demo")
        sim_id = sim["id"] if isinstance(sim, dict) else sim.id
        simeng.start_simulation(state, sim_id)
        # Deterministic virtual ticking so risk/routes reflect the incident.
        for _ in range(30):
            simeng.tick_simulation(state, dt=15.0)
        compute_risk(state)
        compute_routes(state, primary_building=building)
        return f"sim:{scenario}:{sim_id}"
    if atype == "apply_recommendation":
        # Nudge the primary route to demonstrate an authorized action.
        compute_routes(state, primary_building="eng")
        return "routes-recomputed"
    if atype == "recover":
        sim = state.active_sim
        if sim:
            simeng = __import__("app.services.simulation_engine", fromlist=["x"])
            try:
                simeng.recover_simulation(state, sim.id)
            except ValueError:
                pass
        full_reset(state)
        return "recovered"
    return atype


def start_run(state: TwinState | None = None) -> dict:
    """Start a demo run.  Raises RuntimeError if one is already active."""
    global _current
    with _lock:
        if _current is not None and _current["status"] == "running":
            raise RuntimeError("A demo run is already active")
        run_id = uuid.uuid4().hex[:12]
        _current = {
            "id": run_id,
            "step_index": 0,
            "status": "running",
            "started_at": time.time(),
            "log": [f"demo:{run_id}:started"],
        }
    state = state or get_state()
    try:
        # Step 0: deterministic initial state.
        full_reset(state)
        _set(0, "running", "initial-state-reset")
        for i, step in enumerate(DEMO_SCRIPT, start=1):
            note = _apply_action(state, step.get("action", {}))
            _set(i, "running", f"step:{step['id']}:{step.get('title', '')}:{note}")
        _set(len(DEMO_SCRIPT), "completed", "demo:completed")
        with _lock:
            result = dict(_current) if _current else {}
        return result
    except Exception as exc:  # pragma: no cover — defensive
        _set(None, "failed", f"error:{exc}")
        log.exception("demo run failed")
        raise


def stop_run() -> dict:
    """Stop the current demo run (idempotent)."""
    global _current
    with _lock:
        if _current is None:
            return {"status": "idle"}
        _current["status"] = "stopped"
        _current["log"].append("demo:stopped")
        result = dict(_current)
        _current = None
        return result


def reset_demo(state: TwinState | None = None) -> dict:
    """Reset demo state without starting a new run (idempotent)."""
    state = state or get_state()
    stop_run()
    return full_reset(state)
