"""Phase 9 §60–§61 — analytics, history and replay determinism tests."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import create_token
from app.main import app
from app.services import analytics_service as an
from app.services import history_service as hs
from app.services import replay_service as rs
from app.services.state import get_state

client = TestClient(app)
ADMIN = {"Authorization": f"Bearer {create_token('u_admin', 'admin', 'ADMIN')}"}


def _viewer() -> dict:
    return {"Authorization": f"Bearer {create_token('u_viewer', 'viewer', 'VIEWER')}"}


# ------------------------------------------------------------ §60.1 windows

def test_window_presets_and_buckets():
    for key, minutes, bucket in [("15M", 15, 60), ("1H", 60, 60), ("6H", 360, 300),
                                 ("24H", 1440, 900), ("7D", 10080, 7200),
                                 ("30D", 43200, 28800)]:
        w = an.resolve_window(key, None, None)
        assert w.preset == key and w.bucket_s == bucket
        assert abs(w.span_s - minutes * 60) < 120
        assert len(w.buckets()) <= an.MAX_POINTS + 2
        assert w.as_dict()["from"] < w.as_dict()["to"]


def test_window_custom_and_fallback():
    w = an.resolve_window("CUSTOM", "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z")
    assert w.preset == "CUSTOM" and w.custom is True
    # start > end falls back to a 24h window ending at `end`
    w2 = an.resolve_window("CUSTOM", "2026-01-03T00:00:00Z", "2026-01-01T00:00:00Z")
    assert w2.span_s <= 24 * 3600 + 60
    # oversized custom windows clamp to MAX_CUSTOM_DAYS
    w3 = an.resolve_window("CUSTOM", "2020-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    assert w3.span_s <= (an.MAX_CUSTOM_DAYS + 1) * 86400
    # unknown preset falls back to 24H
    w4 = an.resolve_window("BOGUS", None, None)
    assert w4.preset == "24H"
    # bucket step keeps point count bounded
    assert len(w3.buckets()) <= an.MAX_POINTS + 2


# ---------------------------------------------------------- §60.2 overview

def test_overview_kpis_shape():
    with SessionLocal() as db:
        out = an.overview(db, get_state(), an.resolve_window("24H", None, None))
    ids = [k["id"] for k in out["kpis"]]
    assert {"occupancy", "energy", "risk", "incidents", "predictions", "sensors"} <= set(ids)
    for kpi in out["kpis"]:
        assert kpi["status"] in ("GOOD", "WARN", "CRITICAL", "LOW", "UNKNOWN")
        assert kpi["trend"]["direction"] in ("up", "down", "flat")
        assert "label" in kpi and "unit" in kpi
    assert out["counts"]["sensors_total"] == len(get_state().sensors)
    assert out["window"]["preset"] == "24H"
    assert out["source"] and out["computed_at"]
    assert isinstance(out["confidence"]["available"], bool)


def test_overview_risk_status_bands():
    with SessionLocal() as db:
        out = an.overview(db, get_state(), an.resolve_window("24H", None, None))
    risk = next(k for k in out["kpis"] if k["id"] == "risk")
    assert risk["secondary"] in an.RISK_BANDS
    assert risk["status"] == an.RISK_KPI_STATUS.get(risk["secondary"])


# -------------------------------------------------------------- §60.3 risk

def test_risk_analytics_shape():
    with SessionLocal() as db:
        out = an.risk_analytics(db, get_state(), an.resolve_window("7D", None, None))
    assert out["entity"] == "campus" and out["available"] is True
    assert 0 <= out["current"] <= 100
    assert out["stats"]["samples"] >= 1
    assert [c["category"] for c in out["time_in_category"]] == list(an.RISK_BANDS)
    total_pct = sum(c["pct"] for c in out["time_in_category"])
    assert 0 <= total_pct <= 100.1
    assert isinstance(out["critical_events"], list)
    assert len(out["heatmap"]["rows"]) >= 1
    # endpoint accepts building_id scope and echoes the resolved entity
    r = client.get("/api/analytics/risk?building_id=eng&range=6H", headers=ADMIN)
    assert r.status_code == 200 and r.json()["entity"] == "eng"


def test_risk_empty_window_is_honest():
    with SessionLocal() as db:
        out = an.risk_analytics(db, get_state(),
                                an.resolve_window("CUSTOM", "2020-01-01T00:00:00Z",
                                                  "2020-01-02T00:00:00Z"))
    assert out["available"] is False
    assert "no persisted risk scores" in out["reason"]
    assert out["series"] == []


# --------------------------------------------------------- §60.4 occupancy

def test_occupancy_analytics_shape():
    with SessionLocal() as db:
        out = an.occupancy_analytics(db, get_state(), an.resolve_window("24H", None, None))
    assert out["available"] is True
    assert len(out["by_building"]) == len(get_state().buildings)
    b = out["by_building"][0]
    assert {"id", "name", "current", "capacity", "pct", "avg"} <= set(b)
    assert "peak" in out["stats"] and "peak_at" in out["stats"]
    assert out["trend"]["direction"] in ("up", "down", "flat")
    assert out["current"] is not None and out["capacity"] is not None


# ----------------------------------------------------------- §60.5 energy

def test_energy_analytics_shape():
    with SessionLocal() as db:
        out = an.energy_analytics(db, get_state(), an.resolve_window("6H", None, None))
    assert out["available"] is True
    assert out["stats"]["samples"] > 0
    assert out["abnormal"]["count"] >= 0
    assert isinstance(out["anomalies_live"], list)
    assert len(out["by_building"]) == len(get_state().buildings)
    assert all(isinstance(p["value"], (int, float)) for p in out["series"])


# ------------------------------------------------------- §60.6 environment

def test_environment_metrics():
    with SessionLocal() as db:
        out = an.environment_analytics(db, get_state(), an.resolve_window("1H", None, None))
    assert [m["metric"] for m in out["metrics"]] == list(an.ENV_METRICS)
    for m in out["metrics"]:
        assert m["unit"] and "stats" in m and "series" in m
        assert m["abnormal_readings"] >= 0
        assert isinstance(m["available"], bool)
    assert out["live_temperature"] > 0


# ------------------------------------------------------ §60.7 sensor health

def test_sensor_health_totals():
    state = get_state()
    with SessionLocal() as db:
        out = an.sensor_health(db, state, an.resolve_window("24H", None, None))
    assert out["totals"]["total"] == len(state.sensors)
    assert out["totals"]["online"] + out["totals"]["offline"] == out["totals"]["total"]
    assert out["status"] in ("HEALTHY", "DEGRADED", "UNHEALTHY")
    assert len(out["by_type"]) >= 9
    assert isinstance(out["diagnostics"], list)
    for d in out["diagnostics"]:
        assert d["issues"] and d["sensor_id"]


def test_sensor_detail_endpoint():
    r = client.get("/api/analytics/sensors/temperature_eng?range=6H", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["sensor"]["id"] == "temperature_eng"
    assert "series" in body and "stats" in body and "window" in body
    missing = client.get("/api/analytics/sensors/does_not_exist", headers=ADMIN)
    assert missing.status_code == 404


# ---------------------------------------------------------- §60.8 buildings

def test_buildings_analytics():
    with SessionLocal() as db:
        out = an.buildings_analytics(db, get_state(), an.resolve_window("24H", None, None))
    assert out["count"] == len(get_state().buildings)
    for b in out["buildings"]:
        assert {"id", "name", "risk", "occupancy", "energy", "incidents",
                "sensor_health"} <= set(b)
        assert 0 <= b["occupancy_pct"] <= 100 or b["occupancy"] > b["capacity"]


def test_building_detail_and_404():
    r = client.get("/api/analytics/buildings/eng?range=24H", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    for key in ("building", "risk", "occupancy", "environment", "incidents", "sensors"):
        assert key in body
    assert client.get("/api/analytics/buildings/nope", headers=ADMIN).status_code == 404


def test_buildings_compare():
    ids = ",".join(list(get_state().buildings)[:3])
    r = client.get(f"/api/analytics/buildings/compare?ids={ids}&range=24H", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert len(body["rows"]) >= 5
    for row in body["rows"]:
        for cell in row["values"].values():
            assert cell["raw"] is None or 0 <= cell["norm"] <= 100
    one = client.get("/api/analytics/buildings/compare?ids=eng", headers=ADMIN)
    assert one.json()["available"] is False


# --------------------------------------------------- §60.9 routes / AI

def test_routes_analytics_shape():
    with SessionLocal() as db:
        out = an.routes_analytics(db, get_state(), an.resolve_window("24H", None, None))
    assert {"events", "recalculations", "by_event", "by_mode",
            "avg_distance"} <= set(out["stats"])
    assert {"active_routes", "route_version", "mode"} <= set(out["current"])
    assert isinstance(out["series"], list)


def test_ai_analytics_shape():
    with SessionLocal() as db:
        out = an.ai_analytics(db, get_state(), an.resolve_window("7D", None, None))
    assert {"analyses", "recommendations", "avg_confidence",
            "acceptance_rate"} <= set(out["stats"])
    assert {"analyst", "ai", "anomalies"} <= set(out["engine"])
    assert isinstance(out["series"], list)
    rate = out["stats"]["acceptance_rate"]
    assert rate is None or 0 <= rate <= 100


# ---------------------------------------------------- §60.10 system / health

def test_system_status_components():
    with SessionLocal() as db:
        out = an.system_status(db, get_state())
    ids = [c["id"] for c in out["components"]]
    assert {"api", "database", "websocket", "simulation", "ai", "risk", "routes",
            "sensors", "occupancy"} <= set(ids)
    for c in out["components"]:
        assert c["status"] in ("ONLINE", "DEGRADED", "OFFLINE")
        assert c["message"]
    s = out["summary"]
    assert s["online"] + s["degraded"] + s["offline"] == s["total"]


def test_campus_health_score():
    with SessionLocal() as db:
        out = an.campus_health(db, get_state(), an.resolve_window("24H", None, None))
    assert 0 <= out["score"] <= 100
    assert out["level"] in ("GOOD", "FAIR", "POOR")
    assert out["weights_total"] == 100
    assert len(out["components"]) >= 6
    for c in out["components"]:
        assert 0 <= c["score"] <= 100 and c["weight"] > 0


# ---------------------------------------------------- §60.11 what changed

def test_what_changed_rows():
    with SessionLocal() as db:
        out = an.what_changed(db, get_state(), 60)
    assert out["ago_minutes"] == 60
    assert len(out["rows"]) >= 6
    for row in out["rows"]:
        assert {"metric", "label", "unit", "previous", "current",
                "direction", "impact"} <= set(row)
    s = out["summary"]
    assert s["improved"] + s["worsened"] + s["unchanged"] <= len(out["rows"])
    # ago=0 is clamped to 1 minute instead of failing
    clamped = an.what_changed(db, get_state(), 0)
    assert clamped["ago_minutes"] == 1
    r = client.get("/api/analytics/what-changed?ago=0", headers=ADMIN)
    assert r.status_code == 200


# -------------------------------------------------- §60.12 prediction accuracy

def test_prediction_accuracy_honesty():
    with SessionLocal() as db:
        out = an.prediction_accuracy(db, an.resolve_window("24H", None, None))
    assert isinstance(out["available"], bool)
    assert out["samples"] >= 0
    if out["available"]:
        assert 0 <= out["accuracy"] <= 100
        assert "method" in out and "source" in out
    else:
        assert out["reason"]


# -------------------------------------------------------------- §60.13 CSV

def test_export_csv_kinds():
    with SessionLocal() as db:
        state = get_state()
        window = an.resolve_window("30D", None, None)
        for kind in an.EXPORT_KINDS:
            filename, media_type, body = an.export_dataset(db, state, kind, window)
            assert media_type == "text/csv" and filename.endswith(".csv")
            header = body.splitlines()[0]
            assert "," in header and len(body.splitlines()) >= 1
    bad = client.get("/api/analytics/export?kind=definitely_not", headers=ADMIN)
    assert bad.status_code == 400


# ------------------------------------------------- §60.14 incidents history

def test_phase9_indexes_created():
    from sqlalchemy import inspect

    from app.core.database import engine

    insp = inspect(engine)
    want = {"incidents": {"ix_incidents_severity", "ix_incidents_kind"},
            "simulation_events": {"ix_simulation_events_sim_t"},
            "risk_scores": {"ix_risk_scores_entity_time"},
            "route_events": {"ix_route_events_sim_time"},
            "occupancy_records": {"ix_occupancy_records_building_time"}}
    for table, names in want.items():
        have = {i["name"] for i in insp.get_indexes(table)}
        assert names <= have, (table, sorted(names - have))


def test_incidents_list_pagination_and_filters():
    r = client.get("/api/history/incidents?page=1&page_size=2", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 3 and body["page"] == 1 and body["pages"] >= 2
    assert len(body["items"]) == 2
    med = client.get("/api/history/incidents?severity=MEDIUM", headers=ADMIN).json()
    assert med["items"] and all(i["severity"] == "MEDIUM" for i in med["items"])
    search = client.get("/api/history/incidents?q=leak", headers=ADMIN).json()
    assert search["items"] and "leak" in search["items"][0]["title"].lower()
    asc = client.get("/api/history/incidents?sort=started_at&order=asc",
                     headers=ADMIN).json()
    starts = [i["started_at"] for i in asc["items"]]
    assert starts == sorted(starts)


def test_incident_detail_report_export():
    det = client.get("/api/history/incidents/inc_seed_1", headers=ADMIN)
    assert det.status_code == 200
    body = det.json()
    assert body["incident"]["code"] == "INC-0001"
    assert isinstance(body["timeline"], list) and body["metrics"]
    rep = client.get("/api/history/incidents/inc_seed_1/report", headers=ADMIN)
    assert rep.status_code == 200
    report = rep.json()
    assert report["report_type"] == "INCIDENT_REPORT"
    assert report["executive_summary"]
    assert isinstance(report["contributing_factors"], list)
    csv_out = client.get("/api/history/incidents/inc_seed_1/export?format=csv",
                         headers=ADMIN)
    assert csv_out.status_code == 200
    assert csv_out.text.splitlines()[0].startswith("category,kind,time")
    assert client.get("/api/history/incidents/nope").status_code in (401, 404)
    assert client.get("/api/history/incidents/nope", headers=ADMIN).status_code == 404


# ---------------------------------------------- §60.15 simulations history

def test_simulations_list_detail_events():
    r = client.get("/api/history/simulations?page_size=10", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 4
    item = body["items"][0]
    assert {"id", "code", "scenario", "status", "events"} <= set(item)
    det = client.get("/api/history/simulations/sim_seed_fire", headers=ADMIN).json()
    assert det["simulation"]["scenario"] == "fire"
    assert "events_by_category" in det["metrics"]
    ev = client.get("/api/history/simulations/sim_seed_fire/events", headers=ADMIN).json()
    assert ev["count"] == len(ev["events"]) == 4
    ts = [e["t"] for e in ev["events"]]
    assert ts == sorted(ts)
    assert {e["category"] for e in ev["events"]} <= set(hs.KIND_CATEGORY.values()) | {"SIMULATION"}
    assert client.get("/api/history/simulations/nope",
                      headers=ADMIN).status_code == 404


def test_simulations_compare_endpoint():
    r = client.get("/api/history/simulations/compare?a=sim_seed_fire&b=sim_seed_crowd",
                   headers=ADMIN)
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) >= 10
    metrics = {row["metric"] for row in rows}
    assert {"peak_risk", "people_affected", "recovery_time_s", "events"} <= metrics
    missing = client.get("/api/history/simulations/compare?a=sim_seed_fire&b=nope",
                         headers=ADMIN)
    assert missing.status_code == 404


# ------------------------------------------------------------- §60.16 RBAC

def test_rbac_requires_read_token():
    endpoints = [
        "/api/analytics/overview", "/api/analytics/risk", "/api/analytics/health",
        "/api/analytics/system", "/api/analytics/what-changed", "/api/analytics/sensors",
        "/api/analytics/buildings", "/api/analytics/routes", "/api/analytics/ai",
        "/api/history/incidents", "/api/history/simulations",
        "/api/history/simulations/sim_seed_fire/replay",
    ]
    for url in endpoints:
        assert client.get(url).status_code == 401, url
        assert client.get(url, headers=_viewer()).status_code == 200, url


# ------------------------------------------------------ §60.17 legacy compat

def test_legacy_timeseries_untouched():
    r = client.get("/api/analytics/timeseries?range=24H", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert len(body["occupancy"]) > 50
    assert body["source"].startswith("simulated telemetry")


# ============================================================ §61 replay

REPLAY_ID = "sim_seed_fire"


def test_replay_deterministic():
    with SessionLocal() as db:
        a = rs.build_replay(db, REPLAY_ID)
        b = rs.build_replay(db, REPLAY_ID)
    assert a is not None and b is not None
    a.pop("built_at"), b.pop("built_at")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_replay_frames_monotonic_and_complete():
    with SessionLocal() as db:
        out = rs.build_replay(db, REPLAY_ID)
    frames = out["frames"]
    assert frames and out["duration_s"] == 240.0
    assert frames[0]["t"] == 0.0
    assert frames[-1]["t"] == pytest.approx(out["duration_s"])
    ts = [f["t"] for f in frames]
    assert ts == sorted(ts)
    assert len(ts) == len(set(ts))
    assert len(frames) <= rs.MAX_FRAMES
    for f in frames:
        assert f["status"] in set(rs.LIFECYCLE_STATUS.values()) | {"CREATED"}
        assert 0 <= f["t"] <= out["duration_s"]
    # final frame reflects the last persisted lifecycle event, not the row status
    last_lifecycle = next((e for e in reversed(out["events"])
                           if e["kind"] in rs.LIFECYCLE_STATUS), None)
    assert last_lifecycle is not None
    assert frames[-1]["status"] == rs.LIFECYCLE_STATUS[last_lifecycle["kind"]]


def test_replay_events_ordered_and_categorized():
    with SessionLocal() as db:
        out = rs.build_replay(db, REPLAY_ID)
        ev = hs.simulation_events(db, REPLAY_ID)
    ts = [e["t"] for e in out["events"]]
    assert ts == sorted(ts)
    assert len(out["events"]) == ev["count"]
    assert [e["kind"] for e in out["events"]] == [e["kind"] for e in ev["events"]]
    allowed = set(hs.KIND_CATEGORY.values()) | {"SIMULATION"}
    assert {e["category"] for e in out["events"]} <= allowed
    assert out["categories"] == sorted({e["category"] for e in out["events"]})
    assert out["speeds"] == [0.5, 1.0, 2.0, 5.0, 10.0]


def test_replay_frame_seek_and_step_override():
    with SessionLocal() as db:
        near = rs.replay_frame(db, REPLAY_ID, 100)
        tail = rs.replay_frame(db, REPLAY_ID, 10_000)
        stepped = rs.build_replay(db, REPLAY_ID, frame_step=30.0)
    assert near["t"] >= 100
    assert tail["t"] == pytest.approx(240.0)
    assert stepped["frame_step_s"] == 30.0
    step_ts = [f["t"] for f in stepped["frames"]]
    assert step_ts[1] - step_ts[0] == pytest.approx(30.0, abs=0.01)


def test_replay_payload_names_persisted_sources():
    with SessionLocal() as db:
        out = rs.build_replay(db, REPLAY_ID)
    assert "simulation_events" in out["source"] and "risk_scores" in out["source"]
    entities = {r["entity"] for r in out["risk_series"]}
    allowed = {"campus", *get_state().buildings.keys()}
    assert entities <= allowed
    # risk values are interpolated persisted scores (0-100), not synthetic curves
    assert all(0 <= r["score"] <= 100 for r in out["risk_series"])
    assert out["notes"]["risk"].startswith("interpolated from persisted")


def test_replay_endpoints_and_404():
    r = client.get(f"/api/history/simulations/{REPLAY_ID}/replay", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert {"simulation", "duration_s", "frames", "events", "speeds",
            "zone_buildings", "source"} <= set(body)
    fr = client.get(f"/api/history/simulations/{REPLAY_ID}/frame?t=100",
                    headers=ADMIN)
    assert fr.status_code == 200 and fr.json()["t"] >= 100
    assert client.get("/api/history/simulations/nope/replay",
                      headers=ADMIN).status_code == 404


def test_history_export_endpoint():
    r = client.get("/api/history/export?kind=simulations&range=30D", headers=ADMIN)
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("id,code,scenario")
    bad = client.get("/api/history/export?kind=wat", headers=ADMIN)
    assert bad.status_code == 400
