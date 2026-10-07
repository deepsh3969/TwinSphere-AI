import pytest

from app.core.database import SessionLocal
from app.models.entities import Simulation
from app.services import simulation_engine as simeng
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.seed import init_db, seed_data
from app.services.state import TwinState


@pytest.fixture()
def state():
    st = TwinState(seed=7)
    compute_routes(st)
    compute_risk(st)
    return st


def _run(st: TwinState, seconds: float, step: float = 5.0):
    elapsed = 0.0
    events = []
    while elapsed < seconds:
        events.extend(simeng.tick_simulation(st, step))
        elapsed += step
    return events


def test_fire_lifecycle_events_and_recovery(state):
    simeng.create_simulation(state, "fire", "eng", {"intensity": 6, "wind": "E"})
    sim = state.active_sim
    assert sim.status == "CREATED"

    simeng.start_simulation(state, sim.id)
    assert sim.status == "RUNNING"
    assert any(i["kind"] == "FIRE" for i in state.incidents)

    events = _run(state, 260, step=10)
    compute_risk(state)
    kinds = [e["kind"] for e in events] + [e["kind"] for e in sim.events]
    for expected in ("smoke_detected", "risk_zone_expanding", "zones_affected",
                     "routes_recalculated", "people_at_risk", "route_optimized",
                     "response_recommended"):
        assert expected in kinds, f"missing phase {expected}: {kinds}"

    assert state.risk["score"] > 40
    assert state.buildings["eng"].risk > 40
    assert sim.people_at_risk >= 0
    assert any(z.status == "FIRE" for z in state.zones.values() if z.building_id == "eng")
    assert len(state.recommendations) >= 1

    routes = [r for r in state.routes if r["building_id"] == "eng"]
    assert routes and all(r["exit_id"] for r in routes)

    simeng.recover_simulation(state, sim.id)
    assert sim.status == "RECOVERING"
    _run(state, 200, step=5)
    assert state.recovery_progress == 100.0
    assert sim.status == "COMPLETED"
    assert state.status == "NORMAL"
    assert all(z.status == "NORMAL" for z in state.zones.values() if z.building_id == "eng")
    assert state.buildings["eng"].status == "OPERATIONAL"

    with SessionLocal() as db:
        row = db.get(Simulation, sim.id)
        assert row is not None
        assert row.status == "COMPLETED"
        assert row.peak_risk >= 40


def test_pause_resume_reset(state):
    simeng.create_simulation(state, "crowd", "lib", {"occupancy_increase": 60})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    _run(state, 40, step=5)
    simeng.pause_simulation(state, sim.id)
    assert sim.status == "PAUSED"
    t_frozen = sim.t
    simeng.tick_simulation(state, 20)
    assert sim.t == t_frozen, "paused simulation must not advance"
    simeng.resume_simulation(state, sim.id)
    _run(state, 20, step=5)
    assert sim.t > t_frozen
    simeng.reset_simulation(state, sim.id)
    assert sim.status == "CREATED"
    assert sim.t == 0
    assert state.status == "NORMAL"


def test_road_closure_blocks_and_reroutes(state):
    before = {r["id"]: r["status"] for r in state.routes}
    simeng.create_simulation(state, "road", None, {"road_id": "r_cc_ce"})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    assert state.roads["r_cc_ce"]["blocked"] is True
    compute_routes(state)
    blocked = [r for r in state.routes if r["status"] == "BLOCKED"]
    for r in state.routes:
        assert "r_cc_ce" not in r["road_path"], "blocked road must not appear in any route"
    compute_risk(state)
    assert state.risk["score"] > 0
    simeng.recover_simulation(state, sim.id)
    assert state.roads["r_cc_ce"]["blocked"] is False
    _run(state, 120, step=10)
    assert sim.status == "COMPLETED"


def test_power_failure_effects(state):
    simeng.create_simulation(state, "power", "clinic", {})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    b = state.buildings["clinic"]
    assert b.power is False
    assert b.status == "POWER_FAILURE"
    assert b.backup_power is True  # clinic has generator
    compute_risk(state)
    assert state.building_risk["clinic"]["score"] > 10
    assert any(r["action"] == "activate_backup" for r in state.recommendations)
    simeng.recover_simulation(state, sim.id)
    _run(state, 160, step=10)
    assert b.power is True
    assert b.status == "OPERATIONAL"


def test_extreme_temperature_scenario(state):
    simeng.create_simulation(state, "temperature", None, {})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    _run(state, 120, step=10)
    assert sim.status in ("RUNNING", "AWAITING_RECOVERY")
    assert any(e["kind"] == "clinic_standby" for e in sim.events)
    simeng.recover_simulation(state, sim.id)
    _run(state, 160, step=10)
    assert sim.status == "COMPLETED"


def test_full_reset_clears_effects(state):
    simeng.create_simulation(state, "fire", "lib", {"intensity": 8, "wind": "S"})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    _run(state, 80, step=10)
    assert any(z.fire > 0 for z in state.zones.values())
    from app.services.demo import full_reset
    out = full_reset(state)
    assert out["status"] == "reset"
    assert state.active_sim is None
    assert all(z.fire == 0 and z.status == "NORMAL" for z in state.zones.values())
    assert state.status == "NORMAL"
