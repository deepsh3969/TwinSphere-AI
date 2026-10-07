"""Risk factor definitions with documented, deterministic weights (Phase 5).

Each factor contributes a bounded number of points to the 0-100 risk score;
the weight tables below ARE the documentation (every contribution formula
references them). Factor categories:

  occupancy       — people load vs capacity
  environmental   — smoke, fire, temperature, air quality
  anomaly         — AI anomaly intelligence feeding risk (not an incident!)
  incident        — operational incidents / blocked roads (campus level)
  infrastructure  — exits, power, building status

Risk is a weighted operational indicator, NOT a probability of disaster.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- weights
BUILDING_WEIGHTS: dict[str, float] = {
    "occupancy": 15.0,
    "smoke": 32.0,
    "fire": 34.0,
    "temperature": 16.0,
    "blocked_exits": 20.0,
    "air_quality": 10.0,
    "anomaly": 12.0,
    "power": 14.0,
    "status": 8.0,
}

CAMPUS_WEIGHTS: dict[str, float] = {
    "worst_blend": 0.65,      # share of the worst building score
    "mean_blend": 0.35,       # share of the campus mean score
    "blocked_roads": 12.0,    # max points from blocked roads
    "incidents": 15.0,        # max points from active incidents
    "outdoor_temp": 8.0,      # max points from extreme outdoor temperature
}

FACTOR_CATEGORY = {
    "occupancy": "occupancy",
    "smoke": "environmental", "fire": "environmental",
    "temperature": "environmental", "air_quality": "environmental",
    "anomaly": "anomaly",
    "blocked_exits": "infrastructure", "power": "infrastructure",
    "status": "infrastructure",
    "blocked_roads": "incident", "incidents": "incident",
    "outdoor_temp": "environmental",
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# risk bands (shared by every risk surface): 0-20/21-40/41-60/61-80/81-100
LEVELS: list[tuple[int, str]] = [
    (20, "LOW"),
    (40, "MODERATE"),
    (60, "ELEVATED"),
    (80, "HIGH"),
    (101, "CRITICAL"),
]


def risk_level(score: float) -> str:
    score = max(0.0, min(100.0, score))
    for limit, name in LEVELS:
        if score <= limit:
            return name
    return "CRITICAL"


def _factor(key: str, label: str, contribution: float) -> dict[str, Any]:
    weight = BUILDING_WEIGHTS.get(key) or CAMPUS_WEIGHTS.get(key)
    return {
        "label": label,
        "contribution": round(contribution, 1),
        "category": FACTOR_CATEGORY.get(key, "environmental"),
        "weight": round(weight, 1) if weight is not None else None,
    }


def building_factors(*, occupancy: int, capacity: int, temperature: float,
                     smoke: float, air_quality: float, fire_fraction: float,
                     burning_zones: int, blocked_exits: int, total_exits: int,
                     anomaly_score: float, power_ok: bool,
                     status: str) -> list[dict[str, Any]]:
    """Weighted building risk factors (anomaly_score normalised 0..1)."""
    factors: list[dict[str, Any]] = []

    occ_ratio = occupancy / max(1, capacity)
    if occ_ratio > 0.85:
        c = _clamp((occ_ratio - 0.85) / 0.15, 0, 1) * BUILDING_WEIGHTS["occupancy"]
        factors.append(_factor("occupancy", f"High occupancy ({occ_ratio:.0%} of capacity)", c))
    elif occ_ratio < 0:
        factors.append(_factor("occupancy", "Occupancy data invalid", 5.0))

    if smoke > 5:
        c = _clamp((smoke - 5) / 95.0, 0, 1) * BUILDING_WEIGHTS["smoke"]
        factors.append(_factor("smoke", f"Smoke detected ({smoke:.0f} ppm)", c))

    if fire_fraction > 0:
        c = _clamp(fire_fraction, 0, 1) * BUILDING_WEIGHTS["fire"]
        factors.append(_factor("fire", f"{burning_zones} zone(s) affected by fire", c))

    if temperature > 35:
        c = _clamp((temperature - 35) / 20.0, 0, 1) * BUILDING_WEIGHTS["temperature"]
        factors.append(_factor("temperature", f"Elevated temperature ({temperature:.0f}°C)", c))

    if blocked_exits > 0:
        frac = blocked_exits / max(1, total_exits)
        c = frac * BUILDING_WEIGHTS["blocked_exits"]
        factors.append(_factor("blocked_exits", f"{blocked_exits}/{total_exits} exits unavailable", c))

    if air_quality > 120:
        c = _clamp((air_quality - 120) / 180.0, 0, 1) * BUILDING_WEIGHTS["air_quality"]
        factors.append(_factor("air_quality", f"Poor air quality (AQI {air_quality:.0f})", c))

    if anomaly_score > 0.5:
        c = _clamp(anomaly_score, 0, 1) * BUILDING_WEIGHTS["anomaly"]
        factors.append(_factor("anomaly", "Sensor telemetry anomaly", c))

    if not power_ok:
        factors.append(_factor("power", "Power failure — degraded systems",
                               BUILDING_WEIGHTS["power"]))

    if status in ("EVACUATING", "ISOLATED"):
        factors.append(_factor("status", f"Building status: {status}",
                               BUILDING_WEIGHTS["status"]))
    return factors


def campus_factors(building_results: dict[str, dict], *, blocked_roads: int,
                   active_incidents: int, outdoor_temp: float) -> list[dict[str, Any]]:
    """Campus-level factors on top of the blended building scores."""
    factors: list[dict[str, Any]] = []
    if blocked_roads > 0:
        c = min(CAMPUS_WEIGHTS["blocked_roads"], blocked_roads * 6)
        factors.append({"label": f"{blocked_roads} road(s) blocked", "contribution": round(c, 1),
                        "category": "incident", "weight": CAMPUS_WEIGHTS["blocked_roads"]})
    if active_incidents > 0:
        c = min(CAMPUS_WEIGHTS["incidents"], active_incidents * 7)
        factors.append({"label": f"{active_incidents} active incident(s)",
                        "contribution": round(c, 1),
                        "category": "incident", "weight": CAMPUS_WEIGHTS["incidents"]})
    if outdoor_temp > 38:
        c = min(CAMPUS_WEIGHTS["outdoor_temp"], (outdoor_temp - 38) * 2)
        factors.append({"label": f"Extreme outdoor temperature ({outdoor_temp:.0f}°C)",
                        "contribution": round(c, 1),
                        "category": "environmental",
                        "weight": CAMPUS_WEIGHTS["outdoor_temp"]})
    return factors


def sensor_risk(anomaly_status: dict[str, Any] | None) -> dict[str, Any]:
    """Sensor-level risk indicator from its AI anomaly status (0..100).

    An anomaly is NOT an incident: a sensor with no anomaly and enough
    samples is LOW; insufficient data stays LOW with a data note.
    """
    if not anomaly_status:
        return {"score": 0.0, "level": "LOW", "factors": [],
                "explanation": "No AI telemetry status available."}
    if anomaly_status.get("status") == "INSUFFICIENT_DATA":
        return {"score": 0.0, "level": "LOW", "factors": [],
                "explanation": (
                    "Insufficient samples for AI analysis "
                    f"({anomaly_status.get('available_samples', 0)}/"
                    f"{anomaly_status.get('minimum_required', 0)}).")}
    score = float(anomaly_status.get("score") or 0.0)
    return {
        "score": round(score, 1),
        "level": risk_level(score),
        "factors": ([{"label": f"{anomaly_status.get('type', 'Anomaly')} ({anomaly_status.get('detector', '')})",
                      "contribution": round(score, 1), "category": "anomaly", "weight": None}]
                    if score > 0 else []),
        "explanation": (f"Telemetry anomaly score {score:.0f}/100." if score > 0
                        else "Telemetry within expected bounds."),
    }
