"""Phase 6 — Emergency What-If Simulation Engine (spec §61-§66)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from ai.simulation import building_status, intensity_label, smoke_band, smoke_severity
from ai.simulation.fire_simulation import INTENSITY_LEVELS
from app.core.database import SessionLocal
from app.core.security import create_token
from app.main import app
from app.models.entities import Simulation
from app.services import sensor_engine, simulation_engine as simeng
from app.services.demo import full_reset
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.runtime import runtime
from app.services.state import TwinState, get_state

client = TestClient(app)
ADMIN = {"Authorization": f"Bearer {create_token('u_admin', 'admin', 'ADMIN')}"}


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
        compute_risk(st)  # mirrors the runtime's risk cycle feeding peak_risk
        elapsed += step
    return events


def _fire(st: TwinState, target="eng", **params):
    p = {"intensity": 5, "wind": "NONE"}
    p.update(params)
    simeng.create_simulation(st, "fire", target, p)
    simeng.start_simulation(st, st.active_sim.id)
    return st.active_sim


# ---------------------------------------------------------------- §61 fire physics

def test_fire_ignition_zone_and_adjacency_propagation(state):
    sim = _fire(state)
    ign_id = sim.params["ignition_zone"]
    ign = state.zones[ign_id]
    assert ign.status == "FIRE" and ign.fire > 0.15
    assert ign.temperature >= 60.0

    _run(state, 90)
    burning = [z for z in state.zones.values() if z.fire > 0.05]
    assert len(burning) >= 2, "fire must spread to at least one adjacent zone"

    # every burning zone must be graph-reachable from the ignition zone
    reach, stack = {ign_id}, [ign_id]
    while stack:
        cur = state.zones[stack.pop()]
        for nid in cur.adjacent:
            if nid not in reach:
                reach.add(nid)
                stack.append(nid)
    assert {z.id for z in burning} <= reach, "fire may only spread along adjacency"


def test_fire_intensity_controls_growth(state):
    _fire(state, intensity=1)
    weak = state.active_sim
    _run(state, 60)
    weak_fire = sum(z.fire for z in state.zones.values())

    st2 = TwinState(seed=7)
    compute_routes(st2)
    compute_risk(st2)
    _fire(st2, intensity=5)
    _run(st2, 60)
    strong_fire = sum(z.fire for z in st2.zones.values())
    assert strong_fire > weak_fire > 0
    assert intensity_label(5) == INTENSITY_LEVELS[5] != intensity_label(1)


def test_wind_east_biases_spread(state):
    eng_zones = [z for z in state.zones.values() if z.building_id == "eng"]
    ign_id = min(eng_zones, key=lambda z: z.local_x).id  # west-most → east spread possible
    sim = _fire(state, wind="E", ignition_zone=ign_id)
    ign = state.zones[sim.params["ignition_zone"]]
    _run(state, 60)
    east_burning = [
        z for z in state.zones.values()
        if z.fire > 0.05 and z.building_id == ign.building_id and z.local_x > ign.local_x
    ]
    assert east_burning, "downwind (east) zones must catch fire under E wind"
    for nid in ign.adjacent:
        nb = state.zones.get(nid)
        if nb and nb.local_x < ign.local_x:
            assert nb.fire <= max(z.fire for z in east_burning)


def test_fire_temperature_smoke_and_weighted_people(state):
    sim = _fire(state)
    _run(state, 120)
    compute_risk(state)

    assert sim.peak_temperature >= 60.0
    assert sim.peak_smoke > 0
    assert smoke_severity(sim.peak_smoke) >= 1
    assert isinstance(smoke_band(smoke_severity(sim.peak_smoke)), str)

    assert sim.people_at_risk > 0
    assert 0.3 * sim.people_at_risk - 1 <= sim.weighted_people <= sim.people_at_risk
    assert sim.max_people_at_risk >= sim.people_at_risk
    assert sim.affected_zones >= 1

    assert state.risk["score"] > 40
    assert sim.peak_risk >= state.risk["score"]


def test_building_status_escalation_and_sensor_heat_coupling(state):
    sim = _fire(state, intensity=5)
    b = state.buildings["eng"]
    ambient = b.temperature

    _run(state, 30)
    assert b.status in ("ALERT", "DANGER", "CRITICAL")
    assert building_status(
        any_fire=True, burning_zones=1, max_fire=0.9, smoke_severity_idx=2, affected_zones=1,
    ) in ("DANGER", "CRITICAL")

    sensor_engine.tick_sensors(state, 5.0)
    assert b.temperature > ambient, "burning zones must heat their building's sensors"

    _run(state, 90)
    assert b.status in ("DANGER", "CRITICAL") or sim.status != "RUNNING"


# ------------------------------------------------- §62 pause / resume / reset deltas

def test_reset_clears_phase6_fields(state):
    sim = _fire(state, intensity=4)
    _run(state, 80)
    assert sim.max_people_at_risk > 0 or sim.peak_smoke > 0 or sim.affected_zones > 0

    simeng.reset_simulation(state, sim.id)
    assert sim.status == "CREATED"
    assert sim.peak_temperature <= 24.0 and sim.peak_smoke == 0.0
    assert sim.max_people_at_risk == 0 and sim.affected_zones == 0
    assert sim.weighted_people == 0 and sim.results == {}
    assert all(z.status == "NORMAL" and z.fire == 0 for z in state.zones.values())

    # a fresh run recomputes from zero
    simeng.start_simulation(state, sim.id)
    _run(state, 20)
    assert sim.peak_smoke > 0


# ------------------------------------------------------------------ §63 recovery

def test_recovery_is_gradual_and_computes_results(state):
    sim = _fire(state)
    _run(state, 120)
    simeng.recover_simulation(state, sim.id)
    assert sim.status == "RECOVERING"

    seen = []
    elapsed = 0.0
    while elapsed < 300 and sim.status == "RECOVERING":
        simeng.tick_simulation(state, 5.0)
        elapsed += 5.0
        seen.append(state.recovery_progress)

    assert sim.status == "COMPLETED"
    assert seen, "recovery must emit progress samples"
    assert all(0 <= p <= 100 for p in seen)
    assert seen[0] < 100, "recovery must not teleport to 100%"
    assert all(b >= a for a, b in zip(seen, seen[1:])), "progress must be monotonic"
    assert state.recovery_progress == 100.0

    assert sim.results, "completion must persist a results block"
    for key in ("scenario", "peak_risk", "peak_temperature", "peak_smoke",
                "affected_zone_count", "recovery_time_s", "events"):
        assert key in sim.results, f"results missing {key}"
    assert sim.results["scenario"] == "fire"
    assert sim.results["recovery_time_s"] > 0

    b = state.buildings["eng"]
    assert b.status == "OPERATIONAL" and b.power is True
    assert state.status == "NORMAL"
    assert all(z.status == "NORMAL" for z in state.zones.values())

    with SessionLocal() as db:
        row = db.get(Simulation, sim.id)
        assert row is not None and row.status == "COMPLETED"
        assert (row.result or {}).get("results", {}).get("scenario") == "fire"


# ------------------------------------------------------------ §64 non-fire deltas

def test_crowd_scenario_density_and_occupancy(state):
    simeng.create_simulation(state, "crowd", "lib", {"occupancy_increase": 80})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    _run(state, 60)
    zones = [z for z in state.zones.values() if z.building_id == "lib"]
    assert any(z.occupancy > 0 for z in zones)
    assert sim.people_at_risk >= 0
    simeng.recover_simulation(state, sim.id)
    _run(state, 200)
    assert sim.status == "COMPLETED"
    assert sim.results.get("scenario") == "crowd"


def test_power_scenario_services_and_recovery(state):
    simeng.create_simulation(state, "power", "clinic", {})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    b = state.buildings["clinic"]
    assert b.power is False and b.status == "POWER_FAILURE"
    assert sim.results == {} or "scenario" not in sim.results  # only set on completion

    simeng.recover_simulation(state, sim.id)
    _run(state, 200)
    assert b.power is True and b.status == "OPERATIONAL"
    assert sim.status == "COMPLETED" and sim.results["scenario"] == "power"


def test_road_scenario_blocks_and_reopens(state):
    simeng.create_simulation(state, "road", None, {"road_id": "r_cc_ce"})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    assert state.roads["r_cc_ce"]["blocked"] is True
    simeng.recover_simulation(state, sim.id)
    assert state.roads["r_cc_ce"]["blocked"] is False
    _run(state, 160)
    assert sim.status == "COMPLETED" and sim.results["scenario"] == "road"


def test_temperature_scenario_peak_tracking(state):
    simeng.create_simulation(state, "temperature", None, {})
    sim = state.active_sim
    simeng.start_simulation(state, sim.id)
    _run(state, 90)
    assert sim.status in ("RUNNING", "AWAITING_RECOVERY")
    simeng.recover_simulation(state, sim.id)
    _run(state, 200)
    assert sim.status == "COMPLETED"
    assert sim.results["scenario"] == "temperature"


# ------------------------------------------------------ §65 validation + endpoints

def test_create_validation_errors_are_400():
    cases = [
        ("volcano", None, {}),
        ("fire", "eng", {"intensity": 0}),
        ("fire", "eng", {"intensity": 11}),
        ("fire", "eng", {"wind": "UP"}),
        ("fire", "eng", {"ignition_zone": "no_such_zone"}),
        ("fire", "eng", {"zone_id": "no_such_zone"}),
        ("fire", "nowhere", {}),
        ("fire", None, {}),
        ("power", None, {}),
        ("crowd", "eng", {"occupancy_increase": 500}),
        ("road", None, {"road_id": "r_nope"}),
    ]
    try:
        for scenario, target, params in cases:
            r = client.post("/api/simulations", headers=ADMIN,
                            json={"scenario": scenario, "target_id": target, "params": params})
            # target-not-found is REST-404, parameter problems are 400 (§52)
            expected = (400, 404) if target == "nowhere" else (400,)
            assert r.status_code in expected, f"{scenario}/{params} -> {r.status_code}: {r.text}"
    finally:
        full_reset(get_state())


def test_single_active_simulation_conflict():
    st = get_state()
    try:
        full_reset(st)
        r1 = client.post("/api/simulations", headers=ADMIN,
                         json={"scenario": "fire", "target_id": "eng",
                               "params": {"intensity": 3, "wind": "E"}})
        assert r1.status_code in (200, 201), r1.text
        sim_id = r1.json()["id"]
        r_start = client.post(f"/api/simulations/{sim_id}/start", headers=ADMIN)
        assert r_start.status_code == 200, r_start.text

        r2 = client.post("/api/simulations", headers=ADMIN,
                         json={"scenario": "power", "target_id": "clinic", "params": {}})
        assert r2.status_code == 409
        assert "already running" in r2.json()["detail"]

        # detail + live results endpoints (§53/§48)
        r3 = client.get(f"/api/simulations/{sim_id}", headers=ADMIN)
        assert r3.status_code == 200 and r3.json()["id"] == sim_id
        r4 = client.get(f"/api/simulations/{sim_id}/results", headers=ADMIN)
        assert r4.status_code == 200
        body = r4.json()
        assert body["live"] is True and body["results"]["scenario"] == "fire"
        assert "peak_temperature" in body["results"]

        r5 = client.get("/api/simulations/sim_does_not_exist", headers=ADMIN)
        r6 = client.get("/api/simulations/sim_does_not_exist/results", headers=ADMIN)
        assert r5.status_code == 404 and r6.status_code == 404
    finally:
        full_reset(st)
        full_reset(get_state())


def test_results_endpoint_for_history_row():
    st = get_state()
    try:
        full_reset(st)
        r1 = client.post("/api/simulations", headers=ADMIN,
                         json={"scenario": "road", "target_id": None,
                               "params": {"road_id": "r_cc_ce"}})
        assert r1.status_code in (200, 201), r1.text
        sim_id = r1.json()["id"]
        client.post(f"/api/simulations/{sim_id}/start", headers=ADMIN)
        client.post(f"/api/simulations/{sim_id}/recover", headers=ADMIN)
        _run(st, 200, step=10)
        assert st.active_sim is None or st.active_sim.status in ("COMPLETED", "CREATED")

        r = client.get(f"/api/simulations/{sim_id}/results", headers=ADMIN)
        assert r.status_code == 200
        body = r.json()
        assert body["live"] is False or body["status"] in ("COMPLETED", "RUNNING")
        assert body["results"]
    finally:
        full_reset(get_state())


def test_history_results_payload_contains_phase6_block():
    st = TwinState(seed=7)
    compute_routes(st)
    compute_risk(st)
    simeng.create_simulation(st, "fire", "lib", {"intensity": 4, "wind": "SE"})
    sim = st.active_sim
    simeng.start_simulation(st, sim.id)
    _run(st, 100)
    simeng.recover_simulation(st, sim.id)
    _run(st, 260)
    assert sim.status == "COMPLETED"
    assert sim.results["wind"] == "SE"
    assert sim.results["intensity"] == 4
    assert sim.results["peak_risk_level"]


# ------------------------------------------------------- §27/§66 events + runtime

def test_lifecycle_events_are_queued_for_websocket(state):
    simeng.create_simulation(state, "fire", "eng", {"intensity": 3, "wind": "N"})
    assert state.pending_sim_events and state.pending_sim_events[-1]["event"] == "simulation.created"
    sim = state.active_sim

    simeng.start_simulation(state, sim.id)
    assert state.pending_sim_events[-1]["event"] == "simulation.started"
    assert state.pending_sim_events[-1]["data"]["id"] == sim.id

    _run(state, 40)
    assert not any(e["event"] == "simulation.recovery_progress" for e in state.pending_sim_events)

    # cap keeps the queue bounded (backpressure)
    for _ in range(80):
        simeng.queue_sim_event(state, "simulation.tick", {"id": sim.id, "n": _})
    assert len(state.pending_sim_events) <= 60

    # runtime flush drains the runtime-owned (global) queue
    g = get_state()
    g.pending_sim_events = [{"event": "simulation.tick", "data": {"id": sim.id}}
                            for _ in range(3)]
    asyncio.run(runtime._flush_sim_events())
    assert g.pending_sim_events == []


def test_incident_carries_simulation_id(state):
    sim = _fire(state)
    fire = [i for i in state.incidents if i.get("kind") == "FIRE"]
    assert fire, "starting a fire must raise an incident"
    assert fire[0].get("simulation_id") == sim.id


def test_simulation_telemetry_payload_shape(state):
    sim = _fire(state)
    seen: list[tuple[str, dict]] = []

    async def _capture(event, data):
        seen.append((event, data))

    import app.services.runtime as rt_mod
    original = rt_mod.manager.emit
    original_state = runtime.state
    rt_mod.manager.emit = _capture  # type: ignore[assignment]
    runtime.state = state  # telemetry must observe the fixture's twin
    try:
        # first call primes the zone-status diff baseline (ignition only)
        asyncio.run(runtime._emit_simulation_telemetry(sim))
        seen.clear()
        _run(state, 60)  # smoke + fire spread change zone statuses
        asyncio.run(runtime._emit_simulation_telemetry(sim))
    finally:
        runtime.state = original_state
        rt_mod.manager.emit = original  # type: ignore[assignment]

    kinds = [k for k, _ in seen]
    assert "simulation.tick" in kinds
    assert "simulation.risk_update" in kinds
    assert "simulation.zone_update" in kinds, "changed zones must be reported"
    tick = next(d for k, d in seen if k == "simulation.tick")
    for key in ("id", "status", "t", "progress", "people_at_risk", "affected_zones",
                "risk", "risk_level", "speed", "building_status"):
        assert key in tick, f"tick payload missing {key}"
    assert tick["id"] == sim.id and tick["status"] == "RUNNING"


# ------------------------------------------------------------------- §66 chain

def test_full_integration_chain(state):
    # create → start → run → pause → resume → recover → complete, one pass
    sim = _fire(state, intensity=4, wind="SW")
    assert state.pending_sim_events

    _run(state, 60)
    compute_risk(state)
    assert sim.people_at_risk > 0 and state.risk["score"] > 30
    kinds = [e["kind"] for e in sim.events]
    assert "ignition" in kinds

    simeng.pause_simulation(state, sim.id)
    t_frozen = sim.t
    simeng.tick_simulation(state, 10)
    assert sim.t == t_frozen

    simeng.resume_simulation(state, sim.id)
    _run(state, 30)
    assert sim.t > t_frozen

    simeng.recover_simulation(state, sim.id)
    _run(state, 300, step=5)
    assert sim.status == "COMPLETED"
    assert state.recovery_progress == 100.0
    assert sim.results["scenario"] == "fire"
    assert sim.results["recovery_time_s"] > 0
    assert sim.results["peak_people_at_risk"] >= sim.results["weighted_people_at_risk"] - 1
    assert all(z.status == "NORMAL" for z in state.zones.values())

    events = [e["event"] for e in state.pending_sim_events]
    assert "simulation.started" in events
    assert "simulation.recovery_started" in events
    assert "simulation.completed" in events
