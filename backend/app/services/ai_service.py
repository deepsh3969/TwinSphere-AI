"""AI service glue: anomaly detection, prediction refresh, risk publication,
AI scheduler cycle, analyst context (Phase 5).

`run_ai_cycle` is the unit the runtime scheduler executes every
AI_ANALYSIS_INTERVAL_SECONDS: anomalies -> predictions -> stabilised risk ->
bounded AI event timeline. Every failure is contained here so an AI error
never stops the simulation, WebSocket or REST layers (degraded mode).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from ai.anomaly import AnomalyTracker, backend_name as anomaly_backend
from ai.prediction import backend_name as prediction_backend, forecast
from app.core.config import settings
from app.services.risk_engine import compute_risk, refresh_risk_hierarchy
from app.services.sensor_engine import BUILDING_PROFILE as PROFILES, occupancy_curve
from app.services.state import TwinState

SERIES_INTERVAL_VSEC = 900.0  # sample the prediction series every 15 virtual minutes
AI_EVENTS_LIMIT = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ timeline
def append_ai_event(state: TwinState, kind: str, title: str, detail: str = "",
                    level: str = "info", entity_id: str | None = None) -> None:
    state.ai_events.insert(0, {
        "id": f"aiev_{int(time.time() * 1000)}_{len(state.ai_events)}",
        "kind": kind,            # ANOMALY | PREDICTION | RISK | DATA | SYSTEM
        "title": title, "detail": detail, "level": level,   # info | warn | critical
        "entity_id": entity_id, "at": _now(), "source": "AI",
    })
    del state.ai_events[AI_EVENTS_LIMIT:]


# ------------------------------------------------------------------ anomalies
def _tracker(state: TwinState) -> AnomalyTracker:
    t = getattr(state, "_anomaly_tracker", None)
    if (t is None or t.min_samples != settings.ANOMALY_MIN_SAMPLES
            or t.score_threshold != settings.ANOMALY_SCORE_THRESHOLD
            or t.max_tracked != settings.ANOMALY_MAX_TRACKED):
        t = AnomalyTracker(min_samples=settings.ANOMALY_MIN_SAMPLES,
                           score_threshold=settings.ANOMALY_SCORE_THRESHOLD,
                           max_tracked=settings.ANOMALY_MAX_TRACKED)
        state._anomaly_tracker = t
    return t


def _sensor_meta(state: TwinState) -> dict[str, dict]:
    labels = {
        "occupancy": "Occupancy", "temperature": "Temperature", "energy": "Energy draw",
        "smoke": "Smoke level", "air_quality": "Air quality", "humidity": "Humidity",
        "traffic": "Traffic flow", "parking": "Parking utilisation", "water": "Water usage",
    }
    meta: dict[str, dict] = {}
    for s in state.sensors.values():
        b = state.buildings.get(s.building_id) if s.building_id else None
        meta[s.id] = {
            "type": s.type, "unit": s.unit, "building_id": s.building_id,
            "building_name": b.name if b else "Campus", "name": s.name,
            "label": labels.get(s.type, s.type.title()),
        }
    return meta


def refresh_anomalies(state: TwinState) -> dict:
    """Run the layered detector + tracker over live sensor history."""
    meta = _sensor_meta(state)
    history = {sid: list(s.history) for sid, s in state.sensors.items()}
    previous_ids = {a["id"] for a in state.anomalies}
    try:
        result = _tracker(state).update(history, meta, clock_hour=state.clock_hour)
    except Exception:
        state.anomalies = []
        raise
    state.anomalies = result["anomalies"]
    state.sensor_ai_status = result["sensor_status"]
    for a in state.anomalies:
        if a["id"] not in previous_ids and a.get("status") in ("NEW", "ACTIVE"):
            if a.get("status") == "NEW" or a["score"] >= settings.ANOMALY_SCORE_THRESHOLD:
                append_ai_event(
                    state, "ANOMALY",
                    f"Anomaly raised · {a['location']} · {a['metric']}",
                    f"Score {a['score']}/100 ({a['band']}) — {a['reason']} "
                    f"[{a['detector']}]",
                    level="critical" if a["band"] in ("HIGH", "CRITICAL") else "warn",
                    entity_id=a.get("building_id"))
    return result


# ---------------------------------------------------------------- predictions
def refresh_predictions(state: TwinState,
                        horizon_min: int | None = None) -> list[dict]:
    """Forecast every building x metric x configured horizon (Phase 5)."""
    horizons: tuple[int, ...] = settings.PREDICTION_HORIZONS
    if horizon_min is not None:
        horizons = (horizon_min,)
    predictions: list[dict] = []
    for b in state.buildings.values():
        occ_series = state.series.get(f"occupancy:{b.id}")
        ratio = None
        if occ_series:
            ratio = [round(v[1] / max(1, b.capacity), 4) for v in occ_series]
        for metric, upper, sibling in (
            ("occupancy", float(b.capacity), None),
            ("energy", float(b.capacity), ratio),
        ):
            series = state.series.get(f"{metric}:{b.id}")
            if not series:
                continue
            hours = [p[0] for p in series]
            values = [p[1] for p in series]
            values[-1] = round(float(b.occupancy if metric == "occupancy" else b.energy), 1)
            if sibling is not None and len(sibling) != len(values):
                sibling = sibling[: len(values)] + [0.0] * max(0, len(values) - len(sibling))
            try:
                records = forecast(
                    b.id, metric, b.name, hours, values,
                    horizons=horizons, lower_bound=0.0, upper_bound=upper,
                    sibling=sibling, min_samples=settings.PREDICTION_MIN_SAMPLES,
                    retrain_seconds=settings.PREDICTION_RETRAIN_SECONDS,
                    model_dir=settings.MODEL_DIR, entity_type="building",
                )
            except Exception:
                continue
            predictions.extend(records)
    state.predictions = predictions
    return predictions


# --------------------------------------------------------------- AI scheduler
def run_ai_cycle(state: TwinState) -> dict:
    """One scheduler unit: anomalies -> predictions -> stabilised risk.

    Raises on failure — the runtime catches and flips AI to degraded mode
    without touching simulation, WebSocket or REST health.
    """
    previous_level = state.risk_published.get("campus", {}).get("level")
    previous_quality = state.ai_health.get("data_quality", "OK")

    anomaly_result = refresh_anomalies(state)
    predictions = refresh_predictions(state)
    compute_risk(state)  # raw physics + stabilised publication (per-tick cadence)
    refresh_risk_hierarchy(state, anomaly_result["sensor_status"])
    published = state.risk_published

    campus_pub = published.get("campus", {})
    level = campus_pub.get("level")
    if level and previous_level and level != previous_level:
        rank = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4}
        worsening = rank.get(level, 0) > rank.get(previous_level, 0)
        append_ai_event(
            state, "RISK",
            f"Campus risk {previous_level} → {level}",
            f"Stabilised score {campus_pub.get('score', 0)} "
            f"(raw {campus_pub.get('raw_score', 0)}, Δ {campus_pub.get('delta', 0)}).",
            level="critical" if worsening else "info")

    quality = anomaly_result.get("data_quality", "OK")
    if quality != previous_quality:
        append_ai_event(
            state, "DATA",
            f"Data quality: {quality}",
            f"{len(anomaly_result.get('insufficient', []))} sensors below "
            f"{settings.ANOMALY_MIN_SAMPLES}-sample minimum.",
            level="info" if quality == "OK" else "warn")

    state.ai_health.update({
        "ok": True, "degraded": False, "last_cycle": _now(),
        "errors": 0, "data_quality": quality,
        "cycle_interval_s": settings.AI_ANALYSIS_INTERVAL_SECONDS,
        "anomaly_engine": anomaly_backend(), "prediction_engine": prediction_backend(),
    })
    state.system_health["ai"] = True

    return {
        "anomalies": state.anomalies,
        "predictions": predictions,
        "risk": published,
        "data_quality": quality,
        "sensor_status": anomaly_result["sensor_status"],
        "new_anomalies": [a for a in state.anomalies if a.get("status") == "NEW"],
    }


def mark_ai_degraded(state: TwinState, error: str) -> None:
    """Called by the runtime when a cycle raises — UI shows DEGRADED mode."""
    was_ok = not state.ai_health.get("degraded", False)
    state.ai_health.update({"ok": False, "degraded": True,
                            "errors": int(state.ai_health.get("errors", 0)) + 1,
                            "last_error": error, "last_error_at": _now()})
    state.system_health["ai"] = False
    if was_ok:
        append_ai_event(state, "SYSTEM", "AI ENGINE DEGRADED",
                        f"Analysis cycle failed: {error}. Simulation and "
                        f"WebSocket keep running.", level="critical")


# ------------------------------------------------------------------ series
def warm_series(state: TwinState, hours: int = 24) -> None:
    """Build 24h of deterministic history per building for prediction models."""
    points = hours * 4
    for b in state.buildings.values():
        profile = PROFILES.get(b.id, PROFILES["eng"])
        occ_series, energy_series = [], []
        for i in range(points):
            h = (state.clock / 3600.0 - (points - 1 - i) * 0.25) % 24
            frac = occupancy_curve(h, profile)
            occ = b.capacity * frac
            working = 1.0 if 7 <= h <= 19 else 0.35
            energy = b.capacity * 0.055 * (0.35 + 0.75 * frac) * working
            occ_series.append((round(h, 3), round(occ, 1)))
            energy_series.append((round(h, 3), round(energy, 1)))
        state.series[f"occupancy:{b.id}"] = occ_series
        state.series[f"energy:{b.id}"] = energy_series
    state._last_series_sample = state.clock


def maybe_sample_series(state: TwinState) -> None:
    if state.clock - state._last_series_sample < SERIES_INTERVAL_VSEC:
        return
    state._last_series_sample = state.clock
    h = round(state.clock_hour, 3)
    for b in state.buildings.values():
        for metric, value in (("occupancy", b.occupancy), ("energy", b.energy)):
            key = f"{metric}:{b.id}"
            series = state.series.setdefault(key, [])
            series.append((h, round(value, 1)))
            if len(series) > 400:
                del series[: len(series) - 400]


# ------------------------------------------------------------------- analyst
def analyst_context(state: TwinState) -> dict:
    sim = state.active_sim
    target_name = ""
    if sim and sim.target_id:
        target_name = state.buildings[sim.target_id].name if sim.target_id in state.buildings else sim.target_id
    closed = None
    if sim and sim.scenario == "road":
        road = state.roads.get(sim.params.get("road_id", ""))
        closed = road["name"] if road else None
    return {
        "clock_hour": round(state.clock_hour, 2),
        "risk": state.risk,
        "metrics": state.metrics(),
        "active_sim": sim.to_dict() if sim else None,
        "target_name": target_name,
        "closed_road": closed,
        "routes": [
            {k: r.get(k) for k in ("building_name", "exit_name", "status", "risk", "evac_time_s", "reason")}
            for r in state.routes
        ],
        "top_anomalies": [
            {"metric": a["metric"], "location": a["location"], "explanation": a["explanation"]}
            for a in state.anomalies[:4]
        ],
        "incidents": [i for i in state.incidents if i["status"] == "ACTIVE"],
        "recommendations": [
            {"title": r["title"], "priority": r["priority"], "status": r["status"]}
            for r in state.recommendations[:5]
        ],
    }


async def run_analyst(state: TwinState) -> dict:
    """Back-compat Phase 5 entry point — now the full Phase 8 pipeline
    (context → cache/cooldown → structured AnalystResult → events → persist).
    Kept so boot, tests and legacy callers keep working unchanged."""
    from app.services import analyst_service

    result = await analyst_service.analyze_now(state, trigger="internal",
                                               force=True)
    state.system_health["ai"] = True
    return result


def ai_status(state: TwinState) -> dict:
    health = state.ai_health
    return {
        "anomaly_engine": anomaly_backend(),
        "prediction_engine": prediction_backend(),
        "analyst": "LLM (" + settings.LLM_MODEL + ")" if settings.LLM_API_KEY
        else "local deterministic fallback",
        "llm_configured": bool(settings.LLM_API_KEY),
        "healthy": not health.get("degraded", False),
        # Phase 5 detail
        "ai_enabled": settings.AI_ENABLED,
        "degraded": health.get("degraded", False),
        "last_cycle": health.get("last_cycle"),
        "last_error": health.get("last_error"),
        "cycle_interval_s": settings.AI_ANALYSIS_INTERVAL_SECONDS,
        "data_quality": health.get("data_quality", "OK"),
        "anomaly_min_samples": settings.ANOMALY_MIN_SAMPLES,
        "anomaly_score_threshold": settings.ANOMALY_SCORE_THRESHOLD,
        "prediction_min_samples": settings.PREDICTION_MIN_SAMPLES,
        "prediction_horizons": list(settings.PREDICTION_HORIZONS),
        "model_dir": settings.MODEL_DIR,
        "tracked_anomalies": len(state.anomalies),
        "insufficient_sensors": sum(
            1 for s in state.sensor_ai_status.values()
            if s.get("status") == "INSUFFICIENT_DATA"),
    }
