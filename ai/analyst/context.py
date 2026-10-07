"""Phase 8 — normalized Analyst context builder (§5/§6).

Collects ONLY what the deterministic engines already produced — risk,
anomalies, predictions, simulation, routes, congestion, bottlenecks, campus
state. Never recomputes anything, never invents values, never includes
secrets (§41) or person-level data (§42 — aggregated occupancy only).

Also provides:
* freshness tracking (§16)      — per-stream data ages in seconds
* grounding material (§40)      — known entity names + numbers the LLM may cite
* context signature / cache key (§44)
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

MODES = ("INCIDENT", "CAMPUS", "BUILDING", "ROUTE", "SIMULATION", "RECOVERY")

_METRIC_LABELS = {
    "temperature": "Temperature", "smoke": "Smoke level", "occupancy": "Occupancy",
    "energy": "Energy draw", "air_quality": "Air quality", "humidity": "Humidity",
    "traffic": "Traffic flow", "parking": "Parking utilisation", "water": "Water usage",
}

_SECRET_KEYS = {
    "api_key", "apikey", "token", "authorization", "password", "secret",
    "jwt", "access_token", "refresh_token", "jwt_secret",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> float:
    return time.time()


def _parse_ts(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def scrub(obj: Any) -> Any:
    """§41 — recursively drop credential-like keys before anything is
    serialized (context hashing, prompts, logs, payloads)."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()
                if str(k).lower() not in _SECRET_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def detect_mode(requested: str | None, building_id: str | None,
                sim: Any, recovery_progress: float) -> str:
    if requested:
        m = str(requested).strip().upper()
        if m in MODES:
            return m
        raise ValueError(f"Unknown analysis mode '{requested}'. Valid: {list(MODES)}")
    if building_id:
        return "BUILDING"
    if sim is not None:
        status = getattr(sim, "status", "") or ""
        if status in ("RECOVERING", "AWAITING_RECOVERY", "COMPLETED"):
            return "RECOVERY"
        if status in ("RUNNING", "PAUSED", "CREATED"):
            return "INCIDENT"
    if recovery_progress < 100.0:
        return "RECOVERY"
    return "CAMPUS"


def _campus_block(state: Any) -> dict:
    metrics = state.metrics() if hasattr(state, "metrics") else {}
    active_incidents = len([i for i in getattr(state, "incidents", [])
                            if (i.get("status") == "ACTIVE")])
    return {
        "status": getattr(state, "status", "NORMAL"),
        "occupancy": int(metrics.get("occupancy", 0)),
        "occupancy_pct": float(metrics.get("occupancy_pct", 0.0)),
        "capacity": state.campus_capacity() if hasattr(state, "campus_capacity") else 0,
        "active_incidents": active_incidents,
        "clock_hour": round(float(metrics.get("clock_hour", 0.0)), 2),
        "temperature": round(float(metrics.get("temperature", 0.0)), 1),
    }


def _simulation_block(state: Any) -> dict:
    sim = getattr(state, "active_sim", None)
    if sim is None:
        return {"active": False, "type": None, "simulation_id": "",
                "status": None, "elapsed_time": 0, "phase": "idle",
                "target_id": None, "target_name": "", "people_at_risk": 0}
    target_name = ""
    if sim.target_id:
        b = state.buildings.get(sim.target_id)
        target_name = b.name if b else str(sim.target_id)
    return {
        "active": sim.status in ("RUNNING", "PAUSED", "CREATED"),
        "type": sim.scenario,
        "simulation_id": sim.id,
        "status": sim.status,
        "elapsed_time": round(float(sim.t), 1),
        "duration": round(float(sim.duration), 1),
        "phase": getattr(sim, "phase", "idle"),
        "target_id": sim.target_id,
        "target_name": target_name,
        "people_at_risk": int(getattr(sim, "people_at_risk", 0) or 0),
        "affected_zones": int(getattr(sim, "affected_zones", 0) or 0),
        "peak_risk": round(float(getattr(sim, "peak_risk", 0.0) or 0.0), 1),
    }


def _risk_block(state: Any) -> dict:
    raw = dict(getattr(state, "risk", {}) or {})
    published = dict((getattr(state, "risk_published", {}) or {}).get("campus", {}) or {})
    score = float(published.get("score", raw.get("score", 0.0)) or 0.0)
    level = published.get("level") or raw.get("level", "LOW")
    trend = published.get("trend")
    if not trend:
        history = (getattr(state, "metric_history", {}) or {}).get("risk", [])[-30:]
        if len(history) >= 2:
            first, last = history[0]["value"], history[-1]["value"]
            delta_h = last - first
            trend = ("INCREASING" if delta_h >= 3 else
                     "DECREASING" if delta_h <= -3 else "STABLE")
        else:
            trend = "STABLE"
    factors = [
        {"label": f.get("label", ""), "contribution": float(f.get("contribution", 0.0)),
         "category": f.get("category", "")}
        for f in (published.get("factors") or raw.get("factors") or [])[:6]
    ]
    return {
        "score": round(score, 1),
        "level": level,
        "trend": trend,
        "delta": round(float(published.get("delta", 0.0) or 0.0), 1),
        "raw_score": round(float(published.get("raw_score", raw.get("score", 0.0)) or 0.0), 1),
        "factors": factors,
        "explanation": str(published.get("explanation") or raw.get("explanation") or ""),
    }


def _anomalies_block(state: Any, now: float) -> list[dict]:
    rows = []
    for a in (getattr(state, "anomalies", []) or [])[:8]:
        ts = _parse_ts(a.get("last_seen") or a.get("first_seen"))
        rows.append({
            "id": a.get("id", ""),
            "metric": a.get("metric", ""),
            "location": a.get("location", ""),
            "building_id": a.get("building_id") or "",
            "severity": str(a.get("severity") or a.get("band") or "LOW").upper(),
            "band": str(a.get("band") or "").upper(),
            "score": float(a.get("score", 0) or 0),
            "status": a.get("status", ""),
            "value": a.get("value"),
            "expected": a.get("expected"),
            "explanation": a.get("explanation", ""),
            "detector": a.get("detector", ""),
            "age_seconds": round(now - ts, 1) if ts else None,
        })
    return rows


def _predictions_block(state: Any, now: float) -> list[dict]:
    rows = []
    preds = sorted(getattr(state, "predictions", []) or [],
                   key=lambda p: -float(p.get("confidence", 0) or 0))
    for p in preds[:8]:
        ts = _parse_ts(p.get("created_at") or p.get("at"))
        location = p.get("entity_name") or p.get("entity_id", "")
        rows.append({
            "metric": p.get("metric", ""),
            "location": location,
            "entity_id": p.get("entity_id", ""),
            "current": p.get("current_value"),
            "predicted": p.get("predicted_value"),
            "horizon_minutes": p.get("horizon_min"),
            "confidence": float(p.get("confidence", 0) or 0),
            "model": p.get("model_name", ""),
            "summary": p.get("summary", ""),
            "status": p.get("status", ""),
            "kind": "PREDICTED",
            "age_seconds": round(now - ts, 1) if ts else None,
        })
    return rows


def _plan_block(plan: Any) -> dict:
    if not plan:
        return {}
    r = plan.get("route") or {}
    return {
        "route_id": plan.get("route_id", ""),
        "kind": plan.get("kind", ""),
        "mode": plan.get("mode", ""),
        "status": plan.get("status", ""),
        "route_version": plan.get("route_version", 0),
        "origin": plan.get("origin") or r.get("origin") or "",
        "destination": plan.get("destination") or r.get("destination") or "",
        "origin_label": r.get("origin_name") or plan.get("origin") or "",
        "destination_label": r.get("destination_name") or plan.get("destination") or "",
        "distance": round(float(r.get("distance", 0.0) or 0.0), 1),
        "estimated_time": round(float(r.get("estimated_time", 0.0) or 0.0), 1),
        "risk_score": round(float(r.get("risk_score", 0.0) or 0.0), 1),
        "congestion_score": round(float(r.get("congestion_score", 0.0) or 0.0), 3),
        "reason": plan.get("reason") or r.get("reason") or "",
        "people_at_risk": int(plan.get("people_at_risk", 0) or 0),
        "created_at": plan.get("created_at") or plan.get("updated_at"),
        "alternatives": [
            {"route_id": alt.get("route_id", ""),
             "status": alt.get("status", ""),
             "risk_score": round(float(alt.get("risk_score", 0.0) or 0.0), 1),
             "estimated_time": round(float(alt.get("estimated_time", 0.0) or 0.0), 1),
             "reason": alt.get("reason", "")}
            for alt in (plan.get("alternatives") or [])[:4]
        ],
    }


def _exit_options(state: Any) -> list[dict]:
    """Legacy optimization routes: per-building exit verdicts with risk."""
    out = []
    for r in (getattr(state, "routes", []) or [])[:8]:
        out.append({
            "building": r.get("building_name", ""),
            "building_id": r.get("building_id", ""),
            "exit": r.get("exit_name") or r.get("exit_id") or "",
            "status": r.get("status", ""),
            "risk": round(float(r.get("risk", 0.0) or 0.0), 1),
            "evac_time_s": round(float(r.get("evac_time_s", r.get("eta_s", 0.0)) or 0.0), 1),
            "reason": r.get("reason", ""),
        })
    return out


def _evacuation_block(state: Any) -> dict:
    evac = dict(getattr(state, "evacuation", {}) or {})
    buildings = []
    for b in (evac.get("buildings") or [])[:6]:
        buildings.append({
            "building_id": b.get("building_id", ""),
            "building_name": b.get("building_name", ""),
            "status": b.get("status", ""),
            "primary_exit": b.get("primary_exit", ""),
            "route_status": b.get("route_status", ""),
            "route_risk": b.get("route_risk"),
            "people_at_risk": b.get("people_at_risk", 0),
            "has_safe_route": b.get("has_safe_route", True),
        })
    return {
        "status": evac.get("status", "IDLE"),
        "mode": evac.get("mode", ""),
        "people_at_risk": int(evac.get("people_at_risk", 0) or 0),
        "critical_buildings": evac.get("critical_buildings", []),
        "blocked_buildings": evac.get("blocked_buildings", []),
        "totals": evac.get("totals", {}),
        "buildings": buildings,
        "bottlenecks": [
            {"location_id": b.get("location_id", ""),
             "location": b.get("location", b.get("location_id", "")),
             "kind": b.get("kind", ""),
             "severity": b.get("severity", ""),
             "estimated_people": b.get("estimated_people", 0),
             "congestion": b.get("congestion"),
             "risk": b.get("risk"),
             "recommendation": b.get("recommendation", "")}
            for b in (evac.get("bottlenecks") or [])[:6]
        ],
        "exits": [
            {"exit_id": e.get("exit_id", ""), "name": e.get("name", ""),
             "people": e.get("people", 0), "pressure": round(float(e.get("pressure", 0.0) or 0.0), 3)}
            for e in (evac.get("exits") or [])[:6]
        ],
    }


def _blocked_paths(state: Any) -> list[dict]:
    roads = getattr(state, "roads", {}) or {}
    node_risk = getattr(state, "node_risk", {}) or {}
    blocked = [{"id": rid, "name": r.get("name", rid), "reason": "road_blocked"}
               for rid, r in roads.items() if r.get("blocked")]
    for nid, risk in node_risk.items():
        if float(risk or 0) >= 75.0:
            node = (getattr(state, "nodes", {}) or {}).get(nid, {})
            blocked.append({"id": nid, "name": node.get("name", nid),
                            "reason": f"node_risk_{round(float(risk))}"})
    for opt in _exit_options(state):
        if opt["status"] == "BLOCKED":
            blocked.append({"id": opt["exit"], "name": opt["exit"],
                            "reason": "exit_blocked"})
    return blocked[:8]


def _affected_zones(state: Any, sim_block: dict) -> list[dict]:
    if not sim_block.get("active"):
        return []
    out = []
    for z in (getattr(state, "zones", {}) or {}).values():
        if z.status in ("FIRE", "SMOKE", "AFFECTED"):
            out.append({"id": z.id, "name": z.name,
                        "building_id": z.building_id, "status": z.status,
                        "risk_level": z.risk_level})
    return out[:10]


def _freshness(state: Any, now: float, route_block: dict,
               preds: list[dict]) -> dict:
    sensors = getattr(state, "sensors", {}) or {}
    ages = [now - float(s.updated_at) for s in sensors.values() if s.healthy]
    pred_ages = [p["age_seconds"] for p in preds if p.get("age_seconds") is not None]
    route_age = None
    ts = _parse_ts(route_block.get("created_at")) if route_block else None
    if ts is not None:
        route_age = now - ts
    return {
        "sensor_oldest_s": round(max(ages), 1) if ages else None,
        "sensor_newest_s": round(min(ages), 1) if ages else None,
        "sensor_count": len(ages),
        "sensor_total": len(sensors),
        "prediction_age_s": round(min(pred_ages), 1) if pred_ages else None,
        "route_age_s": round(route_age, 1) if route_age is not None else None,
        "generated_at": _utc_iso(),
    }


def _names_and_numbers(ctx: dict) -> dict:
    """§40 grounding material — the only names/numbers the LLM may cite."""
    names: set[str] = {"Campus", "TwinSphere"}
    numbers: set[float] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str):
                    names.add(v)
                    if k in ("label", "metric", "factor", "location", "status",
                             "level", "trend", "category", "type", "kind",
                             "severity", "mode", "exit", "building", "name",
                             "target_name", "primary_exit", "detector"):
                        names.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, bool):
            pass
        elif isinstance(o, (int, float)):
            numbers.add(float(o))

    walk(ctx)
    state_names = ctx.get("_state_names") or {}
    for extra in state_names.values():
        for n in extra:
            names.add(str(n))
    return {"names": names, "numbers": numbers}


def build_context(state: Any, mode: str | None = None,
                  building_id: str | None = None,
                  question: str = "") -> dict:
    """§5 — the single normalized input for every analyst run."""
    now = _now()
    sim_block = _simulation_block(state)
    risk = _risk_block(state)
    route_block = _plan_block(getattr(state, "route_plan", None))
    preds = _predictions_block(state, now)
    resolved_mode = detect_mode(mode, building_id, getattr(state, "active_sim", None),
                                float(getattr(state, "recovery_progress", 100.0)))

    buildings = getattr(state, "buildings", {}) or {}
    zones = getattr(state, "zones", {}) or {}
    nodes = getattr(state, "nodes", {}) or {}
    roads = getattr(state, "roads", {}) or {}

    ctx: dict[str, Any] = {
        "timestamp": _utc_iso(),
        "mode": resolved_mode,
        "question": str(question or "")[:500],
        "campus": _campus_block(state),
        "simulation": sim_block,
        "risk": risk,
        "anomalies": _anomalies_block(state, now),
        "predictions": preds,
        "affected_zones": _affected_zones(state, sim_block),
        "people_at_risk": int(sim_block.get("people_at_risk", 0)
                              or (getattr(state, "evacuation", {}) or {}).get("people_at_risk", 0)
                              or 0),
        "routes": {
            "recommended": route_block or None,
            "alternatives": (route_block or {}).get("alternatives", []),
            "exit_options": _exit_options(state),
        },
        "evacuation": _evacuation_block(state),
        "bottlenecks": [],
        "blocked_paths": _blocked_paths(state),
        "recovery": {
            "active": float(getattr(state, "recovery_progress", 100.0)) < 100.0,
            "progress": round(float(getattr(state, "recovery_progress", 100.0)), 1),
        },
        "incidents": [
            {"id": i.get("id", ""), "title": i.get("title", ""),
             "kind": i.get("kind", ""), "severity": i.get("severity", ""),
             "building_id": i.get("building_id")}
            for i in (getattr(state, "incidents", []) or [])
            if i.get("status") == "ACTIVE"
        ],
    }
    ctx["bottlenecks"] = ctx["evacuation"]["bottlenecks"]
    ctx["people_at_risk"] = int(
        sim_block.get("people_at_risk", 0)
        or ctx["evacuation"].get("people_at_risk", 0)
        or 0)

    # entity names the LLM is allowed to mention (§40)
    ctx["_state_names"] = {
        "buildings": [b.name for b in buildings.values()],
        "roads": [r.get("name", "") for r in roads.values()],
        "nodes": [n.get("name", "") for n in nodes.values()],
        "zones": [z.name for z in zones.values()],
        "metrics": list(_METRIC_LABELS.values()),
        "exits": sorted({o["exit"] for o in ctx["routes"]["exit_options"]
                         if o.get("exit")} |
                        {e["name"] for e in ctx["evacuation"]["exits"] if e.get("name")}),
        "scenarios": ["fire", "crowd", "power", "road", "temperature"],
    }
    ctx["freshness"] = _freshness(state, now, route_block, preds)
    ctx["signature"] = context_signature(ctx)
    return scrub(ctx)


def context_signature(ctx: dict) -> str:
    """§44 cache key — meaningful state only, volatility rounded away so an
    unchanged situation reuses the previous analysis instead of burning an
    LLM call."""
    risk = ctx.get("risk", {}) or {}
    sim = ctx.get("simulation", {}) or {}
    routes = ctx.get("routes", {}) or {}
    rec = routes.get("recommended") or {}
    evac = ctx.get("evacuation", {}) or {}
    payload = {
        "m": ctx.get("mode"),
        "risk": [round(float(risk.get("score", 0) or 0)), risk.get("level"),
                 risk.get("trend"), round(float(risk.get("delta", 0) or 0))],
        "sim": [sim.get("simulation_id"), sim.get("status"), sim.get("phase"),
                int(float(sim.get("elapsed_time", 0) or 0) // 30),
                int(sim.get("people_at_risk", 0) or 0)],
        "anom": sorted([a.get("id"), a.get("status"),
                        int(float(a.get("score", 0) or 0) // 5)]
                       for a in ctx.get("anomalies", [])),
        "pred": [[p.get("metric"), p.get("horizon_minutes"),
                  int(float(p.get("current") or 0) // 25),
                  int(float(p.get("predicted") or 0) // 25)]
                 for p in ctx.get("predictions", [])],
        "route": [rec.get("route_id"), rec.get("status"), rec.get("route_version"),
                  rec.get("origin"), rec.get("destination"), rec.get("mode"),
                  round(float(rec.get("risk_score", 0) or 0))],
        "exit": sorted([e.get("exit"), e.get("status"), round(float(e.get("risk", 0) or 0))]
                       for e in routes.get("exit_options", [])),
        "bn": sorted(b.get("location_id", "") for b in ctx.get("bottlenecks", [])),
        "blocked": sorted(b.get("id", "") for b in ctx.get("blocked_paths", [])),
        "evac": [evac.get("status"), int(float(evac.get("people_at_risk", 0) or 0) // 10)],
        "rec": [bool(ctx.get("recovery", {}).get("active")),
                round(float(ctx.get("recovery", {}).get("progress", 100) or 0))],
        "zone": sorted(z.get("status", "") for z in ctx.get("affected_zones", [])),
        "inc": len(ctx.get("incidents", [])),
        "par": int(float(ctx.get("people_at_risk", 0) or 0) // 10),
        "occ": int(float(ctx.get("campus", {}).get("occupancy", 0) or 0) // 25),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]
