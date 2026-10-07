"""Phase 8 — confidence calculation (§15/§16).

Weighted combination of evidence quality signals: sensor availability, data
freshness, anomaly agreement, prediction confidence, route certainty and
simulation consistency. Capped at 0.95 — the Analyst never claims near-
certainty without validated statistical evidence, and stale data lowers
confidence with an explicit human-readable note.
"""

from __future__ import annotations

from typing import Any

WEIGHTS = {
    "sensor_availability": 0.22,
    "freshness": 0.20,
    "anomaly_agreement": 0.13,
    "prediction_confidence": 0.15,
    "route_certainty": 0.18,
    "simulation_consistency": 0.12,
}

OVERALL_CAP = 0.95
OVERALL_FLOOR = 0.05


def _freshness_score(age: float | None) -> float | None:
    if age is None:
        return None
    if age <= 15:
        return 1.0
    if age <= 30:
        return 0.85
    if age <= 60:
        return 0.7
    if age <= 120:
        return 0.5
    if age <= 300:
        return 0.3
    return 0.15


def _level(overall: float) -> str:
    if overall >= 0.75:
        return "HIGH"
    if overall >= 0.5:
        return "MEDIUM"
    return "LOW"


def compute_confidence(ctx: dict, evidence: list[Any] | None = None) -> dict:
    """Returns {overall, level, components, notes} for a normalized context."""
    fresh = ctx.get("freshness", {}) or {}
    notes: list[str] = []
    scores: dict[str, float] = {}

    # --- sensor availability --------------------------------------------------
    total = int(fresh.get("sensor_total") or 0)
    healthy = int(fresh.get("sensor_count") or 0)
    if total > 0:
        scores["sensor_availability"] = healthy / total
        if healthy < total:
            notes.append(
                f"Confidence reduced because {total - healthy} of {total} "
                f"sensors are offline.")
    else:
        scores["sensor_availability"] = 0.9

    # --- freshness (§16) ------------------------------------------------------
    stream_scores = [s for s in (
        _freshness_score(fresh.get("sensor_oldest_s")),
        _freshness_score(fresh.get("prediction_age_s")),
        _freshness_score(fresh.get("route_age_s")),
    ) if s is not None]
    scores["freshness"] = (sum(stream_scores) / len(stream_scores)
                           if stream_scores else 0.75)
    if fresh.get("sensor_oldest_s") is not None and fresh["sensor_oldest_s"] > 60:
        notes.append(f"Confidence reduced because current sensor data is "
                     f"{round(fresh['sensor_oldest_s'])} seconds old.")
    if fresh.get("prediction_age_s") is not None and fresh["prediction_age_s"] > 180:
        notes.append(f"Confidence reduced because the latest prediction is "
                     f"{round(fresh['prediction_age_s'])} seconds old.")
    if fresh.get("route_age_s") is not None and fresh["route_age_s"] > 120:
        notes.append(f"Confidence reduced because the active route was "
                     f"calculated {round(fresh['route_age_s'])} seconds ago.")

    # --- anomaly agreement ----------------------------------------------------
    anomalies = ctx.get("anomalies") or []
    if not anomalies:
        scores["anomaly_agreement"] = 1.0
    else:
        active = [a for a in anomalies if a.get("status") not in ("RESOLVED",)]
        score = 1.0 - min(0.45, 0.09 * len(active))
        severe = any(str(a.get("severity", "")).upper() in ("HIGH", "CRITICAL")
                     for a in active)
        risk_elevated = str(ctx.get("risk", {}).get("level", "")).upper() in (
            "ELEVATED", "HIGH", "CRITICAL")
        if severe == risk_elevated:
            score = min(1.0, score + 0.1)
        else:
            score = max(0.3, score - 0.1)
            notes.append("Confidence reduced because anomaly severity and the "
                         "campus risk level disagree.")
        scores["anomaly_agreement"] = score

    # --- prediction confidence ------------------------------------------------
    preds = ctx.get("predictions") or []
    if preds:
        confs = [float(p.get("confidence") or 0.0) for p in preds]
        scores["prediction_confidence"] = sum(confs) / len(confs)
        if any(c < 0.5 for c in confs):
            notes.append("Some forecasts are low-confidence (cold-start "
                         "baseline); projections should be treated cautiously.")
    else:
        scores["prediction_confidence"] = 0.7

    # --- route certainty ------------------------------------------------------
    rec = (ctx.get("routes") or {}).get("recommended")
    if rec:
        status = str(rec.get("status", "")).upper()
        scores["route_certainty"] = {
            "RECOMMENDED": 0.92, "ALTERNATIVE": 0.75,
            "NOT_RECOMMENDED": 0.55, "BLOCKED": 0.4,
        }.get(status, 0.7)
        if status not in ("RECOMMENDED",):
            notes.append(f"Confidence reduced because the active route is "
                         f"{status or 'unrated'}.")
    else:
        incident = bool(ctx.get("simulation", {}).get("active"))
        scores["route_certainty"] = 0.5 if incident else 0.85
        if incident:
            notes.append("Confidence reduced because no active route plan "
                         "exists for the incident.")

    # --- simulation consistency ----------------------------------------------
    sim = ctx.get("simulation", {}) or {}
    risk = ctx.get("risk", {}) or {}
    trend = str(risk.get("trend", "STABLE"))
    if not sim.get("active"):
        scores["simulation_consistency"] = 1.0 if trend != "INCREASING" else 0.75
    elif ctx.get("mode") == "RECOVERY":
        scores["simulation_consistency"] = 0.9 if trend == "DECREASING" else 0.7
    else:
        expected = trend in ("INCREASING", "STABLE")
        scores["simulation_consistency"] = 0.9 if expected else 0.65
        if not expected:
            notes.append("Confidence reduced because risk is decreasing while "
                         "the simulation is still active — verify against live "
                         "sensors.")

    components = []
    overall = 0.0
    for name, weight in WEIGHTS.items():
        value = round(min(1.0, max(0.0, scores.get(name, 0.7))), 3)
        contribution = round(value * weight, 4)
        overall += contribution
        components.append({"name": name, "value": value, "weight": weight,
                           "contribution": contribution})

    overall = round(min(OVERALL_CAP, max(OVERALL_FLOOR, overall)), 3)
    return {
        "overall": overall,
        "level": _level(overall),
        "components": components,
        "notes": notes,
    }
