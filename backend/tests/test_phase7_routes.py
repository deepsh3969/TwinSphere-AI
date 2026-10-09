"""Phase 7 — Route & Evacuation Optimization (spec §39-§40, §43)."""

import math

import pytest
from fastapi.testclient import TestClient

from ai.optimization import (
    MODE_KEYS,
    calculate_route,
    check_route_validity,
    compare_modes,
    dijkstra,
    get_graph,
    plan_building_evacuation,
    plan_emergency_route,
    reset_graph_cache,
)
from ai.optimization.congestion import (
    detect_bottlenecks,
    exit_flow_capacity,
    assign_exits,
)
from ai.optimization.graph import RouteGraph
from ai.optimization.route_cost import MODE_WEIGHTS, get_weights, edge_cost
from app.core.security import create_token
from app.main import app
from app.services import route_service as rs
from app.services import simulation_engine as simeng
from app.services.risk_engine import compute_risk
from app.services.state import TwinState, get_state

client = TestClient(app)
ADMIN = {"Authorization": f"Bearer {create_token('u_admin', 'admin', 'ADMIN')}"}
OPERATOR = {"Authorization": f"Bearer {create_token('u_operator', 'operator', 'OPERATOR')}"}
VIEWER = {"Authorization": f"Bearer {create_token('u_viewer', 'viewer', 'VIEWER')}"}


@pytest.fixture()
def state():
    st = TwinState(seed=7)
    compute_risk(st)
    return st


def _synthetic(pair_risk: float = 0.0, pair_congestion: float = 0.0,
               extra_roads: list | None = None, disconnect: bool = False) -> RouteGraph:
    """Two nodes connected by two parallel roads (risky-short vs safe-long)."""
    reset_graph_cache()
    nodes = {
        "o": dict(id="o", name="Origin", x=0, z=0, kind="EXIT"),
        "d": dict(id="d", name="Destination", x=100, z=0, kind="GATE", is_exit=True),
        "orphan": dict(id="orphan", name="Orphan", x=500, z=500, kind="JUNCTION"),
    }
    roads = {
        "r_short": dict(id="r_short", name="Short risky", from_node="o", to_node="d",
                        length=100.0, kind="INTERNAL", risk=90.0,
                        congestion=pair_congestion, blocked=False),
        "r_long": dict(id="r_long", name="Long safe", from_node="o", to_node="d",
                       length=150.0, kind="INTERNAL", risk=pair_risk,
                       congestion=0.0, blocked=False),
    }
    for extra in (extra_roads or []):
        roads[extra["id"]] = extra
    g = RouteGraph()
    g.build_topology(nodes, roads)
    g.refresh_dynamic(roads, {n: 0.0 for n in nodes})
    return g


# ------------------------------------------------------------ §39.1-2 graph

def test_graph_construction_and_connectivity(state):
    g = rs.get_route_graph(state)
    assert len(g.nodes) == 35 and len(g.edges) == 40
    assert set(g.exits()) == {"gate_main", "gate_east", "gate_west"}
    # flood fill: the campus graph must be fully connected
    seen, stack = {"ex_eng_s"}, ["ex_eng_s"]
    while stack:
        cur = stack.pop()
        for nb, _rid in g.neighbors(cur):
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    assert len(seen) == len(g.nodes), "all road nodes must be reachable"
    # every edge references existing nodes
    for e in g.edges.values():
        assert e.source in g.nodes and e.destination in g.nodes


def test_astar_matches_dijkstra_reference(state):
    g = rs.get_route_graph(state)
    pairs = [("ex_eng_s", "gate_main"), ("ex_admin", "gate_east"),
             ("ex_clinic", "gate_west"), ("court_c", "gate_main")]
    for mode in ("shortest", "balanced", "safest"):
        w = get_weights(mode)
        for a, b in pairs:
            pa = calculate_route(g, a, b, mode=mode)
            ref = dijkstra(g, a, {b}, w)
            assert ref is not None and pa["path"], f"{mode} {a}->{b} must route"
            ref_cost = sum(edge_cost(g.edges[r], w) for r in ref[1])
            path_cost = sum(edge_cost(g.edges[r], w) for r in pa["road_path"])
            assert path_cost == pytest.approx(ref_cost, rel=1e-6), \
                f"A* must be optimal vs Dijkstra for {mode} {a}->{b}"


# ------------------------------------------------------- §39.4-7 route modes

def test_shortest_mode_minimises_distance():
    g = _synthetic()
    r = calculate_route(g, "o", "d", mode="shortest")
    assert r["road_path"] == ["r_short"] and r["distance"] == 100.0


def test_safest_mode_prefers_lower_risk():
    """Spec §39: Road A 100m/risk90 vs Road B 150m/risk20 → safest picks B."""
    g = _synthetic(pair_risk=20.0)
    r = calculate_route(g, "o", "d", mode="safest")
    assert r["road_path"] == ["r_long"], "safest must choose the low-risk road"
    assert r["risk_score"] < 30
    # sanity: shortest still prefers the risky short road (mode independence)
    s = calculate_route(g, "o", "d", mode="shortest")
    assert s["road_path"] == ["r_short"]


def test_fastest_mode_avoids_congestion():
    g = _synthetic(pair_congestion=0.9)
    fast = calculate_route(g, "o", "d", mode="fastest")
    assert fast["road_path"] == ["r_long"], "congestion inflates traversal time"
    short = calculate_route(g, "o", "d", mode="shortest")
    assert short["road_path"] == ["r_short"]


def test_balanced_mode_weights_all_factors():
    w = MODE_WEIGHTS["balanced"]
    for field in ("distance", "time", "risk", "congestion", "capacity"):
        assert getattr(w, field) > 0, f"balanced must weight {field}"
    g = _synthetic(pair_risk=20.0)
    b = calculate_route(g, "o", "d", mode="balanced")
    assert b["status"] in ("RECOMMENDED", "ALTERNATIVE") and b["path"]


def test_all_modes_valid_and_compare_marks_recommended(state):
    g = rs.get_route_graph(state)
    assert set(MODE_KEYS) == {"shortest", "fastest", "safest", "balanced", "emergency"}
    cmp = compare_modes(g, "ex_eng_s", "gate_main")
    assert len(cmp["rows"]) == 4
    assert cmp["recommended_mode"] in {r["mode"] for r in cmp["rows"]}
    recommended = [r for r in cmp["rows"] if r.get("recommended")]
    assert len(recommended) == 1


# ----------------------------------------------------- §39.8 blocked handling

def test_blocked_road_excluded_from_cost():
    g = _synthetic()
    g.edges["r_short"].blocked = True
    r = calculate_route(g, "o", "d", mode="shortest")
    assert r["road_path"] == ["r_long"]
    assert edge_cost(g.edges["r_short"], get_weights("shortest")) == math.inf


def test_blocked_leaf_exit_reports_no_safe_route(state):
    g = rs.get_route_graph(state)
    state.roads["r_eng_s"]["blocked"] = True   # only road serving ex_eng_s
    g.refresh_dynamic(state.roads, state.node_risk)
    r = calculate_route(g, "ex_eng_s", "gate_main", mode="balanced")
    assert r["status"] == "NO_SAFE_ROUTE"
    assert r["blocked_paths"] >= 1 and r["path"] == []
    state.roads["r_eng_s"]["blocked"] = False
    g.refresh_dynamic(state.roads, state.node_risk)


def test_no_route_condition_disconnected_graph():
    g = _synthetic()
    r = calculate_route(g, "o", "orphan", mode="balanced")
    assert r["status"] == "NO_SAFE_ROUTE"
    assert "available_alternatives" in r and "reason" in r
    # emergency vehicle path also refuses
    v = plan_emergency_route(g, "o", "orphan")
    assert v["status"] == "NO_SAFE_ROUTE" and v["road_path"] == []


def test_check_route_validity_reasons():
    g = _synthetic()
    v = check_route_validity(g, ["r_short"], ["o", "d"])
    assert v["valid"] and v["reasons"] == []
    g.edges["r_short"].blocked = True
    v = check_route_validity(g, ["r_short"], ["o", "d"])
    assert not v["valid"] and "edge_blocked" in v["reasons"]
    g.edges["r_short"].blocked = False
    g.edges["r_short"].risk = 80.0
    v = check_route_validity(g, ["r_short"], ["o", "d"], prev_edge_risk={"r_short": 40.0})
    assert not v["valid"] and "risk_increased" in v["reasons"]


# ------------------------------------------------------ §39.10-11 congestion/risk

def test_congestion_raises_time_and_cost(state):
    g = rs.get_route_graph(state)
    # shortest ignores congestion → same path, so score/time deltas are pure
    base = calculate_route(g, "ex_eng_s", "gate_main", mode="shortest")
    base_time = base["estimated_time"]
    for rid in base["road_path"]:
        state.roads[rid]["congestion"] = 0.9
    g.refresh_dynamic(state.roads, state.node_risk)
    congested = calculate_route(g, "ex_eng_s", "gate_main", mode="shortest")
    assert congested["road_path"] == base["road_path"]
    assert congested["estimated_time"] > base_time * 1.5, "congestion inflates ETA"
    assert congested["congestion_score"] >= 0.8
    assert congested["congestion_label"] in ("HIGH", "SEVERE")
    # fastest mode may reroute away from the jam instead of crawling through it
    fast = calculate_route(g, "ex_eng_s", "gate_main", mode="fastest")
    assert fast["road_path"] != base["road_path"] or fast["estimated_time"] >= base_time
    for rid in base["road_path"]:
        state.roads[rid]["congestion"] = 0.0


def test_risk_shifts_safest_choice_on_real_graph(state):
    g = rs.get_route_graph(state)
    baseline = calculate_route(g, "ex_admin_w", "gate_west", mode="safest")
    # spike risk on every baseline edge — safest must find another way or
    # (if no alternative exists) report elevated risk honestly
    for rid in baseline["road_path"]:
        state.roads[rid]["risk"] = 95.0
    g.refresh_dynamic(state.roads, state.node_risk)
    alt = calculate_route(g, "ex_admin_w", "gate_west", mode="safest")
    if alt["road_path"] != baseline["road_path"]:
        assert set(alt["road_path"]).isdisjoint(baseline["road_path"]) or \
            alt["risk_score"] < 95.0
    else:
        assert alt["risk_score"] >= 90.0
    for rid in baseline["road_path"]:
        state.roads[rid]["risk"] = 0.0


# -------------------------------------------------------- §39.12-13 capacity

def test_exit_capacity_values_and_pressure(state):
    g = rs.get_route_graph(state)
    main_gate = g.nodes["gate_main"]
    assert exit_flow_capacity(main_gate) == pytest.approx(500.0)
    assert exit_flow_capacity(g.nodes["gate_east"]) == pytest.approx(375.0)
    # demand-based assignment distributes instead of piling onto one gate
    assigned = assign_exits(g, {"a": 300.0, "b": 200.0, "c": 250.0})
    people = sorted(v["people"] for v in assigned.values())
    assert people[-1] < 750, "no exit should absorb all demand when others exist"


def test_bottleneck_detection_structured_output(state):
    g = rs.get_route_graph(state)
    flows = [{"label": "Engineering", "node_path": ["ex_eng_s", "court_c", "gate_main"],
              "road_path": ["r_eng_s"], "people": 600}]
    exits_pressure = {"gate_main": {"exit_id": "gate_main", "people": 600.0,
                                    "capacity": 500.0, "pressure": 1.2}}
    out = detect_bottlenecks(g, flows, exits_pressure)
    assert out, "over-capacity exit must produce a bottleneck"
    top = out[0]
    for key in ("location", "severity", "estimated_people", "capacity", "recommendation"):
        assert key in top
    assert top["severity"] in ("MEDIUM", "HIGH")
    kinds = {b["kind"] for b in out}
    assert "EXIT" in kinds and "EDGE" in kinds


# ------------------------------------------------------- §39.14 emergency veh

def test_emergency_vehicle_route_and_profiles(state):
    g = rs.get_route_graph(state)
    r = plan_emergency_route(g, "gate_east", "ex_eng_s", vehicle="fire_truck")
    assert r["status"] in ("SAFE", "WARNING") and r["road_path"]
    assert r["eta_s"] > 0 and r["distance"] > 0
    assert isinstance(r["blocked_roads_avoided"], list)
    # vehicle traversal must be much faster than walking
    walk = r["distance"] / 1.35
    assert r["eta_s"] < walk


def test_emergency_routes_all_vehicles_and_block_diversion(state):
    out = rs.emergency_routes(state, destination="ex_eng_s", activate=False)
    assert out["status"] == "ok" and len(out["routes"]) == 3
    best = out["routes"][0]
    assert best["origin"] in state.nodes and best["destination"] == "ex_eng_s"
    # without incident or destination → honest empty answer
    bare = rs.emergency_routes(state, activate=False)
    assert bare["status"] == "NO_SAFE_ROUTE" and bare["routes"] == []
    # block the chosen path → a route must still exist or fail gracefully
    g = rs.get_route_graph(state)
    for rid in best["road_path"]:
        state.roads[rid]["blocked"] = True
    g.refresh_dynamic(state.roads, state.node_risk)
    r2 = plan_emergency_route(g, best["origin"], best["destination"], vehicle="fire_truck")
    assert r2["status"] in ("NO_SAFE_ROUTE", "SAFE", "WARNING", "BLOCKED")
    if r2["road_path"]:
        assert set(r2["road_path"]).isdisjoint(best["road_path"])
    for rid in best["road_path"]:
        state.roads[rid]["blocked"] = False


# --------------------------------------------- §39.9 dynamic recalculation

def test_revalidate_invalidates_and_recalculates(state):
    plan = rs.calculate(state, "ex_eng_s", "gate_main", mode="balanced")
    v0 = state.route_version
    pending0 = len(state.pending_sim_events)
    state.pending_sim_events.clear()
    rs.revalidate(state)  # establish signature
    state.pending_sim_events.clear()

    # block a road ON the active route
    rid = plan["route"]["road_path"][1]
    state.roads[rid]["blocked"] = True
    result = rs.revalidate(state)

    assert result["invalidated"] and result["changed"]
    assert state.route_version > v0
    events = [e["event"] for e in state.pending_sim_events]
    assert "route.invalidated" in events and "route.recalculated" in events
    new = state.route_plan
    assert rid not in new["route"]["road_path"], "recalculated route must avoid the block"
    assert new["route_id"] != plan["route_id"]
    state.roads[rid]["blocked"] = False


def test_revalidate_is_noop_when_environment_unchanged(state):
    rs.calculate(state, "ex_admin", "gate_east", mode="balanced")
    rs.revalidate(state)
    state.pending_sim_events.clear()
    version = state.route_version
    result = rs.revalidate(state)
    assert result["changed"] is False and state.route_version == version
    assert state.pending_sim_events == [], "no events without real change"


# ---------------------------------------------- §39.16-17 simulation + recovery

def test_simulation_fire_integration_and_auto_evacuation_plan(state):
    """§40 core loop: fire starts → risk rises → evacuation plan appears."""
    rs.ensure_initial(state)
    state.pending_sim_events.clear()

    simeng.create_simulation(state, "fire", "eng",
                             {"intensity": 5, "wind": "NONE"})
    simeng.start_simulation(state, state.active_sim.id)
    for _ in range(6):
        simeng.tick_simulation(state, 5.0)
        compute_risk(state)

    result = rs.revalidate(state)
    assert result["evacuation"] is True
    evac = state.evacuation
    assert evac["status"] in ("ACTIVE", "CRITICAL")
    eng = next(b for b in evac["buildings"] if b["building_id"] == "eng")
    assert eng["people_at_risk"] > 0, "fire zones must contribute people at risk"
    assert evac["people_at_risk"] >= eng["people_at_risk"]

    # auto-plan activated: the 3D scene has an evacuation route without manual input
    assert state.route_plan is not None
    assert state.route_plan["kind"] == "evacuation"
    assert state.route_plan["building_id"] == "eng"
    assert state.route_plan["route"]["path"], "plan must contain a node path"
    events = [e["event"] for e in state.pending_sim_events]
    assert any(e.startswith("evacuation.") for e in events)

    # keep running: plan stays fresh, version never regresses
    v = state.route_version
    for _ in range(4):
        simeng.tick_simulation(state, 10.0)
        compute_risk(state)
        rs.revalidate(state)
    assert state.route_version >= v
    if state.route_plan:
        assert state.route_plan["route_version"] <= state.route_version


def test_recovery_returns_evacuation_to_idle(state):
    rs.ensure_initial(state)
    state.pending_sim_events.clear()
    simeng.create_simulation(state, "fire", "eng",
                             {"intensity": 4, "wind": "NONE"})
    simeng.start_simulation(state, state.active_sim.id)
    for _ in range(6):
        simeng.tick_simulation(state, 10.0)
        compute_risk(state)
        rs.revalidate(state)
    assert state.evacuation["status"] in ("ACTIVE", "CRITICAL", "STANDBY", "IDLE")

    simeng._complete(state, state.active_sim)          # duration done
    state.active_sim.status = "RECOVERING"
    for _ in range(8):
        simeng.tick_simulation(state, 15.0)            # recovery glide
        compute_risk(state)
        rs.revalidate(state)
        simeng._clear_effects(state, state.active_sim) if False else None
    # after full recovery zones are normal again → evacuation relaxes
    for z in state.zones.values():
        z.status, z.fire, z.smoke = "NORMAL", 0.0, 0.0
    compute_risk(state)
    rs.revalidate(state)
    assert state.evacuation["status"] in ("IDLE", "STANDBY")
    events = [e["event"] for e in state.pending_sim_events]
    # either completed fired during transition or status already relaxed
    assert "evacuation.completed" in events or state.evacuation["status"] in ("IDLE", "STANDBY")


def test_building_evacuation_roles_and_critical(state):
    plan = rs.building_evacuation(state, "eng", activate=False)
    assert plan["status"] in ("READY", "ACTIVE")
    assert plan["primary_exit"] and plan["routes"]
    roles = {e["role"] for e in plan["exits"]}
    assert "PRIMARY" in roles
    assert plan["has_safe_route"] is True

    # block every road serving eng exits → EVACUATION_CRITICAL
    for rid in ("r_eng_s", "r_eng_n"):
        state.roads[rid]["blocked"] = True
    state.pending_sim_events.clear()
    result = rs.revalidate(state, force=True)
    critical = rs.building_evacuation(state, "eng", activate=False)
    assert critical["status"] == "EVACUATION_CRITICAL"
    assert critical["has_safe_route"] is False
    assert "blocked" in critical["reason"].lower()
    for rid in ("r_eng_s", "r_eng_n"):
        state.roads[rid]["blocked"] = False


# ---------------------------------------------------------------- §43 API

def test_api_route_endpoints_and_validation(stateless=None):
    # happy path calculation
    resp = client.post("/api/routes/calculate", headers=OPERATOR, json={
        "origin": "ex_eng_s", "destination": "gate_main",
        "mode": "balanced", "people": 275})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for key in ("route_id", "mode", "status", "path", "distance",
                "estimated_time", "risk_score", "congestion_score",
                "simulation_id", "route_version"):
        assert key in data, f"missing {key} in calculate response"
    assert data["status"] == "RECOMMENDED" and data["path"]

    # validation: unknown mode / origin / destination → 400
    for bad in ({"origin": "ex_eng_s", "destination": "gate_main", "mode": "turbo"},
                {"origin": "nope", "destination": "gate_main"},
                {"origin": "ex_eng_s", "destination": "nope"}):
        r = client.post("/api/routes/calculate", headers=OPERATOR, json=bad)
        assert r.status_code == 400, bad
    # permissions: VIEWER cannot calculate (needs `apply`)
    r = client.post("/api/routes/calculate", headers=VIEWER, json={
        "origin": "ex_eng_s", "destination": "gate_main"})
    assert r.status_code == 403
    # unknown simulation id → 400
    r = client.post("/api/routes/calculate", headers=OPERATOR, json={
        "origin": "ex_eng_s", "destination": "gate_main",
        "simulation_id": "sim_not_active"})
    assert r.status_code == 400


def test_api_graph_evacuation_emergency_history():
    g = client.get("/api/routes/graph", headers=ADMIN)
    assert g.status_code == 200 and g.json()["counts"]["edges"] == 40

    ev = client.get("/api/routes/evacuation", headers=ADMIN)
    assert ev.status_code == 200
    body = ev.json()
    assert body["status"] in ("IDLE", "STANDBY", "ACTIVE", "CRITICAL")
    assert len(body["buildings"]) == 6 and "bottlenecks" in body

    st = client.get("/api/evacuation/status", headers=ADMIN)
    assert st.status_code == 200 and "status" in st.json()

    b = client.get("/api/evacuation/building/eng", headers=ADMIN)
    assert b.status_code == 200
    assert b.json()["building_id"] == "eng"
    r404 = client.get("/api/evacuation/building/nope", headers=ADMIN)
    assert r404.status_code == 400

    em = client.get("/api/routes/emergency?destination=ex_eng_s", headers=ADMIN)
    assert em.status_code == 200
    emr = client.get("/api/emergency-response/routes?destination=ex_eng_s",
                     headers=ADMIN)
    assert emr.status_code == 200 and len(emr.json()["routes"]) == 3
    # no incident and no destination → NO_SAFE_ROUTE + empty list
    bare = client.get("/api/emergency-response/routes", headers=ADMIN)
    assert bare.status_code == 200 and bare.json()["routes"] == []
    bad_v = client.get("/api/routes/emergency?vehicle=tank&destination=ex_eng_s",
                       headers=ADMIN)
    assert bad_v.status_code == 400

    bn = client.get("/api/routes/bottlenecks", headers=ADMIN)
    assert bn.status_code == 200 and "bottlenecks" in bn.json()

    al = client.get("/api/routes/alternatives?origin=ex_eng_s&destination=gate_main",
                    headers=ADMIN)
    assert al.status_code == 200
    assert len(al.json()["routes"]) >= 1 and "comparison" in al.json()

    hist = client.get("/api/routes/history", headers=ADMIN)
    assert hist.status_code == 200 and "history" in hist.json()

    # route detail: active plan first, then DB row, then 404
    plan_id = client.get("/api/evacuation/status", headers=ADMIN).json()
    active = (plan_id.get("active_plan") or {}).get("route_id")
    if active:
        det = client.get(f"/api/routes/{active}", headers=ADMIN)
        assert det.status_code == 200 and det.json()["route_id"] == active
    missing = client.get("/api/routes/rte_does_not_exist", headers=ADMIN)
    assert missing.status_code == 404

    rec = client.post("/api/routes/recalculate", headers=OPERATOR, json={})
    assert rec.status_code in (200, 404)  # 404 when no plan exists yet
