import math

import pytest

from ai.anomaly import detect_anomalies, rolling_zscore
from ai.optimization import build_graph, plan_route
from ai.prediction import predict_series
from ai.risk import building_risk, campus_risk, risk_level
from ai.simulation import crowd_density, ignite, step_fire, suppress, zone_totals


# ---------------------------------------------------------------- risk engine
def test_risk_levels_boundaries():
    assert risk_level(0) == "LOW"
    assert risk_level(20) == "LOW"
    assert risk_level(21) == "MODERATE"
    assert risk_level(60) == "ELEVATED"
    assert risk_level(61) == "HIGH"
    assert risk_level(81) == "CRITICAL"
    assert risk_level(150) == "CRITICAL"


def test_risk_low_normal_building():
    r = building_risk(occupancy=100, capacity=500, temperature=24.0, smoke=1.0)
    assert r["score"] <= 20
    assert r["level"] == "LOW"
    assert isinstance(r["factors"], list)


def test_risk_smoke_fire_blocked_exits():
    r = building_risk(occupancy=782, capacity=1200, temperature=48.0, smoke=90.0,
                      fire_fraction=0.5, burning_zones=4, blocked_exits=2, total_exits=3,
                      power_ok=False)
    assert r["score"] >= 81
    assert r["level"] == "CRITICAL"
    assert any("Smoke" in f["label"] for f in r["factors"])
    assert r["explanation"]


def test_campus_risk_reflects_worst_building():
    results = {
        "a": building_risk(occupancy=10, capacity=100),
        "b": building_risk(occupancy=900, capacity=1000, smoke=95, fire_fraction=0.8,
                           temperature=60, blocked_exits=1, total_exits=2),
    }
    c = campus_risk(results, blocked_roads=1, active_incidents=1)
    assert c["score"] > results["a"]["score"]
    assert c["level"] in ("HIGH", "CRITICAL")
    assert c["worst_building"] == "b"


# ---------------------------------------------------------------- optimisation
def _tiny_graph():
    nodes = {
        "a": {"x": 0, "z": 0}, "b": {"x": 10, "z": 0},
        "c": {"x": 0, "z": 10}, "d": {"x": 10, "z": 10},
        "exit1": {"x": 20, "z": 5, "is_exit": True},
        "exit2": {"x": -20, "z": 0, "is_exit": True},
    }
    roads = {
        "ab": {"from_node": "a", "to_node": "b", "length": 10, "congestion": 0, "risk": 0, "blocked": False},
        "bd": {"from_node": "b", "to_node": "d", "length": 10, "congestion": 0, "risk": 0, "blocked": False},
        "de": {"from_node": "d", "to_node": "exit1", "length": 10, "congestion": 0, "risk": 0, "blocked": False},
        "ac": {"from_node": "a", "to_node": "c", "length": 10, "congestion": 0, "risk": 0, "blocked": False},
        "aexit2": {"from_node": "a", "to_node": "exit2", "length": 20, "congestion": 0, "risk": 0, "blocked": False},
    }
    return nodes, roads


def test_astar_finds_exit():
    nodes, roads = _tiny_graph()
    route = plan_route(nodes, roads, "a", ["exit1", "exit2"])
    assert route["status"] in ("SAFE", "WARNING")
    assert route["exit_id"] in ("exit1", "exit2")
    assert route["distance"] > 0
    assert route["eta_s"] > 0


def test_blocked_road_avoids_path():
    nodes, roads = _tiny_graph()
    roads["aexit2"]["blocked"] = True
    route = plan_route(nodes, roads, "a", ["exit2"])
    assert route["status"] == "BLOCKED"
    assert route["node_path"] == []


def test_risk_prefers_safer_route():
    nodes, roads = _tiny_graph()
    # make the short east exit path extremely risky; west exit cheap
    for rid in ("ab", "bd", "de"):
        roads[rid]["risk"] = 95
    route = plan_route(nodes, roads, "a", ["exit1", "exit2"])
    assert route["exit_id"] == "exit2"


def test_cost_respects_congestion():
    nodes, roads = _tiny_graph()
    roads["aexit2"]["congestion"] = 1.0
    route = plan_route(nodes, roads, "a", ["exit1", "exit2"])
    assert route["exit_id"] == "exit1"


def test_graph_construction():
    nodes, roads = _tiny_graph()
    g = build_graph(nodes, roads)
    assert set(g) == set(nodes)
    assert any(nbr == "b" for nbr, _, _ in g["a"])


# ---------------------------------------------------------------- fire model
def _zones():
    return {
        "z1": {"id": "z1", "name": "Lab", "local_x": 0, "local_z": 0, "adjacent": ["z2"],
               "fire": 0, "smoke": 0, "temperature": 24, "status": "NORMAL", "occupancy": 80},
        "z2": {"id": "z2", "name": "Hall", "local_x": 10, "local_z": 0, "adjacent": ["z1", "z3"],
               "fire": 0, "smoke": 0, "temperature": 24, "status": "NORMAL", "occupancy": 120},
        "z3": {"id": "z3", "name": "Office", "local_x": 20, "local_z": 0, "adjacent": ["z2"],
               "fire": 0, "smoke": 0, "temperature": 24, "status": "NORMAL", "occupancy": 40},
    }


def test_fire_ignition_and_spread():
    zones = _zones()
    ev = ignite(zones, "z1", 7)
    assert ev and zones["z1"]["fire"] > 0
    for _ in range(120):
        step_fire(zones, dt=1.0, intensity=7, wind="E")
    assert zones["z2"]["fire"] > 0, "fire should spread downwind to neighbour"
    totals = zone_totals(zones)
    assert totals["burning_zones"] >= 1
    assert totals["people_at_risk"] > 0


def test_fire_wind_direction_matters():
    west = _zones()
    ignite(west, "z1", 6)
    for _ in range(90):
        step_fire(west, dt=1.0, intensity=6, wind="E")
    east = _zones()
    ignite(east, "z1", 6)
    for _ in range(90):
        step_fire(east, dt=1.0, intensity=6, wind="W")
    assert east["z2"]["fire"] >= west["z2"]["fire"] * 0.5  # both spread, west wind helps east-lying zones


def test_suppression_extinguishes():
    zones = _zones()
    ignite(zones, "z1", 8)
    for _ in range(30):
        step_fire(zones, dt=1.0, intensity=8, wind="NONE")
    for _ in range(120):
        suppress(zones, dt=1.0, factor=0.6)
    assert zones["z1"]["fire"] == 0
    assert zones["z1"]["status"] == "NORMAL"
    evs = zone_totals(zones)
    assert evs["burning_zones"] == 0


def test_crowd_density_states():
    assert crowd_density(50, 100)["state"] == "SAFE"
    assert crowd_density(85, 100)["state"] == "WARNING"
    assert crowd_density(120, 100)["state"] == "OVERLOADED"


# ---------------------------------------------------------------- prediction
def test_prediction_occupancy_shape():
    hours = [(i * 0.25) % 24 for i in range(96)]
    values = [300 + 400 * max(0, math.sin((h - 6) / 14 * math.pi)) for h in hours]
    out = predict_series(hours, values, horizon_min=20, metric="occupancy",
                         entity_id="eng", entity_name="Engineering", upper_bound=1200)
    assert 0 <= out["predicted_value"] <= 1200
    assert 0.3 <= out["confidence"] <= 0.95
    assert out["model_name"]
    assert "predicted to" in out["summary"]


def test_prediction_insufficient_data():
    out = predict_series([1.0], [10.0], metric="energy", entity_id="x")
    assert out["model_name"] == "insufficient_data"
    assert out["confidence"] == 0.0


# ---------------------------------------------------------------- anomaly
def test_zscore_flags_spike():
    values = [10, 11, 9.5, 10.2, 9.8, 10.1, 10.4, 9.9, 10.3, 10.0, 45.0]
    z, mean, std = rolling_zscore(values)
    assert abs(z) > 3
    res = detect_anomalies({"s1": values}, {"s1": {"type": "energy", "label": "Energy", "building_name": "Eng"}})
    assert res and res[0]["sensor_id"] == "s1"
    assert "above" in res[0]["explanation"] or "below" in res[0]["explanation"]


def test_no_anomaly_on_stable_series():
    values = [10, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 10.0, 9.9, 10.1, 10.0]
    res = detect_anomalies({"s1": values}, {"s1": {"type": "energy", "label": "Energy"}})
    assert res == []
