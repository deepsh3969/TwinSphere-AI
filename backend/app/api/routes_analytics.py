"""Analytics time-series endpoints (Recharts-friendly payloads).

Phase 9 adds real server-side aggregation endpoints (`/api/analytics/*`) — see
`app.services.analytics_service`.  The legacy `/timeseries` endpoint below is
kept unchanged for backward compatibility with earlier phases.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ratelimit import limit
from app.core.security import require
from app.models.entities import Incident, SensorReading, Simulation
from app.services import analytics_service as analytics
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


# =====================================================================
# Phase 9 — command centre analytics (server-side aggregation, §9–§48)
# =====================================================================

def _window(range_: str, start: str | None, end: str | None) -> analytics.Window:
    return analytics.resolve_window(range_, start, end)


@router.get("/overview")
def analytics_overview(range: str = Query("24H"), start: str | None = Query(None),
                       end: str | None = Query(None),
                       principal: dict = Depends(require("read")),
                       db: Session = Depends(get_db)):
    """Dashboard KPI strip: value + status + trend + freshness per KPI (§17–§24)."""
    return analytics.overview(db, get_state(), _window(range, start, end))


@router.get("/risk")
def analytics_risk(range: str = Query("24H"), start: str | None = Query(None),
                   end: str | None = Query(None),
                   building_id: str | None = Query(None),
                   principal: dict = Depends(require("read")),
                   db: Session = Depends(get_db)):
    window = _window(range, start, end)
    return analytics.risk_analytics(db, get_state(), window, building_id=building_id)


@router.get("/occupancy")
def analytics_occupancy(range: str = Query("24H"), start: str | None = Query(None),
                        end: str | None = Query(None),
                        building_id: str | None = Query(None),
                        principal: dict = Depends(require("read")),
                        db: Session = Depends(get_db)):
    window = _window(range, start, end)
    return analytics.occupancy_analytics(db, get_state(), window, building_id=building_id)


@router.get("/energy")
def analytics_energy(range: str = Query("24H"), start: str | None = Query(None),
                     end: str | None = Query(None),
                     building_id: str | None = Query(None),
                     principal: dict = Depends(require("read")),
                     db: Session = Depends(get_db)):
    window = _window(range, start, end)
    return analytics.energy_analytics(db, get_state(), window, building_id=building_id)


@router.get("/environment")
def analytics_environment(range: str = Query("24H"), start: str | None = Query(None),
                          end: str | None = Query(None),
                          building_id: str | None = Query(None),
                          principal: dict = Depends(require("read")),
                          db: Session = Depends(get_db)):
    window = _window(range, start, end)
    return analytics.environment_analytics(db, get_state(), window, building_id=building_id)


@router.get("/sensors")
def analytics_sensors(range: str = Query("24H"), start: str | None = Query(None),
                      end: str | None = Query(None),
                      principal: dict = Depends(require("read")),
                      db: Session = Depends(get_db)):
    """Sensor health totals + diagnostics list (§42)."""
    return analytics.sensor_health(db, get_state(), _window(range, start, end))


@router.get("/sensors/{sensor_id}")
def analytics_sensor_detail(sensor_id: str, range: str = Query("24H"),
                            start: str | None = Query(None), end: str | None = Query(None),
                            principal: dict = Depends(require("read")),
                            db: Session = Depends(get_db)):
    window = _window(range, start, end)
    out = analytics.sensor_detail(db, get_state(), sensor_id, window)
    if out is None:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return out


@router.get("/buildings")
def analytics_buildings(range: str = Query("24H"), start: str | None = Query(None),
                        end: str | None = Query(None),
                        principal: dict = Depends(require("read")),
                        db: Session = Depends(get_db)):
    return analytics.buildings_analytics(db, get_state(), _window(range, start, end))


@router.get("/buildings/compare")
def analytics_buildings_compare(ids: str = Query(..., description="comma-separated ids"),
                                range: str = Query("24H"), start: str | None = Query(None),
                                end: str | None = Query(None),
                                principal: dict = Depends(require("read")),
                                db: Session = Depends(get_db)):
    window = _window(range, start, end)
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    return analytics.buildings_compare(db, get_state(), id_list, window)


@router.get("/buildings/{building_id}")
def analytics_building_detail(building_id: str, range: str = Query("24H"),
                              start: str | None = Query(None), end: str | None = Query(None),
                              principal: dict = Depends(require("read")),
                              db: Session = Depends(get_db)):
    window = _window(range, start, end)
    out = analytics.building_detail(db, get_state(), building_id, window)
    if out is None:
        raise HTTPException(status_code=404, detail="Building not found")
    return out


@router.get("/routes")
def analytics_routes(range: str = Query("24H"), start: str | None = Query(None),
                     end: str | None = Query(None),
                     principal: dict = Depends(require("read")),
                     db: Session = Depends(get_db)):
    return analytics.routes_analytics(db, get_state(), _window(range, start, end))


@router.get("/ai")
def analytics_ai(range: str = Query("24H"), start: str | None = Query(None),
                 end: str | None = Query(None),
                 principal: dict = Depends(require("read")),
                 db: Session = Depends(get_db)):
    return analytics.ai_analytics(db, get_state(), _window(range, start, end))


@router.get("/system")
def analytics_system(principal: dict = Depends(require("read")),
                     db: Session = Depends(get_db)):
    """System-health strip: component statuses + updated_at (§43)."""
    return analytics.system_status(db, get_state())


@router.get("/health")
def analytics_health(range: str = Query("24H"), start: str | None = Query(None),
                     end: str | None = Query(None),
                     principal: dict = Depends(require("read")),
                     db: Session = Depends(get_db)):
    """Composite campus health score with transparent contributions (§46)."""
    return analytics.campus_health(db, get_state(), _window(range, start, end))


@router.get("/what-changed")
def analytics_what_changed(ago: int = Query(60, le=10080),
                           principal: dict = Depends(require("read")),
                           db: Session = Depends(get_db)):
    """NOW vs N-minutes-ago comparison (§44)."""
    return analytics.what_changed(db, get_state(), ago)


@router.get("/export")
def analytics_export(kind: str = Query("summary"),
                     range: str = Query("24H"), start: str | None = Query(None),
                     end: str | None = Query(None), format: str = Query("csv"),
                     _: None = Depends(limit("export")),
                     principal: dict = Depends(require("export")),
                     db: Session = Depends(get_db)):
    """CSV/JSON export of an analytics dataset (§33)."""
    kind = kind.lower()
    if kind not in analytics.EXPORT_KINDS:
        raise HTTPException(status_code=400,
                            detail=f"kind must be one of {', '.join(analytics.EXPORT_KINDS)}")
    window = _window(range, start, end)
    try:
        filename, media_type, body = analytics.export_dataset(db, get_state(), kind, window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if format == "json":
        import json as _json
        return Response(content=_json.dumps({"kind": kind, "window": window.as_dict(),
                                             "csv": body}, default=str),
                        media_type="application/json")
    return Response(content=body, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
