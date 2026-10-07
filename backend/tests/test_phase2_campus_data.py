"""Phase 2 — campus data layer: floors, codes, filters, readings, endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_token
from app.main import app
from app.services.risk_engine import compute_risk
from app.services.seed import seed_stats
from app.services.state import get_state

client = TestClient(app)  # no lifespan: routes use lazy state + seeded test DB


def _headers(role: str = "ADMIN", username: str = "admin") -> dict:
    token = create_token(f"u_{username}", username, role)
    return {"Authorization": f"Bearer {token}"}


ADMIN = _headers()


def test_seed_statistics():
    stats = seed_stats()
    assert stats["buildings"] == 6
    assert stats["floors"] == 15          # 4+3+3+3+1+1
    assert stats["zones"] == 29
    assert stats["sensors"] == 44
    assert stats["users"] == 4
    assert stats["incidents"] >= 3
    assert stats["sensor_readings"] >= 12_000  # 24h @ 5-min for 44 sensors


def test_buildings_expose_codes_and_descriptions():
    rows = client.get("/api/buildings", headers=ADMIN).json()
    assert len(rows) == 6
    codes = {r["code"] for r in rows}
    assert codes == {"ADMIN-A", "ENG-B", "CS-C", "LIB-D", "CAN-E", "CLI-F"}
    assert all(r["description"] for r in rows)
    assert all("latitude" in r and "longitude" in r for r in rows)


def test_building_lookup_by_code_and_id():
    by_code = client.get("/api/buildings/ENG-B", headers=ADMIN)
    assert by_code.status_code == 200
    body = by_code.json()
    assert body["name"] == "Engineering Building"
    assert body["code"] == "ENG-B"

    by_id = client.get("/api/buildings/eng", headers=ADMIN)
    assert by_id.status_code == 200
    assert by_id.json()["id"] == "eng"

    missing = client.get("/api/buildings/NOT-A-BUILDING", headers=ADMIN)
    assert missing.status_code == 404


def test_building_filters():
    academic = client.get("/api/buildings", params={"type": "ACADEMIC"}, headers=ADMIN).json()
    assert len(academic) == 2
    library = client.get("/api/buildings", params={"type": "LIBRARY"}, headers=ADMIN).json()
    assert [b["code"] for b in library] == ["LIB-D"]
    operational = client.get("/api/buildings", params={"status": "OPERATIONAL"}, headers=ADMIN).json()
    assert len(operational) == 6


def test_floors_endpoints():
    floors = client.get("/api/buildings/ENG-B/floors", headers=ADMIN)
    assert floors.status_code == 200
    eng = floors.json()
    assert [f["id"] for f in eng] == ["ENG-B-F1", "ENG-B-F2", "ENG-B-F3", "ENG-B-F4"]
    assert eng[0]["is_evacuation_level"] is True
    assert eng[0]["zone_count"] >= 1

    all_floors = client.get("/api/floors", headers=ADMIN).json()
    assert len(all_floors) == 15
    by_building = client.get("/api/floors", params={"building_id": "LIB-D"}, headers=ADMIN).json()
    assert len(by_building) == 3

    detail = client.get("/api/floors/ENG-B-F1", headers=ADMIN)
    assert detail.status_code == 200
    body = detail.json()
    assert body["building"]["code"] == "ENG-B"
    assert len(body["zones"]) == body["zone_count"]
    assert all(z["floor_id"] == "ENG-B-F1" for z in body["zones"])

    missing = client.get("/api/floors/ENG-B-F99", headers=ADMIN)
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"].lower()


def test_zone_endpoints_and_filters():
    all_zones = client.get("/api/zones", headers=ADMIN).json()
    assert len(all_zones) == 29
    assert all("zone_type" in z and "risk_level" in z and "width" in z for z in all_zones)
    assert all(z["floor_id"] for z in all_zones)

    eng = client.get("/api/zones", params={"building_id": "ENG-B"}, headers=ADMIN).json()
    assert eng and all(z["building_id"] == "eng" for z in eng)

    ground = client.get("/api/zones", params={"floor_id": "ENG-B-F1"}, headers=ADMIN).json()
    assert ground and all(z["floor"] == 0 for z in ground)

    labs = client.get("/api/zones", params={"zone_type": "LAB"}, headers=ADMIN).json()
    assert len(labs) >= 3

    detail = client.get("/api/zones/eng_ground", headers=ADMIN)
    assert detail.status_code == 200
    body = detail.json()
    assert body["building"]["code"] == "ENG-B"
    assert "risk_detail" in body and "sensors" in body

    missing = client.get("/api/zones/zone_does_not_exist", headers=ADMIN)
    assert missing.status_code == 404


def test_sensors_codes_thresholds_and_filters():
    sensors = client.get("/api/sensors", headers=ADMIN).json()
    assert len(sensors) == 44
    assert all(s["sensor_code"] for s in sensors)
    assert all(s["status"] == "ONLINE" for s in sensors)
    building_sensors = [s for s in sensors if s["building_id"]]
    assert all(s["zone_id"] for s in building_sensors)

    by_code = client.get("/api/sensors/ENG-B-TEMP-01", headers=ADMIN)
    assert by_code.status_code == 200
    body = by_code.json()
    assert body["id"] == "temperature_eng"
    assert body["normal_min"] == 18.0 and body["normal_max"] == 30.0
    assert body["min_value"] == 10.0 and body["max_value"] == 60.0

    by_id = client.get("/api/sensors/temperature_eng", headers=ADMIN)
    assert by_id.status_code == 200

    zone_id = body["zone_id"]
    zoned = client.get("/api/sensors", params={"zone_id": zone_id}, headers=ADMIN).json()
    assert zoned and all(s["zone_id"] == zone_id for s in zoned)

    campus = client.get("/api/sensors", params={"building_id": "NONE"}, headers=ADMIN)
    assert campus.status_code == 404

    missing = client.get("/api/sensors/NOT-A-SENSOR", headers=ADMIN)
    assert missing.status_code == 404


def test_sensor_history_window_and_simulated_source():
    resp = client.get("/api/sensors/occupancy_eng/history", params={"limit": 10}, headers=ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_source"] == "SIMULATED"
    assert len(body["persisted"]) == 10
    point = body["persisted"][-1]
    assert point["source"] == "SIMULATED"
    assert point["quality"] == "GOOD"
    assert "timestamp" in point and "value" in point

    window = client.get(
        "/api/sensors/occupancy_eng/history",
        params={"start": "2000-01-01T00:00:00+00:00", "end": "2100-01-01T00:00:00+00:00",
                "limit": 500},
        headers=ADMIN,
    ).json()
    assert len(window["persisted"]) >= 200

    narrow = client.get(
        "/api/sensors/occupancy_eng/history",
        params={"start": "2100-01-01T00:00:00+00:00", "limit": 500},
        headers=ADMIN,
    ).json()
    assert narrow["persisted"] == []

    bad = client.get("/api/sensors/occupancy_eng/history",
                     params={"start": "not-a-date"}, headers=ADMIN)
    assert bad.status_code == 400


def test_predictions_endpoint():
    resp = client.get("/api/predictions", headers=ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert body["data_source"] == "SIMULATED"
    assert all("entity_type" in p and "prediction_time" in p for p in body["predictions"])


def test_risk_entity_lookup():
    compute_risk(get_state())
    campus = client.get("/api/risk/campus", headers=ADMIN)
    assert campus.status_code == 200
    assert 0 <= campus.json()["score"] <= 100

    building = client.get("/api/risk/eng", headers=ADMIN)
    assert building.status_code == 200
    assert building.json()["entity_id"] == "eng"

    missing = client.get("/api/risk/zzz-not-real", headers=ADMIN)
    assert missing.status_code == 404


def test_incident_create_and_lookup():
    created = client.post(
        "/api/incidents",
        json={"title": "Phase 2 test incident", "kind": "MANUAL", "building_id": "lib",
              "severity": "MEDIUM", "description": "created by pytest"},
        headers=ADMIN,
    )
    assert created.status_code == 200
    inc = created.json()
    assert inc["incident_code"].startswith("INC-")
    assert inc["location_type"] == "BUILDING"
    assert inc["location_id"] == "lib"

    fetched = client.get(f"/api/incidents/{inc['id']}", headers=ADMIN)
    assert fetched.status_code == 200
    assert fetched.json()["incident_code"] == inc["incident_code"]

    seeded = client.get("/api/incidents/inc_seed_1", headers=ADMIN)
    assert seeded.status_code == 200
    assert seeded.json()["incident_code"] == "INC-0001"

    missing = client.get("/api/incidents/inc_does_not_exist", headers=ADMIN)
    assert missing.status_code == 404


def test_alert_and_recommendation_aliases():
    alerts = client.get("/api/alerts", headers=ADMIN)
    assert alerts.status_code == 200
    for a in alerts.json():
        assert "severity" in a and "type" in a and "is_active" in a

    recs = client.get("/api/recommendations", headers=ADMIN)
    assert recs.status_code == 200
    for r in recs.json():
        assert "reason" in r and "recommendation_id" in r


def test_simulation_history_codes():
    body = client.get("/api/simulations", headers=ADMIN).json()
    seeded = [s for s in body["history"] if s["id"] == "sim_seed_fire"]
    assert seeded, "seeded simulation missing from history"
    sim = seeded[0]
    assert sim["simulation_code"] == "SIM-0001"
    assert sim["target_type"] == "BUILDING"
    assert sim["parameters"] == sim["params"]
    assert sim["results"] == sim["result"]


def test_campus_summary_and_data_source():
    body = client.get("/api/campus", headers=ADMIN).json()
    assert body["data_source"] == "SIMULATED"
    assert body["metadata"]["name"]
    summary = body["summary"]
    assert summary["buildings"] == 6
    assert summary["floors"] == 15
    assert summary["zones"] == 29
    assert summary["sensors"] == 44
    assert summary["gates"] >= 1
    assert 0 <= summary["risk_score"] <= 100
