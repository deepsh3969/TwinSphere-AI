"""Analytics time-series endpoints (Recharts-friendly payloads)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require
from app.models.entities import Incident, SensorReading, Simulation
from app.services.sensor_engine import BUILDING_PROFILE, occupancy_curve, outdoor_temperature
from app.services.state import get_state

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

RANGES = {
    "1H": {"hours": 1, "step_min": 1},
    "6H": {"hours": 6, "step_min": 5},
    "24H": {"hours": 24, "step_min": 15},
    "7D": {"hours": 168, "step_min": 120},
    "30D": {"hours": 720, "step_min": 480},
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/timeseries")
def timeseries(window: str = Query("24H", alias="range"), principal: dict = Depends(require("read")),
               db: Session = Depends(get_db)):
    cfg = RANGES.get(window.upper())
    if cfg is None:
        cfg = RANGES["24H"]
    state = get_state()
    now = datetime.now(timezone.utc)
    step = timedelta(minutes=cfg["step_min"])
    count = max(2, int(cfg["hours"] * 60 / cfg["step_min"]))

    sims = db.query(Simulation).all()
    incidents = db.query(Incident).all()
    # risk/prediction persisted samples for this window
    from app.models.entities import Prediction, RiskScore
    risk_rows = (db.query(RiskScore)
                 .filter(RiskScore.entity_id == "campus",
                         RiskScore.created_at >= (now - timedelta(hours=cfg["hours"])).replace(tzinfo=None))
                 .order_by(RiskScore.created_at).all())
    pred_rows = (db.query(Prediction)
                 .filter(Prediction.metric == "occupancy",
                         Prediction.created_at >= (now - timedelta(hours=cfg["hours"])).replace(tzinfo=None))
                 .order_by(Prediction.created_at).all())

    occupancy_series, energy_series, temperature_series, risk_series = [], [], [], []
    incident_series, prediction_series = [], []

    # cache sensor readings for energy/temp within window (last 24h of persisted data)
    def _sensor_avg(sensor_prefix: str, at: datetime) -> float | None:
        return None  # replaced below by curve model for long ranges

    for i in range(count):
        ts = now - step * (count - 1 - i)
        hour = ts.hour + ts.minute / 60.0
        day_frac = (ts.weekday() + (ts.hour * 3600 + ts.minute * 60) / 86400.0) / 7.0
        weekend = 0.55 if ts.weekday() >= 5 else 1.0
        occ = 0.0
        energy = 0.0
        for b in state.buildings.values():
            prof = BUILDING_PROFILE.get(b.id, BUILDING_PROFILE["eng"])
            frac = occupancy_curve(hour, prof) * weekend
            occ += b.capacity * frac
            working = 1.0 if 7 <= hour <= 19 else 0.35
            energy += b.capacity * 0.055 * (0.35 + 0.75 * frac) * working
        temp = outdoor_temperature(hour) + 1.5 * math.sin(day_frac * 2 * math.pi)

        # risk: baseline plus simulation/incident influence
        base_risk = 18 + 8 * math.sin((hour - 4) / 24 * 2 * math.pi)
        for s in sims:
            created = _aware(s.created_at)
            if created is None:
                continue
            delta_h = abs((ts - created).total_seconds()) / 3600.0
            if delta_h < 6:
                base_risk += (s.peak_risk - 20) * math.exp(-delta_h * 1.2) * 0.5
        for inc in incidents:
            started = _aware(inc.started_at)
            if started is None:
                continue
            delta_h = abs((ts - started).total_seconds()) / 3600.0
            if delta_h < 8:
                base_risk += {"LOW": 4, "MEDIUM": 9, "HIGH": 16, "CRITICAL": 24}.get(inc.severity, 6) * math.exp(-delta_h)
        risk = max(0.0, min(100.0, base_risk))

        occupancy_series.append({"t": _iso(ts), "value": round(occ, 0),
                                 "pct": round(100 * occ / state.campus_capacity(), 1)})
        energy_series.append({"t": _iso(ts), "value": round(energy, 1)})
        temperature_series.append({"t": _iso(ts), "value": round(temp, 1)})
        risk_series.append({"t": _iso(ts), "value": round(risk, 1)})

        inc_count = len([x for x in incidents
                         if _aware(x.started_at) and _aware(x.started_at) <= ts
                         and (x.resolved_at is None or _aware(x.resolved_at) > ts)])
        incident_series.append({"t": _iso(ts), "value": inc_count})
        prediction_series.append({
            "t": _iso(ts), "actual": round(occ, 0),
            "predicted": round(occ * (1 + 0.04 * math.sin(hour)), 0),
        })

    # overlay live in-memory risk samples for short ranges
    if window.upper() in ("1H", "6H") and state.metric_history.get("risk"):
        for point in state.metric_history["risk"][-count:]:
            risk_series.append({"t": point["t"], "value": point["value"]})
        risk_series = risk_series[-count:]

    recovery = [{
        "name": f"{s.scenario[:6].upper()}·{(s.target_id or 'campus')[:6]}",
        "scenario": s.scenario,
        "recovery": round(s.recovery_time_s / 60.0, 1),
        "peak_risk": s.peak_risk,
        "people": s.people_affected,
    } for s in sorted(sims, key=lambda x: _aware(x.created_at) or now)[-12:]]

    severity_counts: dict[str, int] = {}
    for inc in incidents:
        severity_counts[inc.severity] = severity_counts.get(inc.severity, 0) + 1

    return {
        "range": window.upper(),
        "occupancy": occupancy_series,
        "energy": energy_series,
        "temperature": temperature_series,
        "risk": risk_series,
        "incidents": incident_series,
        "predictions": prediction_series,
        "recovery": recovery,
        "severity": [{"name": k, "value": v} for k, v in severity_counts.items()],
        "risk_samples": [{"t": r.created_at.isoformat(), "value": r.score} for r in risk_rows],
        "prediction_samples": [{"t": p.created_at.isoformat(), "predicted": p.predicted_value,
                                "actual": p.current_value, "confidence": p.confidence}
                               for p in pred_rows],
        "source": "simulated telemetry (diurnal model + persisted readings)",
    }
