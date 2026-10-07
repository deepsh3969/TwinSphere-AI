"""Phase 5 — AI anomaly detection, prediction & risk intelligence.

Layered anomaly detection (cold start, persistence, decay, bands, filters),
prediction pipeline (chronological split, metrics, model versioning,
persistence, baseline fallback), deterministic risk (weights, hierarchy,
stability/hysteresis), AI scheduler (cycle, degraded mode, events) and the
Phase 5 REST surface (filters, detail lookups, published risk).
"""

import statistics

import pytest
from fastapi.testclient import TestClient

from ai.anomaly import (
    AnomalyTracker, detect, detect_anomalies, filtered, score_band,
)
from ai.anomaly.feature_engineering import baseline_key
from ai.prediction import (
    backend_name as prediction_backend, clear_cache, forecast, predict_series,
)
from ai.prediction.feature_engineering import chronological_split, regression_metrics
from ai.prediction.prediction_service import confidence_label, train_bundle
from ai.risk import (
    BUILDING_WEIGHTS, RiskStability, building_risk, hierarchy_risk, risk_level,
)
from app.core.security import create_token
from app.main import app
from app.services import ai_service
from app.services.risk_engine import compute_risk
from app.services.state import TwinState, get_state

client = TestClient(app)


def _headers(role: str = "ADMIN", username: str = "admin") -> dict:
    token = create_token(f"u_{username}", username, role)
    return {"Authorization": f"Bearer {token}"}


ADMIN = _headers()


# =========================================================== anomaly layers
def test_score_bands_boundaries():
    assert score_band(0) == "NORMAL"
    assert score_band(20) == "NORMAL"
    assert score_band(21) == "LOW"
    assert score_band(41) == "MODERATE"
    assert score_band(61) == "HIGH"
    assert score_band(81) == "CRITICAL"
    assert score_band(150) == "CRITICAL"


def test_threshold_breach_cold_start():
    """L1 must fire with almost no history (confidence not yet meaningful)."""
    out = detect(
        {"s1": [12.0, 14.0, 18.0]},
        {"s1": {"type": "smoke", "label": "Smoke", "building_name": "Eng"}},
        min_samples=30, score_threshold=60, clock_hour=10,
    )
    assert len(out["anomalies"]) == 1
    a = out["anomalies"][0]
    assert a["anomaly_type"] == "THRESHOLD_BREACH"
    assert "threshold" in a["detector"]
    assert a["score"] >= 60 and a["band"] in ("HIGH", "CRITICAL")
    assert a["confidence"] is None
    assert a["data_quality"] == "INSUFFICIENT_DATA"
    assert out["insufficient"][0]["sensor_id"] == "s1"
    assert out["insufficient"][0]["minimum_required"] == 30
    assert a["id"].startswith("anom:")


def test_rolling_spike_classification():
    values = [10, 11, 9.5, 10.2, 9.8, 10.1, 10.4, 9.9, 10.3, 10.0, 45.0]
    out = detect({"s1": values},
                 {"s1": {"type": "energy", "label": "Energy", "building_name": "Eng"}},
                 min_samples=6, score_threshold=60, clock_hour=10)
    a = out["anomalies"][0]
    assert a["anomaly_type"] in ("SUDDEN_SPIKE", "RATE_OF_CHANGE")
    assert "rolling" in a["detector"]
    assert a["score"] >= 80  # z is huge here
    assert "above" in a["explanation"]
    assert a["confidence"] is not None


def test_stable_series_quiet():
    values = [10, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 10.0, 9.9, 10.1, 10.0] * 3
    out = detect({"s1": values}, {"s1": {"type": "energy", "label": "Energy"}},
                 min_samples=6, score_threshold=60, clock_hour=10)
    assert out["anomalies"] == []
    # legacy contract stays green too
    assert detect_anomalies({"s1": values}, {"s1": {"type": "energy", "label": "Energy"}}) == []


def test_insufficient_data_status():
    tracker = AnomalyTracker(min_samples=30, score_threshold=60)
    meta = {"s1": {"type": "temperature", "label": "Temperature", "building_name": "Eng",
                   "building_id": "eng"}}
    res = tracker.update({"s1": [21.0, 21.4, 21.2, 21.5, 21.1, 21.3]}, meta, clock_hour=10)
    assert res["anomalies"] == []
    st = res["sensor_status"]["s1"]
    assert st["status"] == "INSUFFICIENT_DATA"
    assert st["available_samples"] == 6
    assert st["minimum_required"] == 30
    assert res["data_quality"] in ("LIMITED", "INSUFFICIENT")


def test_persistence_second_observation():
    """Score 60-74 statistical detections need two observations (FP control);
    the adopted time-of-day baseline supplies the un-absorbed 2nd signal."""
    tracker = AnomalyTracker(min_samples=6, score_threshold=60)
    meta = {"s1": {"type": "energy", "label": "Energy", "building_name": "Eng",
                   "building_id": "eng"}}
    # σ ≈ 0.5: large enough that the floored time-of-day baseline can also
    # re-fire after the rolling window absorbs the first observation
    stable = [10.0 + v for v in (
        -0.5, 0.5, -0.4, 0.6, -0.6, 0.4, -0.5, 0.5, -0.6, 0.4,
        0.5, -0.4, 0.6, -0.5, -0.6, 0.5, 0.4, -0.5, 0.6)]
    mean = statistics.fmean(stable)
    std = statistics.pstdev(stable)
    # pre-adopt the time-of-day bucket so persistence has a slow baseline
    key = baseline_key("eng", None, "energy", 10)
    tracker.baselines[key] = {"mean": mean, "std": std, "n": 20.0}
    # 4.5σ deviation -> score ~67 (borderline band 60-74, below the strong
    # bonus at 75) for both the rolling window and the TOD baseline
    bump = round(mean + 4.5 * std, 3)
    history = {"s1": stable + [bump]}

    r1 = tracker.update(history, meta, clock_hour=10, use_isolation_forest=False)
    assert r1["anomalies"] == [], "first borderline observation must not raise"

    history["s1"] = history["s1"] + [bump]
    r2 = tracker.update(history, meta, clock_hour=10, use_isolation_forest=False)
    assert len(r2["anomalies"]) == 1, "second consecutive observation raises"
    a = r2["anomalies"][0]
    assert a["observations"] >= 1 and 60 <= a["score"] < 75


def test_strong_detection_raises_immediately():
    tracker = AnomalyTracker(min_samples=6, score_threshold=60)
    meta = {"s1": {"type": "energy", "label": "Energy", "building_name": "Eng",
                   "building_id": "eng"}}
    history = {"s1": [10.0] * 18 + [45.0]}
    r1 = tracker.update(history, meta, clock_hour=10)
    assert len(r1["anomalies"]) == 1
    assert r1["anomalies"][0]["status"] in ("NEW", "ACTIVE")
    assert r1["anomalies"][0]["score"] >= 75


def test_decay_and_release_hysteresis():
    tracker = AnomalyTracker(min_samples=6, score_threshold=60)
    meta = {"s1": {"type": "energy", "label": "Energy", "building_name": "Eng",
                   "building_id": "eng"}}
    history = {"s1": [10.0] * 18 + [45.0]}
    assert tracker.update(history, meta, clock_hour=10)["anomalies"]
    # detector stops firing: anomaly decays 18/cycle, releases below 25
    for _ in range(6):
        history["s1"] = history["s1"] + [10.0]
        result = tracker.update(history, meta, clock_hour=10)
    assert result["anomalies"] == [], "released below score 25"
    assert "s1" not in tracker.tracked


def test_multivariate_relation():
    history = {
        "occ": [500, 505, 498, 502, 499, 501, 500, 498, 502, 500, 300],
        "nrg": [120, 121, 119, 120, 120, 121, 119, 120, 120, 121, 260],
    }
    meta = {
        "occ": {"type": "occupancy", "label": "Occupancy", "building_id": "eng",
                "building_name": "Eng"},
        "nrg": {"type": "energy", "label": "Energy", "building_id": "eng",
                "building_name": "Eng"},
    }
    out = detect(history, meta, min_samples=6, score_threshold=60, clock_hour=10,
                 use_isolation_forest=False)
    types = {a["anomaly_type"] for a in out["anomalies"]}
    assert "MULTIVARIATE_ANOMALY" in types
    mv = next(a for a in out["anomalies"] if a["anomaly_type"] == "MULTIVARIATE_ANOMALY")
    assert mv["detector"] == "multivariate"
    assert "occupancy falling" in mv["reason"]


def test_anomaly_list_filters():
    rows = [
        {"id": "1", "band": "CRITICAL", "severity": "CRITICAL", "building_id": "eng",
         "sensor_id": "a", "metric": "smoke", "first_seen": "2026-01-01T00:00:00",
         "last_seen": "2026-01-01T02:00:00"},
        {"id": "2", "band": "MODERATE", "severity": "MEDIUM", "building_id": "lib",
         "sensor_id": "b", "metric": "temperature", "first_seen": "2026-01-01T04:00:00",
         "last_seen": "2026-01-01T05:00:00"},
    ]
    assert [r["id"] for r in filtered(rows, severity="critical")] == ["1"]
    assert [r["id"] for r in filtered(rows, severity="medium")] == ["2"]  # alias
    assert [r["id"] for r in filtered(rows, building_id="lib")] == ["2"]
    assert [r["id"] for r in filtered(rows, sensor_id="a")] == ["1"]
    assert [r["id"] for r in filtered(rows, metric="temperature")] == ["2"]
    # start = still active after that instant (last_seen >= start)
    assert [r["id"] for r in filtered(rows, start="2026-01-01T03:00:00")] == ["2"]
    # end = existed by that instant (first_seen <= end)
    assert [r["id"] for r in filtered(rows, end="2026-01-01T03:00:00")] == ["1"]
    assert filtered(rows, limit=1) == [rows[0]]


# ============================================================== prediction
def test_chronological_split_no_shuffle():
    X = [[i] for i in range(100)]
    y = list(range(100))
    Xtr, ytr, Xte, yte = chronological_split(X, y, test_fraction=0.2)
    assert Xtr[-1][0] < Xte[0][0], "train must precede test (time ordered)"
    assert len(ytr) == 80 and len(yte) == 20
    assert ytr == list(range(80)) and yte == list(range(80, 100))


def test_regression_metrics_honest():
    m = regression_metrics([10, 11, 12], [11, 10, 12])
    assert m["mae"] == pytest.approx(2 / 3, abs=0.01)
    assert m["rmse"] is not None and m["r2"] is not None
    assert m["mape"] is not None
    # MAPE withheld when the series contains zeros (division unsafe)
    m2 = regression_metrics([0, 0, 5], [1, 1, 5])
    assert m2["mape"] is None
    # R² withheld when the true series has no variance (undefined)
    assert regression_metrics([10, 10, 10], [11, 9, 10])["r2"] is None


def test_forecast_horizons_with_model_versioning(tmp_path):
    clear_cache()
    hours = [(i * 0.25) % 24 for i in range(160)]
    values = [300 + 400 * max(0.0, __import__("math").sin((h - 6) / 14 * 3.14159))
              for h in hours]
    recs = forecast("eng", "occupancy", "Engineering", hours, values,
                    horizons=(15, 30, 60), upper_bound=1200, min_samples=100,
                    model_dir=str(tmp_path))
    assert [r["horizon_min"] for r in recs] == [15, 30, 60]
    for r in recs:
        assert r["model_name"] == "occupancy-rf-v1"
        assert r["model_version"] == "occupancy-rf-v1"
        assert r["status"] in ("OK", "LOW_CONFIDENCE")
        assert r["mae"] is not None and r["rmse"] is not None
        assert 0 <= r["predicted_value"] <= 1200
        assert r["confidence_label"] in ("HIGH", "MEDIUM", "LOW")
        assert "predicted to" in r["summary"]
        assert r["samples"] >= 100 and r["trained_at"]
    # artefact persisted (joblib) for the versioned model
    assert list(tmp_path.glob("occupancy_eng_*.joblib"))
    assert "joblib" in prediction_backend()


def test_forecast_baseline_fallback(tmp_path):
    clear_cache()
    hours = [(i * 0.25) % 24 for i in range(96)]
    values = [300 + 400 * max(0.0, __import__("math").sin((h - 6) / 14 * 3.14159))
              for h in hours]
    recs = forecast("eng", "occupancy", "Engineering", hours, values,
                    horizons=(15, 30, 60), upper_bound=1200, min_samples=100,
                    model_dir=str(tmp_path))
    assert all(r["model_name"] == "BASELINE" for r in recs)
    assert all(r["status"] in ("BASELINE", "LOW_CONFIDENCE") for r in recs)
    assert all(0.3 <= r["confidence"] <= 0.95 for r in recs)


def test_forecast_insufficient_data():
    recs = forecast("x", "energy", "", [1.0], [10.0], horizons=(20,))
    r = recs[0]
    assert r["model_name"] == "insufficient_data"
    assert r["confidence"] == 0.0
    assert r["status"] == "INSUFFICIENT_DATA"
    assert r["confidence_label"] == "N/A"


def test_legacy_predict_series_contract():
    import math
    hours = [(i * 0.25) % 24 for i in range(96)]
    values = [300 + 400 * max(0, math.sin((h - 6) / 14 * math.pi)) for h in hours]
    out = predict_series(hours, values, horizon_min=20, metric="occupancy",
                         entity_id="eng", entity_name="Engineering", upper_bound=1200)
    assert 0 <= out["predicted_value"] <= 1200
    assert 0.3 <= out["confidence"] <= 0.95
    assert out["model_name"]
    assert "predicted to" in out["summary"]


def test_confidence_label_mapping():
    assert confidence_label(0.8, "OK") == "HIGH"
    assert confidence_label(0.6, "OK") == "MEDIUM"
    assert confidence_label(0.4, "LOW_CONFIDENCE") == "LOW"
    assert confidence_label(0.0, "INSUFFICIENT_DATA") == "N/A"


def test_train_bundle_metadata():
    clear_cache()
    hours = [(i * 0.25) % 24 for i in range(160)]
    values = [100 + 40 * ((i * 7) % 11) / 10 for i in range(160)]
    bundle = train_bundle(hours, values, metric="energy", entity_id="eng")
    assert bundle is not None
    assert bundle.version == "energy-rf-v1"
    assert bundle.features  # feature list recorded
    assert bundle.metrics.get("mae") is not None
    assert bundle.samples >= 100
    assert bundle.trained_at


# ==================================================================== risk
def test_weights_documented_with_categories():
    r = building_risk(occupancy=782, capacity=1200, temperature=48.0, smoke=90.0,
                      fire_fraction=0.5, burning_zones=4, blocked_exits=2,
                      total_exits=3, power_ok=False, anomaly_score=0.9)
    assert r["score"] >= 81 and r["level"] == "CRITICAL"
    assert all("category" in f for f in r["factors"])
    smoke_f = next(f for f in r["factors"] if "Smoke" in f["label"])
    assert smoke_f["category"] == "environmental"
    assert smoke_f["weight"] == BUILDING_WEIGHTS["smoke"]
    anomaly_f = next(f for f in r["factors"] if "anomaly" in f["label"].lower())
    assert anomaly_f["category"] == "anomaly"
    assert BUILDING_WEIGHTS["occupancy"] == 15.0
    assert sum(BUILDING_WEIGHTS.values()) > 100  # weights are per-factor caps


def test_risk_stability_no_flapping():
    stab = RiskStability(alpha=0.35, min_delta=1.0)
    # oscillate across the ELEVATED edge (41) raw — published must not flap
    levels = []
    for v in [41.5, 39.4, 41.8, 39.2, 42.0, 39.0, 41.6, 39.5] * 3:
        levels.append(stab.update("campus", v)["level"])
    assert len(set(levels[:10])) == 1, f"level flapped: {levels[:10]}"


def test_risk_stability_jump_publishes_immediately():
    stab = RiskStability(alpha=0.35, min_delta=1.0)
    first = stab.update("campus", 8.0)
    assert first["score"] == 8.0 and first["level"] == "LOW"
    jump = stab.update("campus", 90.0)   # >=25 gap -> raw publishes at once
    assert jump["score"] == 90.0 and jump["level"] == "CRITICAL"
    assert jump["changed"] is True


def test_risk_stability_downgrade_hysteresis():
    stab = RiskStability(alpha=0.5, min_delta=1.0)
    stab.update("campus", 70.0)               # HIGH published
    small = stab.update("campus", 55.0)       # drop, but slower decay rule
    # downgrade needs min_delta * 2.5 movement from the published score
    still = stab.update("campus", 66.0)
    assert still["level"] == "HIGH" or still["changed"] is True
    drop = stab.update("campus", 30.0)
    assert drop["level"] in ("MODERATE", "ELEVATED") and drop["changed"] is True


def test_compute_risk_publishes_stabilised_view():
    state = TwinState(seed=5)
    compute_risk(state)
    assert "campus" in state.risk_published
    pub = state.risk_published["campus"]
    assert pub["score"] >= 0 and pub["level"] == risk_level(pub["score"])
    assert set(state.buildings).issubset(set(state.risk_published) - {"campus"})


def test_hierarchy_risk_structure():
    state = TwinState(seed=5)
    compute_risk(state)
    sensor_status = {sid: {"status": "NORMAL", "score": 0,
                           "available_samples": 40, "minimum_required": 30}
                     for sid in state.sensors}
    # one anomalous + one insufficient sensor
    sid_a = next(iter(state.sensors))
    sensor_status[sid_a] = {"status": "HIGH", "score": 72, "type": "SUDDEN_SPIKE",
                            "detector": "rolling_zscore", "available_samples": 40,
                            "minimum_required": 30}
    sid_b = list(state.sensors)[1]
    sensor_status[sid_b] = {"status": "INSUFFICIENT_DATA", "score": None,
                            "available_samples": 3, "minimum_required": 30}
    h = hierarchy_risk(buildings=state.buildings, building_results=state.building_risk,
                       zones=state.zones, sensors=state.sensors,
                       sensor_status=sensor_status)
    eng = h["buildings"]["eng"]
    assert eng["floors"] and eng["zones"]
    assert eng["level"] == risk_level(eng["score"])
    z0 = next(iter(eng["zones"].values()))
    assert {"id", "floor", "score", "level"} <= set(z0)
    assert h["sensors"][sid_a]["score"] == 72.0
    assert "Insufficient samples" in h["sensors"][sid_b]["explanation"]
    assert h["weights"]["building"] == BUILDING_WEIGHTS


# ======================================================= scheduler + state
def test_run_ai_cycle_end_to_end():
    state = get_state()
    ai_service.warm_series(state)
    result = ai_service.run_ai_cycle(state)
    assert state.anomalies is result["anomalies"]
    assert len(result["predictions"]) >= 12          # 6 buildings x 2 metrics x horizons
    assert result["predictions"][0]["horizon_min"] in (15, 20, 30, 60)
    assert "campus" in result["risk"]
    assert state.ai_health["ok"] is True
    assert state.system_health["ai"] is True
    assert state.sensor_ai_status
    assert state.risk_hierarchy is not None
    assert "buildings" in state.risk_hierarchy


def test_mark_ai_degraded_isolated():
    state = get_state()
    state.ai_health["degraded"] = False
    state.ai_events.clear()
    ai_service.mark_ai_degraded(state, "boom")
    assert state.ai_health["degraded"] is True
    assert state.system_health["ai"] is False
    assert any(e["title"] == "AI ENGINE DEGRADED" for e in state.ai_events)
    # recovery flips health back on the next successful cycle
    ai_service.run_ai_cycle(state)
    assert state.system_health["ai"] is True
    assert state.ai_health["degraded"] is False


def test_ai_events_bounded_timeline():
    state = get_state()
    for i in range(60):
        ai_service.append_ai_event(state, "TEST", f"event {i}")
    assert len(state.ai_events) == 40
    assert state.ai_events[0]["title"] == "event 59"   # newest first


def test_ai_status_phase5_fields():
    state = get_state()
    body = client.get("/api/ai/status", headers=ADMIN).json()
    for key in ("anomaly_engine", "prediction_engine", "healthy",
                "ai_enabled", "degraded", "data_quality", "cycle_interval_s",
                "anomaly_min_samples", "anomaly_score_threshold",
                "prediction_horizons", "tracked_anomalies"):
        assert key in body, key
    assert body["ai_enabled"] in (True, False)


# ============================================================ REST surface
INJECTED = {
    "id": "anom:test:smoke", "sensor_id": "s_test", "metric": "smoke",
    "location": "Engineering", "building_id": "eng", "zone_id": None,
    "value": 55.0, "expected": 3.0, "deviation_pct": 1700.0, "z_score": 9.0,
    "score": 100, "band": "CRITICAL", "severity": "CRITICAL",
    "anomaly_type": "THRESHOLD_BREACH", "detector": "threshold",
    "reason": "value 55.0 at/above critical threshold 40",
    "explanation": "Smoke in Engineering is far above its expected pattern.",
    "method": "threshold", "confidence": None, "baseline": "rolling_window",
    "data_quality": "INSUFFICIENT_DATA", "available_samples": 3,
    "minimum_required": 30, "status": "NEW", "score_raw": 100.0,
    "rate_of_change_pct": 0.0,
    "first_seen": "2026-01-01T00:00:00+00:00",
    "last_seen": "2026-01-01T00:00:00+00:00", "observations": 1,
}


def _inject_anomaly(state: TwinState) -> None:
    """Seed a tracker-resident anomaly (score refreshed so the -18/cycle
    decay still leaves it CRITICAL inside the refresh the GET triggers)."""
    tracker = ai_service._tracker(state)
    tracker.tracked[INJECTED["id"]] = dict(INJECTED)


def test_anomalies_endpoint_filters():
    state = get_state()
    ai_service.run_ai_cycle(state)
    base = client.get("/api/ai/anomalies", headers=ADMIN).json()
    assert {"anomalies", "engine", "sensor_status", "bands",
            "data_quality", "score_threshold", "min_samples"} <= set(base)

    _inject_anomaly(state)
    crit = client.get("/api/ai/anomalies?severity=CRITICAL", headers=ADMIN).json()
    assert all(a["band"] == "CRITICAL" for a in crit["anomalies"])
    assert any(a["id"] == "anom:test:smoke" for a in crit["anomalies"])

    _inject_anomaly(state)
    by_bld = client.get("/api/ai/anomalies?building_id=eng", headers=ADMIN).json()
    assert all(a["building_id"] == "eng" for a in by_bld["anomalies"])

    _inject_anomaly(state)
    by_sensor = client.get("/api/ai/anomalies?sensor_id=s_test", headers=ADMIN).json()
    assert [a["id"] for a in by_sensor["anomalies"]] == ["anom:test:smoke"]

    _inject_anomaly(state)
    by_metric = client.get("/api/ai/anomalies?metric=smoke", headers=ADMIN).json()
    assert all(a["metric"] == "smoke" for a in by_metric["anomalies"])

    _inject_anomaly(state)
    limited = client.get("/api/ai/anomalies?limit=1", headers=ADMIN).json()
    assert len(limited["anomalies"]) == 1

    _inject_anomaly(state)
    ranged = client.get(
        "/api/ai/anomalies?start=2026-01-01T00:00:00%2B00:00", headers=ADMIN).json()
    assert any(a["id"] == "anom:test:smoke" for a in ranged["anomalies"])


def test_anomaly_detail_lookup():
    state = get_state()
    ai_service.run_ai_cycle(state)
    if state.anomalies:
        aid = state.anomalies[0]["id"]
        got = client.get(f"/api/ai/anomalies/{aid}", headers=ADMIN)
        assert got.status_code == 200
        assert got.json()["id"] == aid
    missing = client.get("/api/ai/anomalies/anom:does-not-exist", headers=ADMIN)
    assert missing.status_code == 404


def test_predictions_endpoints():
    state = get_state()
    ai_service.warm_series(state)
    all_preds = client.get("/api/ai/predictions", headers=ADMIN).json()
    assert all_preds["count"] >= 12
    assert set(all_preds["horizons"]) >= {15, 30, 60}
    assert all("model_name" in p and "confidence" in p for p in all_preds["predictions"])

    # Phase 1-3 compat: horizon_min filter still honoured
    one = client.get("/api/ai/predictions?horizon_min=30", headers=ADMIN).json()
    assert one["predictions"] and all(p["horizon_min"] == 30 for p in one["predictions"])

    ent = client.get("/api/ai/predictions?entity_id=eng", headers=ADMIN).json()
    assert all(p["entity_id"] == "eng" for p in ent["predictions"])

    detail = client.get("/api/ai/predictions/eng", headers=ADMIN)
    assert detail.status_code == 200
    assert detail.json()["entity_id"] == "eng"
    assert detail.json()["count"] >= 1

    missing = client.get("/api/ai/predictions/nope-not-real", headers=ADMIN)
    assert missing.status_code == 404

    stored = client.get("/api/predictions", headers=ADMIN)
    assert stored.status_code == 200 and stored.json()["count"] >= 1


def test_risk_endpoints_with_published_block():
    state = get_state()
    ai_service.run_ai_cycle(state)
    body = client.get("/api/risk", headers=ADMIN).json()
    assert 0 <= body["campus"]["score"] <= 100              # Phase 2 compat
    assert "published" in body and "hierarchy" in body
    assert body["published"]["campus"]["level"] == risk_level(
        body["published"]["campus"]["score"])
    assert body["risk_history"]["campus"]

    campus = client.get("/api/risk/campus", headers=ADMIN).json()
    assert 0 <= campus["score"] <= 100
    assert campus["published"] and "history" in campus

    eng = client.get("/api/risk/eng", headers=ADMIN).json()
    assert eng["entity_id"] == "eng" and "factors" in eng
    assert eng["published"]["score"] >= 0


def test_ai_events_endpoint():
    state = get_state()
    state.ai_events.clear()
    ai_service.append_ai_event(state, "ANOMALY", "Anomaly raised · Eng · smoke",
                               "Score 92/100", level="critical", entity_id="eng")
    body = client.get("/api/ai/events", headers=ADMIN).json()
    assert body["count"] >= 1
    assert body["events"][0]["kind"] == "ANOMALY"
    assert body["events"][0]["source"] == "AI"
    assert "ai_health" in body


def test_ai_endpoints_require_read_role():
    viewer = _headers(role="VIEWER", username="viewer")
    assert client.get("/api/ai/anomalies", headers=viewer).status_code == 200
    assert client.get("/api/ai/anomalies").status_code == 401
