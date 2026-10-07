"""Phase 4 — realtime simulation: status payloads, controls, RBAC, context."""

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_token
from app.main import app
from app.services import realtime, sensor_engine
from app.services import simulation_engine as simeng
from app.services.state import (
    START_CLOCK,
    TwinState,
    build_simulation_context,
    get_state,
)

client = TestClient(app)  # no lifespan: routes use lazy state + seeded test DB


def _headers(role: str = "ADMIN", username: str = "admin") -> dict:
    token = create_token(f"u_{username}", username, role)
    return {"Authorization": f"Bearer {token}"}


ADMIN = _headers()
VIEWER = _headers("VIEWER", "viewer")


@pytest.fixture(autouse=True)
def _isolate_state():
    """Save/restore mutable twin state so endpoint tests stay independent."""
    st = get_state()
    scalar = (st.sim_status, st.speed, st.clock, st.last_tick_at, st.tick_count)
    sensors = {sid: (s.value, s.healthy, s.updated_at) for sid, s in st.sensors.items()}
    buildings = {bid: (b.occupancy, b.temperature, b.humidity, b.energy, b.water,
                       b.smoke, b.air_quality, b.power, b.backup_power)
                 for bid, b in st.buildings.items()}
    zones = {zid: z.occupancy for zid, z in st.zones.items()}
    yield
    st.sim_status, st.speed, st.clock, st.last_tick_at, st.tick_count = scalar
    for sid, (value, healthy, updated_at) in sensors.items():
        s = st.sensors[sid]
        s.value, s.healthy, s.updated_at = value, healthy, updated_at
    for bid, values in buildings.items():
        b = st.buildings[bid]
        (b.occupancy, b.temperature, b.humidity, b.energy, b.water,
         b.smoke, b.air_quality, b.power, b.backup_power) = values
    for zid, occ in zones.items():
        st.zones[zid].occupancy = occ
    st.sim_context = build_simulation_context(st)


# ---------------------------------------------------------------- endpoints
def test_status_endpoint_shape():
    r = client.get("/api/realtime/status", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("RUNNING", "PAUSED", "STOPPED")
    for key in ("speed", "simulation_time", "clock", "clock_hour", "last_tick",
                "tick_count", "sensor_interval", "enabled", "connected_clients",
                "data_source", "seed"):
        assert key in body, key
    assert body["data_source"] == "SIMULATED"
    assert body["speed"] in (1.0, 2.0, 5.0, 10.0)


def test_status_requires_auth_and_rbac():
    assert client.get("/api/realtime/status").status_code == 401
    assert client.get("/api/realtime/status", headers=VIEWER).status_code == 200
    # viewers can read but never control
    assert client.post("/api/realtime/pause", headers=VIEWER).status_code == 403
    assert client.post("/api/realtime/start", headers=VIEWER).status_code == 403
    assert client.post("/api/realtime/speed", json={"speed": 2},
                       headers=VIEWER).status_code == 403
    assert client.post("/api/realtime/reset", headers=VIEWER).status_code == 403


def test_pause_resume_idempotent():
    p = client.post("/api/realtime/pause", headers=ADMIN)
    assert p.status_code == 200 and p.json()["status"] == "PAUSED"
    again = client.post("/api/realtime/pause", headers=ADMIN)
    assert again.status_code == 200 and again.json()["status"] == "PAUSED"
    r = client.post("/api/realtime/resume", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "RUNNING"
    same = client.post("/api/realtime/resume", headers=ADMIN)
    assert same.status_code == 200 and same.json()["status"] == "RUNNING"


def test_start_from_paused_and_idempotent():
    client.post("/api/realtime/pause", headers=ADMIN)
    s = client.post("/api/realtime/start", headers=ADMIN)
    assert s.status_code == 200 and s.json()["status"] == "RUNNING"
    again = client.post("/api/realtime/start", headers=ADMIN)
    assert again.status_code == 200 and again.json()["status"] == "RUNNING"


def test_stopped_sim_rejects_pause_and_resume():
    st = get_state()
    st.sim_status = "STOPPED"
    assert client.post("/api/realtime/pause", headers=ADMIN).status_code == 400
    assert client.post("/api/realtime/resume", headers=ADMIN).status_code == 400
    s = client.post("/api/realtime/start", headers=ADMIN)
    assert s.status_code == 200 and s.json()["status"] == "RUNNING"


def test_speed_validation():
    ok = client.post("/api/realtime/speed", json={"speed": 5}, headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["speed"] == 5
    for bad in (3, 0.5, 15):
        r = client.post("/api/realtime/speed", json={"speed": bad}, headers=ADMIN)
        assert r.status_code == 400, bad
        assert "speed" in r.json()["detail"].lower()
    client.post("/api/realtime/speed", json={"speed": 1}, headers=ADMIN)


def test_reset_restores_baseline_and_pauses():
    st = get_state()
    st.clock = START_CLOCK + 5 * 3600  # move the clock well past 10:00
    st.sensors["temperature_eng"].value = 999.0
    st.buildings["eng"].occupancy = st.buildings["eng"].capacity  # full house

    r = client.post("/api/realtime/reset", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAUSED"
    assert abs(body["simulation_time"] - START_CLOCK) < 1
    assert body["last_tick"] is None
    assert st.clock == START_CLOCK
    assert st.sensors["temperature_eng"].value == st.sensors["temperature_eng"].baseline
    eng = st.buildings["eng"]
    assert eng.occupancy < eng.capacity  # back on the diurnal curve
    # zones redistributed consistently with the building total
    zones = [z for z in st.zones.values() if z.building_id == "eng"]
    assert sum(z.occupancy for z in zones) <= eng.occupancy + len(zones)


def test_control_changes_are_audited():
    from app.core.database import SessionLocal
    from app.models.entities import AuditLog
    client.post("/api/realtime/pause", headers=ADMIN)
    with SessionLocal() as db:
        rows = (db.query(AuditLog).filter(AuditLog.action == "realtime.pause")
                .order_by(AuditLog.created_at.desc()).first())
    assert rows is not None
    assert rows.actor == "admin"


# ------------------------------------------------------------ state/context
def test_snapshot_carries_sim_status_and_speed():
    st = get_state()
    snap = st.snapshot()
    assert snap["sim_status"] in ("RUNNING", "PAUSED", "STOPPED")
    assert snap["speed"] == st.speed


def test_system_status_payload_via_service():
    st = get_state()
    body = realtime.system_status(st, connected=3)
    for key in ("backend", "database", "websocket", "simulator", "connected_clients",
                "risk_level", "incidents", "metrics"):
        assert key in body, key
    assert body["connected_clients"] == 3
    assert body["simulator"] == st.sim_status


def test_context_defaults_are_neutral():
    st = TwinState(seed=3)
    ctx = build_simulation_context(st)
    assert ctx.active is False
    assert ctx.occupancy_multiplier == 1.0
    assert ctx.occupancy_delta == 0.0
    assert ctx.temperature_offset == 0.0
    assert ctx.energy_multiplier == 1.0
    assert ctx.smoke_multiplier == 1.0
    assert ctx.blocked_zones == [] and ctx.blocked_roads == []


def test_context_builder_consumes_no_rng():
    st = TwinState(seed=3)
    before = st.rng.getstate()
    build_simulation_context(st)
    build_simulation_context(st)
    assert st.rng.getstate() == before


def test_context_from_crowd_simulation():
    st = TwinState(seed=3)
    simeng.create_simulation(st, "crowd", "eng", {"occupancy_increase": 60})
    simeng.start_simulation(st, st.active_sim.id)
    st.active_sim.t = 45.0
    ctx = build_simulation_context(st)
    assert ctx.active is True
    assert ctx.scenario == "crowd" and ctx.target_id == "eng"
    assert ctx.occupancy_multiplier > 1.0
    assert ctx.occupancy_cap_fraction == 1.15


def test_context_from_temperature_simulation():
    st = TwinState(seed=3)
    simeng.create_simulation(st, "temperature", None, {})
    simeng.start_simulation(st, st.active_sim.id)
    ctx = build_simulation_context(st)
    assert ctx.active is True
    assert ctx.temperature_offset == 9.0
    assert ctx.energy_multiplier == 1.35


def test_context_active_for_running_and_paused_sims():
    st = TwinState(seed=3)
    simeng.create_simulation(st, "crowd", "lib", {})
    simeng.start_simulation(st, st.active_sim.id)
    ctx_running = build_simulation_context(st)
    assert ctx_running.active is True
    simeng.pause_simulation(st, st.active_sim.id)
    ctx_paused = build_simulation_context(st)
    assert ctx_paused.active is True and ctx_paused.status == "PAUSED"
    # scenario fields remain readable even when inactive (e.g. status reporting)
    st.active_sim.status = "COMPLETED"
    ctx_done = build_simulation_context(st)
    assert ctx_done.active is False
    assert ctx_done.scenario == "crowd" and ctx_done.target_id == "lib"


def test_tick_sensors_updates_context_and_values():
    from app.services.optimization_service import compute_routes
    from app.services.risk_engine import compute_risk
    st = TwinState(seed=3)
    compute_routes(st)
    compute_risk(st)
    before = st.buildings["eng"].occupancy
    sensor_engine.tick_sensors(st, 1.0)
    assert st.sim_context is not None
    assert st.sim_context.active is False  # no scenario running
    st.buildings["eng"].occupancy = min(st.buildings["eng"].capacity, before + 50)
    target = st.buildings["eng"].occupancy
    sensor_engine.tick_sensors(st, 1.0)
    # occupancy moves smoothly toward the diurnal target, never above capacity
    assert st.buildings["eng"].occupancy <= max(target, st.buildings["eng"].capacity)
    assert all(s.updated_at == st.clock for s in st.sensors.values())
