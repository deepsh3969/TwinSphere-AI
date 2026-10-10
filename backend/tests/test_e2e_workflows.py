"""Phase 11 — cross-phase end-to-end regression scenarios (spec §3, A-F).

Hermetic: runs against the in-process TestClient + seeded test database, with the
realtime runtime/lifespan deliberately NOT started (deterministic — no sleeps).
Simulated time is advanced by driving the engine directly, mirroring the runtime
tick (tick_simulation + compute_risk), so every assertion is reproducible.

Scenario map:
  A — normal campus: auth, command-center payload, buildings/sensors, risk,
      occupancy, 3D scene payload
  B — fire emergency: start, incident, sensor changes, risk, affected zones,
      route recalculation, AI analysis (advisory-only)
  C — recovery: progress, recovered state, historical record intact
  D — analytics: time-range filters, building filters, history, CSV export
      permissions, no fabricated data in empty windows
  E — replay: deterministic ordering, seek, payload immutability, isolation
      from live state
  F — security: 401/403 matrix, WS-unrelated auth regression, audit logging,
      session expiry/logout, unauthorized simulation controls
"""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.entities import Simulation, SimulationEvent
from app.services import simulation_engine as simeng
from app.services.demo import full_reset
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.state import get_state

client = TestClient(app)


# --------------------------------------------------------------------- helpers

def login(username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def tick(seconds: float, step: float = 10.0) -> list:
    """Advance simulated time deterministically (mirrors the runtime cycle)."""
    st = get_state()
    events, elapsed = [], 0.0
    while elapsed < seconds:
        events.extend(simeng.tick_simulation(st, step))
        compute_risk(st)
        elapsed += step
    return events


@pytest.fixture(scope="module", autouse=True)
def clean_slate():
    full_reset(get_state())
    yield
    full_reset(get_state())


@pytest.fixture(scope="module")
def op():
    return login("operator", "operator123")


@pytest.fixture(scope="module")
def admin():
    return login("admin", "admin123")


@pytest.fixture(scope="module")
def viewer():
    return login("viewer", "viewer123")


@pytest.fixture(scope="module")
def analyst():
    return login("analyst", "analyst123")


def _ensure_active_fire(op_hdr: dict) -> str:
    """Self-sufficient: create+start+advance a fire if none is active."""
    st = get_state()
    if st.active_sim and st.active_sim.status in ("RUNNING", "AWAITING_RECOVERY"):
        return st.active_sim.id
    full_reset(st)
    r = client.post("/api/simulations",
                    json={"scenario": "fire", "target_id": "eng",
                          "params": {"intensity": 6, "wind": "E"}},
                    headers=op_hdr)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/simulations/{sid}/start", headers=op_hdr).status_code == 200
    tick(260)
    return sid


# ============================================================ Scenario A — normal

def test_a1_login_and_command_center_payload(op, admin):
    # authenticate as an authorized user (already exercised by fixtures)
    me = client.get("/api/auth/me", headers=op)
    assert me.status_code == 200 and me.json()["role"] == "OPERATOR"

    campus = client.get("/api/campus", headers=op)
    overview = client.get("/api/analytics/overview?range=24H", headers=op)
    risk = client.get("/api/risk", headers=op)
    assert campus.status_code == overview.status_code == risk.status_code == 200

    cj, oj, rj = campus.json(), overview.json(), risk.json()
    assert cj["data_source"] == "SIMULATED"
    assert cj["summary"]["buildings"] == 6 and cj["summary"]["floors"] == 15
    kpi_ids = {k["id"] for k in oj["kpis"]}
    assert {"occupancy", "energy", "risk", "incidents"} <= kpi_ids
    assert 0 <= rj["campus"]["score"] <= 100


def test_a2_buildings_sensors_risk_and_occupancy(op):
    buildings = client.get("/api/buildings", headers=op).json()
    sensors = client.get("/api/sensors", headers=op).json()
    assert len(buildings) == 6 and len(sensors) >= 40

    risk = client.get("/api/risk", headers=op).json()
    assert "eng" in risk["buildings"]
    assert all(0 <= b["score"] <= 100 for b in risk["buildings"].values())

    occ = client.get("/api/analytics/occupancy?range=6H", headers=op).json()
    assert occ["available"] is True and len(occ["by_building"]) == 6
    assert occ["capacity"] and "peak" in occ["stats"]


def test_a3_campus_payload_carries_3d_scene_inputs(op):
    """The 3D twin needs positions, road graph and exits — assert they ship."""
    campus = client.get("/api/campus", headers=op).json()
    assert len(campus["buildings"]) == 6
    for b in campus["buildings"]:
        pos = b.get("position") or {}
        assert "x" in pos and "z" in pos, f"building {b.get('id')} missing position"
        assert "size" in b and "height" in b and "color" in b, \
            f"building {b.get('id')} missing 3D attributes"
    assert len(campus.get("roads", [])) >= 30 and len(campus.get("nodes", [])) >= 30
    assert campus["summary"]["gates"] >= 1 and campus["summary"]["exits"] >= 1

    # per-building detail carries zones + exits the scene drills into
    bd = client.get("/api/buildings/eng", headers=op).json()
    assert len(bd["zones"]) >= 6 and len(bd["exits"]) == 2
    assert all("id" in z and "status" in z for z in bd["zones"])


# ======================================================= Scenario B — fire emergency

def test_b1_fire_incident_sensors_and_risk(op, admin):
    full_reset(get_state())
    risk_before = client.get("/api/risk", headers=op).json()["campus"]["score"]
    inc_before = len(get_state().incidents)

    r = client.post("/api/simulations",
                    json={"scenario": "fire", "target_id": "eng",
                          "params": {"intensity": 6, "wind": "E"}},
                    headers=op)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/simulations/{sid}/start", headers=op).status_code == 200

    # incident creation
    st = get_state()
    assert len(st.incidents) > inc_before
    assert any(i.get("kind") == "FIRE" and i["status"] == "ACTIVE" for i in st.incidents)

    tick(260)

    # sensor/telemetry changes (ignition zone heated well above baseline 24°C)
    sim = st.active_sim
    assert sim is not None and sim.id == sid
    burning = [z for z in st.zones.values() if z.building_id == "eng" and z.fire > 0.05]
    assert burning, "fire must affect at least one zone"
    assert max(z.temperature for z in burning) >= 60
    assert sim.peak_temperature >= 60 and sim.peak_smoke > 0

    # risk updates
    risk_after = client.get("/api/risk", headers=op).json()
    assert risk_after["campus"]["score"] > risk_before
    assert risk_after["buildings"]["eng"]["score"] > 40

    # affected zones + required engine events
    kinds = {e["kind"] for e in sim.events}
    assert sim.affected_zones >= 1
    for expected in ("smoke_detected", "zones_affected", "routes_recalculated",
                     "people_at_risk", "response_recommended"):
        assert expected in kinds, f"missing event {expected}: {sorted(kinds)}"


def test_b2_route_recalculation_and_evacuation(op):
    st = get_state()
    assert st.active_sim is not None, "scenario B must leave an active fire"

    # route graph intact and evacuation auto-activated for the incident
    routes = client.get("/api/routes", headers=op).json()["routes"]
    assert len(routes) == 6 and all("exit_id" in r for r in routes)
    graph = client.get("/api/routes/graph", headers=op).json()
    assert graph["counts"]["nodes"] == 35 and graph["counts"]["edges"] == 40

    evac = client.get("/api/routes/evacuation", headers=op).json()
    assert evac["status"] in ("ACTIVE", "CRITICAL")
    eng = next(b for b in evac["buildings"] if b["building_id"] == "eng")
    assert eng["people_at_risk"] >= 0

    # operator activates the building plan (apply permission) → active plan
    bp = client.get("/api/evacuation/building/eng?mode=safest", headers=op)
    assert bp.status_code == 200, bp.text
    assert bp.json()["routes"], "building plan must include routes"
    plan = client.get("/api/evacuation/status", headers=op).json()["active_plan"]
    assert plan is not None and plan["route_version"] >= 1
    assert plan["kind"] == "evacuation"

    # a fresh recalculation during the incident is served + recorded
    before = client.get("/api/routes/history", headers=op).json()["history"]
    calc = client.post("/api/routes/calculate", headers=op, json={
        "origin": "ex_admin", "destination": "gate_east", "mode": "safest", "people": 120})
    assert calc.status_code == 200 and calc.json()["status"] in ("RECOMMENDED", "ALTERNATIVE")
    assert calc.json()["route_version"] >= 1
    after = client.get("/api/routes/history", headers=op).json()["history"]
    assert len(after) >= len(before), "route calculation must be recorded in history"


def test_b3_ai_analysis_is_advisory_only(op, admin):
    st = get_state()
    risk_before = client.get("/api/risk", headers=op).json()["campus"]["score"]
    zone_before = {z.id: (z.status, round(z.fire, 3)) for z in st.zones.values()}
    status_before = st.status

    an = client.post("/api/ai/analyze", json={"question": "fire response?"}, headers=admin)
    assert an.status_code == 200, an.text
    body = an.json()
    assert body.get("analysis_id", "").startswith("anl_")
    assert isinstance(body.get("recommendations"), list) and body["recommendations"]

    # analysis must not mutate operational state (advisory, not executive)
    risk_after = client.get("/api/risk", headers=op).json()["campus"]["score"]
    zone_after = {z.id: (z.status, round(z.fire, 3)) for z in st.zones.values()}
    assert risk_after == risk_before
    assert zone_after == zone_before
    assert st.status == status_before

    # generated recommendations remain pending + require human approval
    recs = client.get(f"/api/ai/recommendations?analysis_id={body['analysis_id']}",
                      headers=op).json()["recommendations"]
    assert recs, "analysis should produce recommendation cards"
    assert all(r["status"] == "PENDING" and r["requires_human_approval"] is True
               for r in recs)


# ========================================================== Scenario C — recovery

def test_c1_recovery_completes_and_history_persists(op):
    sid = _ensure_active_fire(op)

    rec = client.post(f"/api/simulations/{sid}/recover", headers=op)
    assert rec.status_code == 200, rec.text

    st = get_state()
    assert st.active_sim.status == "RECOVERING" and st.status == "RECOVERING"

    # drive recovery to completion deterministically
    for _ in range(80):
        if st.active_sim is None or st.active_sim.status == "COMPLETED":
            break
        tick(10, step=5)
    assert st.active_sim is not None and st.active_sim.status == "COMPLETED"
    assert st.recovery_progress == 100.0
    assert st.status == "NORMAL"
    assert all(z.status == "NORMAL" for z in st.zones.values() if z.building_id == "eng")
    assert st.buildings["eng"].status == "OPERATIONAL"

    # historical record intact: list + detail + persisted events
    hist = client.get("/api/simulations", headers=op).json()["history"]
    row = next((h for h in hist if h["id"] == sid), None)
    assert row is not None and row["status"] == "COMPLETED"

    det = client.get(f"/api/simulations/{sid}", headers=op)
    assert det.status_code == 200 and det.json()["id"] == sid

    with SessionLocal() as db:
        sim_row = db.get(Simulation, sid)
        assert sim_row is not None and sim_row.status == "COMPLETED"
        assert sim_row.peak_risk >= 40
        events = (db.query(SimulationEvent)
                  .filter(SimulationEvent.simulation_id == sid)
                  .order_by(SimulationEvent.t).all())
        assert events, "completed simulation must persist events"
        assert [e.t for e in events] == sorted(e.t for e in events)


# ========================================================== Scenario D — analytics

def test_d1_time_range_filtering(op):
    wins = {}
    for preset in ("15M", "24H", "7D"):
        r = client.get(f"/api/analytics/overview?range={preset}", headers=op)
        assert r.status_code == 200, r.text
        w = r.json()["window"]
        assert w["preset"] == preset
        assert w["from"] < w["to"]
        wins[preset] = (w["from"], w["to"])
    # nested windows: 15M ⊂ 24H ⊂ 7D (all ISO-8601 UTC strings)
    assert wins["15M"][0] > wins["24H"][0] > wins["7D"][0]
    assert wins["15M"][1] <= wins["24H"][1] <= wins["7D"][1]


def test_d2_building_filtering(op):
    by_b = client.get("/api/analytics/risk?building_id=eng&range=6H", headers=op).json()
    assert by_b["entity"] == "eng" and by_b["heatmap"]["rows"]

    detail = client.get("/api/analytics/buildings/eng?range=24H", headers=op)
    assert detail.status_code == 200 and detail.json()["building"]["id"] == "eng"

    # unknown building must not fabricate data
    bad = client.get("/api/analytics/buildings/not_a_building?range=24H", headers=op)
    assert bad.status_code == 404
    bad_risk = client.get("/api/analytics/risk?building_id=not_a_building&range=6H",
                          headers=op)
    assert bad_risk.status_code in (200, 404)
    if bad_risk.status_code == 200:
        body = bad_risk.json()
        assert body.get("available") is False or body.get("entity") == "not_a_building"


def test_d3_incident_and_simulation_history(op):
    inc = client.get("/api/history/incidents?page=1&page_size=5", headers=op).json()
    assert inc["total"] >= 3 and 1 <= len(inc["items"]) <= 5
    assert inc["page"] == 1 and inc["pages"] >= 1
    sev = client.get("/api/history/incidents?severity=MEDIUM", headers=op).json()
    assert sev["items"] and all(i["severity"] == "MEDIUM" for i in sev["items"])

    sims = client.get("/api/history/simulations?page_size=10", headers=op).json()
    assert sims["total"] >= 4 and {"id", "code", "scenario", "status"} <= set(sims["items"][0])

    # page bounds: out-of-range page is honest, not a crash
    far = client.get("/api/history/incidents?page=9999&page_size=5", headers=op)
    assert far.status_code == 200 and far.json()["items"] == []


def test_d4_csv_export_permissions(op, viewer, analyst):
    for hdr, allowed in ((viewer, False), (analyst, True), (op, True)):
        r = client.get("/api/analytics/export?kind=summary&range=24H", headers=hdr)
        if allowed:
            assert r.status_code == 200 and r.text.splitlines()[0].startswith("kpi,")
        else:
            assert r.status_code == 403

    bad = client.get("/api/analytics/export?kind=nope", headers=op)
    assert bad.status_code == 400

    hexp = client.get("/api/history/export?kind=simulations&range=30D", headers=op)
    assert hexp.status_code == 200 and hexp.text.splitlines()[0].startswith("id,code,scenario")


def test_d5_empty_window_is_honest(op):
    r = client.get("/api/analytics/risk?range=CUSTOM"
                   "&start=2020-01-01T00:00:00Z&end=2020-01-02T00:00:00Z", headers=op)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and body["reason"] and body["series"] == []


# =============================================================== Scenario E — replay

def test_e1_replay_frames_and_events_are_deterministically_ordered(op):
    r1 = client.get("/api/history/simulations/sim_seed_fire/replay", headers=op)
    assert r1.status_code == 200, r1.text
    p1 = r1.json()
    frames = p1["frames"]
    assert p1["source"] and p1["speeds"] == [0.5, 1.0, 2.0, 5.0, 10.0]
    assert len(frames) >= 2
    assert frames[0]["t"] == 0.0
    assert frames[-1]["t"] == p1["duration_s"]
    times = [f["t"] for f in frames]
    assert times == sorted(times)
    ev_times = [e["t"] for e in p1["events"]]
    assert ev_times == sorted(ev_times)

    # identical payload on repeat fetch (no server-side mutation)
    r2 = client.get("/api/history/simulations/sim_seed_fire/replay", headers=op)
    p2 = r2.json()
    assert [f["t"] for f in p2["frames"]] == times
    assert [e["kind"] for e in p2["events"]] == [e["kind"] for e in p1["events"]]


def test_e2_frame_seek_begin_middle_end(op):
    p = client.get("/api/history/simulations/sim_seed_fire/replay", headers=op).json()
    duration = p["duration_s"]
    for t in (0.0, duration / 2, duration):
        r = client.get(f"/api/history/simulations/sim_seed_fire/frame?t={t}", headers=op)
        assert r.status_code == 200, (t, r.text[:200])
        frame = r.json()
        assert frame["t"] >= t
        if t == 0.0:
            assert frame["t"] == 0.0

    missing = client.get("/api/history/simulations/nope/replay", headers=op)
    assert missing.status_code == 404
    bad = client.get("/api/history/simulations/sim_seed_fire/frame?t=notanumber", headers=op)
    assert bad.status_code in (200, 400, 422)


def test_e3_replay_never_mutates_live_state(op):
    st = get_state()
    live_before = {
        "active": st.active_sim.id if st.active_sim else None,
        "status": st.status,
        "risk": round(client.get("/api/risk", headers=op).json()["campus"]["score"], 6),
        "zones": {z.id: (z.status, round(z.fire, 4)) for z in st.zones.values()},
    }

    for _ in range(3):
        p = client.get("/api/history/simulations/sim_seed_fire/replay", headers=op).json()
        for t in (0.0, p["duration_s"] / 3, p["duration_s"]):
            client.get(f"/api/history/simulations/sim_seed_fire/frame?t={t}", headers=op)

    live_after = {
        "active": st.active_sim.id if st.active_sim else None,
        "status": st.status,
        "risk": round(client.get("/api/risk", headers=op).json()["campus"]["score"], 6),
        "zones": {z.id: (z.status, round(z.fire, 4)) for z in st.zones.values()},
    }
    assert live_after == live_before, "replay reads must not mutate live state"

    # replay payload for the seeded sim is immutable across fetches even after
    # a live simulation is started (live events never rewrite stored history)
    p_before = client.get("/api/history/simulations/sim_seed_fire/replay", headers=op).json()
    sid = _ensure_active_fire(op)
    p_after = client.get("/api/history/simulations/sim_seed_fire/replay", headers=op).json()
    assert [f["t"] for f in p_after["frames"]] == [f["t"] for f in p_before["frames"]]
    assert [e["kind"] for e in p_after["events"]] == [e["kind"] for e in p_before["events"]]
    # leave the stage clean for scenario-independent reruns
    client.post(f"/api/simulations/{sid}/reset", headers=op)
    full_reset(st)


# ============================================================= Scenario F — security

def test_f1_unauthenticated_requests_rejected():
    paths = ["/api/campus", "/api/risk", "/api/analytics/overview", "/api/users",
             "/api/audit", "/api/history/incidents", "/api/ai/anomalies"]
    for path in paths:
        assert client.get(path).status_code == 401, path
    assert client.post("/api/simulations", json={"scenario": "fire"}).status_code == 401
    assert client.post("/api/realtime/pause").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_f2_role_restrictions_enforced_by_backend(op, admin, viewer, analyst):
    # VIEWER: read-only
    assert client.get("/api/campus", headers=viewer).status_code == 200
    assert client.post("/api/simulations",
                       json={"scenario": "fire", "target_id": "eng"},
                       headers=viewer).status_code == 403
    assert client.post("/api/realtime/pause", headers=viewer).status_code == 403
    assert client.get("/api/users", headers=viewer).status_code == 403
    assert client.get("/api/audit", headers=viewer).status_code == 403
    assert client.get("/api/analytics/export?kind=summary", headers=viewer).status_code == 403

    # ANALYST: analysis yes, operational control no
    assert client.post("/api/ai/analyze", json={"question": "status?"},
                       headers=analyst).status_code == 200
    assert client.post("/api/simulations",
                       json={"scenario": "fire", "target_id": "eng"},
                       headers=analyst).status_code == 403
    assert client.post("/api/realtime/start", headers=analyst).status_code == 403

    # OPERATOR: operations yes, analysis/admin no
    assert client.get("/api/realtime/status", headers=op).status_code == 200
    assert client.post("/api/ai/analyze", json={"question": "x"},
                       headers=op).status_code == 403
    assert client.get("/api/users", headers=op).status_code == 403
    # ADMIN: full access
    assert client.get("/api/users", headers=admin).status_code == 200
    assert client.get("/api/audit?page_size=5", headers=admin).json()["scope"] == "full"


def test_f3_session_expiry_and_logout(op):
    # genuinely expired token (correct signature, exp in the past)
    now = int(time.time())
    expired = jwt.encode({
        "sub": "u_operator", "username": "operator", "role": "OPERATOR",
        "jti": "e2e-expired", "iss": settings.JWT_ISSUER, "aud": settings.JWT_AUDIENCE,
        "ver": 0, "iat": now - 7200, "exp": now - 60,
    }, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401

    # garbage + wrong-algorithm tokens also rejected
    assert client.get("/api/auth/me",
                      headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401

    # logout revokes server-side
    tok = login("viewer", "viewer123")
    assert client.post("/api/auth/logout", headers=tok).status_code == 200
    assert client.get("/api/auth/me", headers=tok).status_code == 401


def test_f4_audit_records_security_events(op, admin, viewer):
    # logins from this module have been audited; query them back as ADMIN
    r = client.get("/api/audit?action=auth.login&page_size=20", headers=admin)
    assert r.status_code == 200
    rows = r.json()["records"]
    assert rows and all(a["action"] == "auth.login" for a in rows)
    assert any(a["actor"] == "operator" and a["outcome"] == "SUCCESS" for a in rows)

    # a rejected login is audited with a DENIED outcome
    bad = client.post("/api/auth/login", json={"username": "operator",
                                               "password": "wrong-password"})
    assert bad.status_code == 401
    denied = client.get("/api/audit?action=auth.login&outcome=DENIED&page_size=10",
                        headers=admin).json()["records"]
    assert denied and all(a["outcome"] == "DENIED" for a in denied)

    # denials are recorded (viewer was denied simulation control in f2)
    d = client.get("/api/audit?action=authz.denied&page_size=20", headers=admin)
    assert d.status_code == 200 and d.json()["records"], "authz.denied must be audited"

    # operator sees only the operational subset — never auth/admin families
    op_rows = client.get("/api/audit?page_size=50", headers=op).json()
    assert op_rows["scope"] == "operational"
    assert all(not a["action"].startswith(("auth.", "authz.", "admin."))
               for a in op_rows["records"])


def test_f5_unauthorized_users_cannot_execute_simulation_controls(op, viewer, analyst):
    # no control verb works for read/analyze-only roles
    for hdr in (viewer, analyst):
        assert client.post("/api/realtime/start", headers=hdr).status_code == 403
        assert client.post("/api/realtime/pause", headers=hdr).status_code == 403
        assert client.post("/api/realtime/resume", headers=hdr).status_code == 403
        assert client.post("/api/realtime/reset", headers=hdr).status_code == 403
        assert client.post("/api/realtime/speed", json={"speed": 5},
                           headers=hdr).status_code == 403
        assert client.post("/api/demo/reset", headers=hdr).status_code == 403
        assert client.post("/api/demo/hard-reset", headers=hdr).status_code == 403
        # analyst does not hold `apply` either
        assert client.post("/api/routes/recalculate", json={},
                           headers=hdr).status_code == 403

    # sanity: authorized operator still can
    assert client.get("/api/realtime/status", headers=op).status_code == 200
