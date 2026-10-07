"""Deterministic risk engine (Phase 5).

Weighted 0-100 scores with documented factors, entity hierarchy
(campus -> building -> floor -> zone -> sensor) and deterministic
explanations — no LLM anywhere in this path. Scores are weighted
operational indicators, not probabilities.
"""

from __future__ import annotations

from typing import Any

from ai.risk.risk_factors import (
    BUILDING_WEIGHTS,
    CAMPUS_WEIGHTS,
    LEVELS,
    building_factors,
    campus_factors,
    risk_level,
    sensor_risk,
)

__all__ = ["BUILDING_WEIGHTS", "CAMPUS_WEIGHTS", "LEVELS",
           "building_risk", "campus_risk", "hierarchy_risk", "risk_level"]


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def building_risk(
    *,
    occupancy: int = 0,
    capacity: int = 1,
    temperature: float = 24.0,
    smoke: float = 0.0,
    air_quality: float = 45.0,
    fire_fraction: float = 0.0,
    burning_zones: int = 0,
    blocked_exits: int = 0,
    total_exits: int = 1,
    anomaly_score: float = 0.0,
    power_ok: bool = True,
    status: str = "OPERATIONAL",
) -> dict:
    factors = building_factors(
        occupancy=occupancy, capacity=capacity, temperature=temperature,
        smoke=smoke, air_quality=air_quality, fire_fraction=fire_fraction,
        burning_zones=burning_zones, blocked_exits=blocked_exits,
        total_exits=total_exits, anomaly_score=anomaly_score,
        power_ok=power_ok, status=status,
    )
    score = _clamp(sum(f["contribution"] for f in factors))
    level = risk_level(score)
    if not factors:
        explanation = "All monitored indicators within normal operating bounds."
    else:
        top = sorted(factors, key=lambda f: f["contribution"], reverse=True)[:3]
        explanation = "Primary drivers: " + "; ".join(f["label"] for f in top) + "."
    return {
        "score": round(score, 1),
        "level": level,
        "factors": sorted(factors, key=lambda f: f["contribution"], reverse=True),
        "explanation": explanation,
    }


def campus_risk(building_results: dict[str, dict], *, blocked_roads: int = 0,
                active_incidents: int = 0, outdoor_temp: float = 26.0) -> dict:
    if not building_results:
        return {"score": 0.0, "level": "LOW", "factors": [], "explanation": "No buildings."}
    scores = [r["score"] for r in building_results.values()]
    worst_id = max(building_results, key=lambda k: building_results[k]["score"])
    worst = building_results[worst_id]
    # dominant influence of the worst building, blended with campus mean
    score = (CAMPUS_WEIGHTS["worst_blend"] * max(scores)
             + CAMPUS_WEIGHTS["mean_blend"] * (sum(scores) / len(scores)))
    factors: list[dict[str, Any]] = [{
        "label": f"{worst_id}: {worst['explanation']}",
        "contribution": round(CAMPUS_WEIGHTS["worst_blend"] * worst["score"], 1),
        "category": "occupancy" if worst.get("level") == "LOW" else "environmental",
        "weight": CAMPUS_WEIGHTS["worst_blend"],
    }]
    extras = campus_factors(building_results, blocked_roads=blocked_roads,
                            active_incidents=active_incidents, outdoor_temp=outdoor_temp)
    for f in extras:
        score += f["contribution"]
        factors.append(f)

    score = _clamp(score)
    level = risk_level(score)
    explanation = (
        f"Campus risk is {score:.0f}/100 ({level}). Worst area: "
        f"{building_results[worst_id].get('level', 'LOW')} in {worst_id}."
    )
    return {"score": round(score, 1), "level": level,
            "factors": sorted(factors, key=lambda f: f["contribution"], reverse=True),
            "explanation": explanation, "worst_building": worst_id}


# ----------------------------------------------------------------- hierarchy
def hierarchy_risk(*, buildings: dict[str, Any],
                   building_results: dict[str, dict],
                   zones: dict[str, Any],
                   sensors: dict[str, Any],
                   sensor_status: dict[str, dict]) -> dict[str, Any]:
    """Campus -> building -> floor -> zone -> sensor risk detail.

    Every level shows how the level below contributes (deterministic
    aggregation: zone from its own state, floor = mean of its zones,
    building = its weighted factors + worst zone, campus = blended result).
    """
    zones_by_building: dict[str, list[Any]] = {}
    for z in zones.values():
        zones_by_building.setdefault(z.building_id, []).append(z)

    building_detail: dict[str, dict] = {}
    for bid, bres in building_results.items():
        bzones = zones_by_building.get(bid, [])
        zone_rows: dict[str, dict] = {}
        floors: dict[str, dict] = {}
        for z in bzones:
            zscore = 0.0
            zfactors: list[dict] = []
            if z.status == "FIRE" or z.fire > 0:
                c = round(min(100.0, 45.0 + 40.0 * z.fire), 1)
                zscore = max(zscore, c)
                zfactors.append({"label": f"Fire in zone ({z.fire:.0%})",
                                 "contribution": c, "category": "environmental"})
            if z.smoke > 5:
                c = round(min(55.0, z.smoke * 0.55), 1)
                zscore = max(zscore, c)
                zfactors.append({"label": f"Smoke {z.smoke:.0f}",
                                 "contribution": c, "category": "environmental"})
            if z.temperature > 33:
                c = round(min(45.0, (z.temperature - 33) * 3.0), 1)
                zscore = max(zscore, c)
                zfactors.append({"label": f"Temperature {z.temperature:.0f}°C",
                                 "contribution": c, "category": "environmental"})
            zlevel = risk_level(zscore)
            zone_rows[z.id] = {
                "id": z.id, "name": z.name, "floor": z.floor,
                "score": zscore, "level": zlevel,
                "factors": zfactors,
                "explanation": (f"Zone {z.name}: " + "; ".join(f["label"] for f in zfactors)
                                if zfactors else f"Zone {z.name} nominal."),
            }
            bucket = floors.setdefault(str(z.floor), {
                "floor": z.floor, "score": 0.0, "zones": [], "level": "LOW",
            })
            bucket["zones"].append(z.id)
            bucket["score"] += zscore
        for bucket in floors.values():
            n = max(1, len(bucket["zones"]))
            bucket["score"] = round(bucket["score"] / n, 1)
            bucket["level"] = risk_level(bucket["score"])
            bucket["worst_zone"] = max(
                bucket["zones"], key=lambda zid: zone_rows[zid]["score"]) if bucket["zones"] else None

        building_detail[bid] = {
            "score": bres["score"], "level": bres["level"],
            "factors": bres["factors"], "explanation": bres["explanation"],
            "floors": floors, "zones": zone_rows,
            "worst_zone": (max(zone_rows, key=lambda zid: zone_rows[zid]["score"])
                           if zone_rows else None),
        }

    sensor_rows: dict[str, dict] = {}
    for sid, status in sensor_status.items():
        s = sensors.get(sid)
        if not s:
            continue
        sres = sensor_risk(status)
        sensor_rows[sid] = {
            "id": sid, "name": s.name if s else sid, "type": s.type if s else "",
            "building_id": s.building_id if s else None,
            "status": status.get("status", "NORMAL"),
            "score": sres["score"], "level": sres["level"],
            "explanation": sres["explanation"],
        }

    return {"buildings": building_detail, "sensors": sensor_rows,
            "weights": {"building": BUILDING_WEIGHTS, "campus": CAMPUS_WEIGHTS}}
