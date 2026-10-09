"""Phase 9 §9–§48 — command-centre analytics aggregation.

Every figure is computed server-side from persisted history (`risk_scores`,
`occupancy_records`, `sensor_readings`, `predictions`, `incidents`,
`route_events`, `ai_analyses`, `recommendations`) using SQL bucket
aggregation.  In-memory twin state supplies *current* values only and each
payload is labelled with `source` + `window` + `computed_at` so the UI can show
where a number came from (§68: nothing is invented — empty windows return
``available: false`` with a reason).

No simulation / risk / route / prediction / anomaly / AI logic is duplicated
here: engines stay the single source of truth; this module only *reads*.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.entities import (
    AiAnalysis,
    AiEvidence,
    AiRecommendation,
    Building,
    Incident,
    OccupancyRecord,
    Prediction,
    RiskScore,
    RouteEvent,
    Sensor,
    SensorReading,
    Simulation,
)
from app.services.state import TwinState, risk_level

# --------------------------------------------------------------------- window

RANGE_PRESETS: dict[str, dict[str, float]] = {
    "15M": {"minutes": 15, "bucket_s": 60},
    "1H": {"minutes": 60, "bucket_s": 60},
    "6H": {"minutes": 360, "bucket_s": 300},
    "24H": {"minutes": 1440, "bucket_s": 900},
    "7D": {"minutes": 10080, "bucket_s": 7200},
    "30D": {"minutes": 43200, "bucket_s": 28800},
}
MAX_POINTS = 500
MAX_CUSTOM_DAYS = 90


@dataclass
class Window:
    preset: str
    start: datetime          # naive UTC (matches stored rows)
    end: datetime            # naive UTC
    bucket_s: int
    custom: bool = False

    @property
    def span_s(self) -> float:
        return max(1.0, (self.end - self.start).total_seconds())

    @property
    def quarter_s(self) -> float:
        return self.span_s / 4.0

    def buckets(self) -> list[datetime]:
        out, ts = [], self.start
        while ts <= self.end and len(out) <= MAX_POINTS + 2:
            out.append(ts)
            ts = ts + timedelta(seconds=self.bucket_s)
        return out

    def as_dict(self) -> dict:
        return {
            "preset": self.preset,
            "from": _iso(self.start),
            "to": _iso(self.end),
            "bucket_s": self.bucket_s,
            "custom": self.custom,
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def resolve_window(range_key: str | None, start: str | None, end: str | None) -> Window:
    """Resolve preset + custom range into a validated Window (§11/§12)."""
    now = datetime.now(timezone.utc)
    key = (range_key or "").upper().strip()
    if key and key != "CUSTOM" and key in RANGE_PRESETS:
        cfg = RANGE_PRESETS[key]
        start_dt = now - timedelta(minutes=cfg["minutes"])
        return Window(preset=key, start=_naive(start_dt), end=_naive(now),
                      bucket_s=int(cfg["bucket_s"]))

    start_dt = _parse_iso(start) if start else None
    end_dt = _parse_iso(end) if end else None
    if key == "CUSTOM" or start_dt or end_dt:
        end_dt = end_dt or now
        start_dt = start_dt or (end_dt - timedelta(hours=24))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt <= start_dt:
            start_dt = end_dt - timedelta(hours=24)
        if end_dt - start_dt > timedelta(days=MAX_CUSTOM_DAYS):
            start_dt = end_dt - timedelta(days=MAX_CUSTOM_DAYS)
        if end_dt > now + timedelta(minutes=5):
            end_dt = now
        span_min = max(1.0, (end_dt - start_dt).total_seconds() / 60.0)
        # aim for ~150 points, snapped to sane step sizes
        target = max(60, int(span_min * 60 / 150))
        step = next((s for s in (60, 300, 900, 3600, 21600, 86400) if s >= target), 86400)
        return Window(preset="CUSTOM", start=_naive(start_dt), end=_naive(end_dt),
                      bucket_s=step, custom=True)

    cfg = RANGE_PRESETS["24H"]
    return Window(preset="24H", start=_naive(now - timedelta(minutes=cfg["minutes"])),
                  end=_naive(now), bucket_s=int(cfg["bucket_s"]))


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def meta(window: Window, source: str) -> dict:
    return {"window": window.as_dict(), "source": source,
            "computed_at": datetime.now(timezone.utc).isoformat()}


# ------------------------------------------------------------------- helpers

def _bucket_expr(model, bucket_s: int):
    """Time-bucket expression with TRUE integer division on SQLite.

    SQLAlchemy compiles ``a / b`` as ``a / (b + 0.0)`` on SQLite (float
    division), which would break epoch bucketing — so the bucket arithmetic is
    emitted as raw SQL via ``literal_column`` (bucket_s is an internal int).
    """
    from sqlalchemy import literal_column
    col = f"{model.__tablename__}.created_at"
    step = int(bucket_s)
    return literal_column(
        f"(CAST(strftime('%s', {col}) AS INTEGER) / {step}) * {step}")


def _dense(points: dict[int, dict], window: Window) -> list[dict]:
    """Order + forward-fill a bucket map into a chart-ready series."""
    out: list[dict] = []
    last: dict | None = None
    ts = window.start.replace(tzinfo=timezone.utc)
    end = window.end.replace(tzinfo=timezone.utc)
    while ts <= end and len(out) <= MAX_POINTS + 2:
        key = int(ts.timestamp()) // window.bucket_s * window.bucket_s
        row = points.get(key)
        if row is not None:
            row = dict(row)
            last = row
        elif last is not None:
            row = {**last, "carried": True}
        if row is not None:
            row.setdefault("t", _iso(ts))
            out.append(row)
        ts = ts + timedelta(seconds=window.bucket_s)
    return out


def _avg(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def trend(series: list[dict], key: str = "value") -> dict:
    """First-quarter vs last-quarter trend of a series (never colour-only)."""
    vals = [p.get(key) for p in series if p.get(key) is not None]
    if len(vals) < 4:
        return {"direction": "flat", "delta": 0.0, "delta_pct": 0.0,
                "label": "insufficient data", "available": False}
    k = max(1, len(vals) // 4)
    head = sum(vals[:k]) / k
    tail = sum(vals[-k:]) / k
    delta = tail - head
    pct = (100.0 * delta / abs(head)) if abs(head) > 1e-9 else (0.0 if delta == 0 else 100.0)
    if abs(pct) < 1.0:
        direction = "flat"
    else:
        direction = "up" if delta > 0 else "down"
    return {"direction": direction, "delta": round(delta, 2),
            "delta_pct": round(pct, 1), "available": True,
            "label": "last quarter vs first quarter of window"}


def _direction_word(v: float) -> str:
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def sensor_series(db: Session, window: Window, sensor_types: tuple[str, ...] = (),
                  building_id: str | None = None, zone_id: str | None = None,
                  reduce: str = "avg") -> list[dict]:
    """Two-level bucket series: per-(bucket,sensor) avg, then avg|sum."""
    be = _bucket_expr(SensorReading, window.bucket_s)
    q = (db.query(be.label("bucket"), SensorReading.sensor_id,
                  func.avg(SensorReading.value), func.count(SensorReading.id))
         .join(Sensor, Sensor.id == SensorReading.sensor_id)
         .filter(SensorReading.created_at >= window.start,
                 SensorReading.created_at <= window.end))
    if sensor_types:
        q = q.filter(Sensor.type.in_(sensor_types))
    if building_id:
        q = q.filter(Sensor.building_id == building_id)
    if zone_id:
        q = q.filter(Sensor.zone_id == zone_id)
    q = q.group_by(be, SensorReading.sensor_id)

    per_bucket: dict[int, list[float]] = {}
    for bucket, _sid, avg_v, _cnt in q.all():
        per_bucket.setdefault(int(bucket), []).append(float(avg_v or 0.0))

    points: dict[int, dict] = {}
    for bucket, vals in per_bucket.items():
        value = sum(vals) if reduce == "sum" else (sum(vals) / len(vals))
        points[bucket] = {"value": round(value, 2), "sensors": len(vals)}
    return _dense(points, window)


def occupancy_series(db: Session, window: Window,
                     building_id: str | None = None) -> list[dict]:
    """Per-(bucket,building) avg occupancy, reduced to campus sum or building."""
    be = _bucket_expr(OccupancyRecord, window.bucket_s)
    q = (db.query(be.label("bucket"), OccupancyRecord.building_id,
                  func.avg(OccupancyRecord.occupancy),
                  func.avg(OccupancyRecord.capacity_pct))
         .filter(OccupancyRecord.created_at >= window.start,
                 OccupancyRecord.created_at <= window.end))
    if building_id:
        q = q.filter(OccupancyRecord.building_id == building_id)
    q = q.group_by(be, OccupancyRecord.building_id)

    people: dict[int, dict[str, float]] = {}
    pct: dict[int, list[float]] = {}
    for bucket, bid, occ, cap in q.all():
        people.setdefault(int(bucket), {})[bid] = float(occ or 0.0)
        pct.setdefault(int(bucket), []).append(float(cap or 0.0))

    points: dict[int, dict] = {}
    for bucket, per_b in people.items():
        points[bucket] = {
            "value": round(sum(per_b.values()), 1),
            "pct": round(sum(pct.get(bucket, [])) / max(1, len(pct.get(bucket, []))), 1),
            "buildings": len(per_b),
        }
    return _dense(points, window)


def risk_series(db: Session, window: Window, entity_id: str = "campus") -> list[dict]:
    be = _bucket_expr(RiskScore, window.bucket_s)
    rows = (db.query(be.label("bucket"), func.avg(RiskScore.score), func.count(RiskScore.id))
            .filter(RiskScore.entity_id == entity_id,
                    RiskScore.created_at >= window.start,
                    RiskScore.created_at <= window.end)
            .group_by(be).all())
    points = {int(b): {"value": round(float(s or 0.0), 1), "samples": int(c)}
              for b, s, c in rows}
    return _dense(points, window)


RISK_BANDS = ("LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL")
RISK_KPI_STATUS = {"LOW": "GOOD", "MODERATE": "WARN", "ELEVATED": "WARN",
                   "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}


def _time_in_categories(series: list[dict], bucket_s: int) -> list[dict]:
    counts: dict[str, float] = {}
    for p in series:
        v = p.get("value")
        if v is None:
            continue
        band = risk_level(float(v))
        counts[band] = counts.get(band, 0.0) + bucket_s
    total = sum(counts.values()) or 1.0
    return [{"category": c, "seconds": round(counts.get(c, 0.0), 1),
             "pct": round(100.0 * counts.get(c, 0.0) / total, 1)} for c in RISK_BANDS]


def _reading_stats(db: Session, window: Window, sensor_types: tuple[str, ...],
                   building_id: str | None = None) -> dict:
    q = (db.query(func.avg(SensorReading.value), func.min(SensorReading.value),
                  func.max(SensorReading.value), func.count(SensorReading.id),
                  func.max(SensorReading.created_at))
         .join(Sensor, Sensor.id == SensorReading.sensor_id)
         .filter(SensorReading.created_at >= window.start,
                 SensorReading.created_at <= window.end))
    if sensor_types:
        q = q.filter(Sensor.type.in_(sensor_types))
    if building_id:
        q = q.filter(Sensor.building_id == building_id)
    avg_v, min_v, max_v, count, last_at = q.one()
    if not count:
        return {"available": False, "reason": "no readings in window"}
    return {"available": True, "avg": round(float(avg_v), 2),
            "min": round(float(min_v), 2), "max": round(float(max_v), 2),
            "samples": int(count), "last_at": _iso(last_at)}


def _incident_rows(db: Session, window: Window) -> list[Incident]:
    return (db.query(Incident)
            .filter(Incident.started_at <= window.end,
                    or_(Incident.resolved_at.is_(None), Incident.resolved_at >= window.start))
            .order_by(Incident.started_at.desc(), Incident.id).all())


def _iso_naive(dt: datetime | None) -> str | None:
    return _iso(dt) if dt else None


# ------------------------------------------------------------------- overview

def overview(db: Session, state: TwinState, window: Window) -> dict:
    """Dashboard KPI strip (§17–§24): current value + trend + freshness."""
    occ = occupancy_series(db, window)
    energy = sensor_series(db, window, ("energy",), reduce="sum")
    risk = risk_series(db, window)
    incidents = _incident_rows(db, window)

    active_now = [i for i in db.query(Incident).filter(Incident.status == "ACTIVE")]
    active_at_start = [i for i in incidents
                       if i.started_at <= window.start
                       and (i.resolved_at is None or i.resolved_at > window.start)]
    active_now_ids = {i.id for i in active_now}
    new_in_window = [i for i in incidents if i.started_at > window.start]
    resolved_in_window = [i for i in incidents
                          if i.resolved_at and window.start <= i.resolved_at <= window.end]

    sensors_total = len(state.sensors)
    sensors_online = sum(1 for s in state.sensors.values() if s.healthy)
    sensor_pct = round(100.0 * sensors_online / max(1, sensors_total), 1)
    acc = prediction_accuracy(db, window)
    last_pred_at = db.query(func.max(Prediction.created_at)).filter(
        Prediction.created_at >= window.start, Prediction.created_at <= window.end).scalar()

    metrics_now = state.metrics()
    occ_series_trend = trend(occ, "value")
    energy_trend = trend(energy, "value")
    risk_trend = trend(risk, "value")

    occ_latest = occ[-1]["value"] if occ else state.campus_occupancy()
    energy_latest = energy[-1]["value"] if energy else state.campus_energy()
    risk_latest = risk[-1]["value"] if risk else metrics_now["risk"]
    occ_pct = occ[-1].get("pct") if occ else metrics_now["occupancy_pct"]

    def _occ_status(p: float | None) -> str:
        if p is None:
            return "UNKNOWN"
        return "GOOD" if p <= 75 else ("WARN" if p <= 90 else "CRITICAL")

    risk_lvl = risk_level(float(risk_latest))
    inc_count = len(active_now)
    inc_start_count = len(active_at_start)

    kpis = [
        {
            "id": "occupancy", "label": "Campus occupancy", "value": round(occ_latest, 0),
            "unit": "people", "secondary": f"{occ_pct}%" if occ_pct is not None else None,
            "status": _occ_status(occ_pct), "trend": occ_series_trend,
            "updated_at": _latest_ts(occ), "detail": "persisted occupancy records",
        },
        {
            "id": "energy", "label": "Energy draw", "value": round(energy_latest, 1),
            "unit": "kW", "secondary": None,
            "status": "GOOD" if energy_trend["available"] and energy_trend["delta_pct"] < 20 else "WARN",
            "trend": energy_trend, "updated_at": _latest_ts(energy),
            "detail": "sum of energy sensors",
        },
        {
            "id": "risk", "label": "Campus risk", "value": round(float(risk_latest), 1),
            "unit": "score", "secondary": risk_lvl,
            "status": RISK_KPI_STATUS.get(risk_lvl, "UNKNOWN"),
            "trend": risk_trend, "updated_at": _latest_ts(risk),
            "detail": "persisted risk scores (campus entity)",
        },
        {
            "id": "incidents", "label": "Active incidents", "value": inc_count,
            "unit": "open", "secondary": f"+{len(new_in_window)} in window",
            "status": "GOOD" if inc_count == 0 else ("WARN" if inc_count <= 2 else "CRITICAL"),
            "trend": {"direction": _direction_word(inc_count - inc_start_count),
                      "delta": inc_count - inc_start_count, "delta_pct": 0.0,
                      "label": "active now vs window start", "available": True},
            "updated_at": _iso_naive(max((i.updated_at for i in incidents), default=None)),
            "detail": f"{len(resolved_in_window)} resolved in window",
        },
        {
            "id": "predictions", "label": "Prediction accuracy", "value": acc.get("accuracy"),
            "unit": "%", "secondary": f"{acc.get('samples', 0)} checked",
            "status": ("GOOD" if (acc.get("accuracy") or 0) >= 85
                       else "WARN" if (acc.get("accuracy") or 0) >= 70 else "LOW"),
            "trend": {"direction": "flat", "delta": 0.0, "delta_pct": 0.0,
                      "label": "model hit-rate in window", "available": acc.get("available", False)},
            "updated_at": _iso(last_pred_at),
            "detail": acc.get("reason", "predicted vs actual (persisted)"),
        },
        {
            "id": "sensors", "label": "Sensor health", "value": sensor_pct,
            "unit": "%", "secondary": f"{sensors_online}/{sensors_total} online",
            "status": "GOOD" if sensor_pct >= 95 else ("WARN" if sensor_pct >= 80 else "CRITICAL"),
            "trend": {"direction": "flat", "delta": 0.0, "delta_pct": 0.0,
                      "label": "live sensor heartbeat", "available": True},
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "detail": "live twin state",
        },
    ]

    return {
        "kpis": kpis,
        "counts": {
            "active_incidents": inc_count,
            "new_incidents": len(new_in_window),
            "resolved_incidents": len(resolved_in_window),
            "incident_ids_active": sorted(active_now_ids),
            "sensors_total": sensors_total,
            "sensors_online": sensors_online,
            "sensors_offline": sensors_total - sensors_online,
            "anomalies": len(state.anomalies),
            "recommendations_pending": len(state.recommendations),
            "simulations_total": db.query(func.count(Simulation.id)).scalar() or 0,
            "active_simulation": state.active_sim.id if state.active_sim else None,
        },
        "confidence": {"prediction_accuracy": acc.get("accuracy"),
                       "available": acc.get("available", False)},
        **meta(window, "persisted analytics tables + live twin state"),
    }


def _latest_ts(series: list[dict]) -> str | None:
    for p in reversed(series):
        if p.get("t"):
            return p["t"]
    return None


# ------------------------------------------------------- prediction accuracy

def prediction_accuracy(db: Session, window: Window, sample_limit: int = 400) -> dict:
    """Measured hit-rate: predicted value vs persisted actual at horizon (§61)."""
    preds = (db.query(Prediction)
             .filter(Prediction.created_at >= window.start,
                     Prediction.created_at <= window.end)
             .order_by(Prediction.created_at.desc()).limit(sample_limit).all())
    if not preds:
        return {"available": False, "reason": "no predictions persisted in window",
                "samples": 0}

    by_metric: dict[str, list[float]] = {"energy": [], "occupancy": []}
    for p in preds:
        if p.metric not in ("energy", "occupancy"):
            continue
        target = p.created_at + timedelta(minutes=p.horizon_min)
        actual = _actual_value(db, p.metric, p.entity_id, target)
        if actual is None or abs(actual) < 1e-6:
            continue
        err = abs(p.predicted_value - actual) / max(abs(actual), 1e-6)
        by_metric[p.metric].append(max(0.0, 1.0 - min(err, 1.0)) * 100.0)

    all_scores = [s for scores in by_metric.values() for s in scores]
    if not all_scores:
        return {"available": False,
                "reason": "no persisted actuals matched predictions in window",
                "samples": 0}
    result = {
        "available": True,
        "accuracy": round(sum(all_scores) / len(all_scores), 1),
        "samples": len(all_scores),
        "by_metric": {m: {"accuracy": round(sum(v) / len(v), 1), "samples": len(v)}
                      for m, v in by_metric.items() if v},
        "method": "1 - |predicted - actual| / |actual| over persisted rows at horizon",
        "source": "predictions vs sensor_readings/occupancy_records",
    }
    return result


def _actual_value(db: Session, metric: str, entity_id: str,
                  target: datetime, tolerance_min: int = 3) -> float | None:
    lo = target - timedelta(minutes=tolerance_min)
    hi = target + timedelta(minutes=tolerance_min)
    if metric == "energy":
        row = (db.query(func.avg(SensorReading.value))
               .join(Sensor, Sensor.id == SensorReading.sensor_id)
               .filter(Sensor.type == "energy", Sensor.building_id == entity_id,
                       SensorReading.created_at >= lo, SensorReading.created_at <= hi)
               .one())
        return float(row[0]) if row and row[0] is not None else None
    if metric == "occupancy":
        row = (db.query(func.avg(OccupancyRecord.occupancy))
               .filter(OccupancyRecord.building_id == entity_id,
                       OccupancyRecord.created_at >= lo, OccupancyRecord.created_at <= hi)
               .one())
        return float(row[0]) if row and row[0] is not None else None
    return None


# ---------------------------------------------------------------- risk panel

def risk_analytics(db: Session, state: TwinState, window: Window,
                   building_id: str | None = None) -> dict:
    entity = building_id or "campus"
    series = risk_series(db, window, entity)
    rows = (db.query(RiskScore)
            .filter(RiskScore.entity_id == entity,
                    RiskScore.created_at >= window.start,
                    RiskScore.created_at <= window.end)
            .all())
    if not rows:
        current = state.buildings[building_id].risk if (building_id and building_id in state.buildings) \
            else state.risk.get("score", 0.0)
        return {
            "entity": entity, "available": False,
            "reason": f"no persisted risk scores for {entity} in window",
            "current": round(float(current), 1),
            "level": risk_level(float(current)), "series": [],
            **meta(window, "risk_scores"),
        }

    scores = [r.score for r in rows]
    latest = rows[-1]
    active_inc = [i for i in state.incidents if i.get("status") == "ACTIVE"]
    critical_events = [
        {"id": i["id"], "title": i.get("title", ""), "severity": i.get("severity", ""),
         "started_at": i.get("started_at"), "building_id": i.get("building_id")}
        for i in active_inc if i.get("severity") in ("HIGH", "CRITICAL")
    ]
    db_high = [i for i in _incident_rows(db, window) if i.severity in ("HIGH", "CRITICAL")]
    for i in db_high[:20]:
        critical_events.append({"id": i.id, "title": i.title, "severity": i.severity,
                                "started_at": _iso_naive(i.started_at),
                                "building_id": i.building_id})

    # heatmap: building x bucket average risk (§15)
    heat_buckets = series[:: max(1, len(series) // 24)][:24]
    heatmap = []
    building_ids = [b for b in state.buildings][:8]
    for bid in building_ids:
        b_series = risk_series(db, window, bid)
        lookup = {p["t"]: p.get("value") for p in b_series}
        heatmap.append({
            "entity": bid, "name": state.buildings[bid].name,
            "cells": [{"t": h["t"], "value": lookup.get(h["t"])} for h in heat_buckets],
        })

    tr = trend(series)
    return {
        "entity": entity, "available": True,
        "current": round(float(latest.score), 1), "level": latest.level,
        "stats": {
            "avg": round(sum(scores) / len(scores), 1),
            "max": round(max(scores), 1), "min": round(min(scores), 1),
            "samples": len(scores),
        },
        "trend": tr,
        "time_in_category": _time_in_categories(series, window.bucket_s),
        "critical_events": critical_events[:30],
        "series": series,
        "heatmap": {"buckets": [h["t"] for h in heat_buckets], "rows": heatmap},
        "factors": latest.factors or [],
        "explanation": latest.explanation or "",
        **meta(window, "risk_scores"),
    }


# ---------------------------------------------------------------- occupancy

def occupancy_analytics(db: Session, state: TwinState, window: Window,
                        building_id: str | None = None) -> dict:
    series = occupancy_series(db, window, building_id)
    stats = {}
    if series:
        vals = [p["value"] for p in series if p.get("value") is not None]
        peak = max(series, key=lambda p: p.get("value") or 0)
        stats = {
            "avg": round(sum(vals) / len(vals), 1),
            "peak": round(max(vals), 1),
            "min": round(min(vals), 1),
            "peak_at": peak.get("t"),
            "samples": len(vals),
        }
    by_building = []
    for bid, b in state.buildings.items():
        if building_id and bid != building_id:
            continue
        rows = (db.query(func.avg(OccupancyRecord.occupancy), func.max(OccupancyRecord.occupancy),
                         func.max(OccupancyRecord.created_at))
                .filter(OccupancyRecord.building_id == bid,
                        OccupancyRecord.created_at >= window.start,
                        OccupancyRecord.created_at <= window.end).one())
        current = b.occupancy
        by_building.append({
            "id": bid, "name": b.name, "current": current, "capacity": b.capacity,
            "pct": round(100.0 * current / max(1, b.capacity), 1),
            "avg": round(float(rows[0]), 1) if rows[0] is not None else None,
            "peak": round(float(rows[1]), 1) if rows[1] is not None else None,
            "last_at": _iso_naive(rows[2]),
        })
    if not series:
        return {"available": False, "reason": "no occupancy records in window",
                "series": [], "by_building": by_building,
                **meta(window, "occupancy_records")}
    return {
        "available": True, "series": series, "stats": stats,
        "current": state.campus_occupancy() if not building_id else
        (state.buildings[building_id].occupancy if building_id in state.buildings else None),
        "capacity": state.campus_capacity() if not building_id else
        (state.buildings[building_id].capacity if building_id in state.buildings else None),
        "trend": trend(series),
        "by_building": by_building,
        "peak_hour": _iso(_naive(datetime.fromisoformat(stats["peak_at"]))
                          .replace(tzinfo=None)) if stats.get("peak_at") else None,
        **meta(window, "occupancy_records"),
    }


# ------------------------------------------------------------------ energy

def energy_analytics(db: Session, state: TwinState, window: Window,
                     building_id: str | None = None) -> dict:
    series = sensor_series(db, window, ("energy",), building_id=building_id, reduce="sum")
    stats = _reading_stats(db, window, ("energy",), building_id)
    abnormal_rows = _out_of_range(db, window, ("energy",), building_id)
    by_building = []
    for bid, b in state.buildings.items():
        if building_id and bid != building_id:
            continue
        st = _reading_stats(db, window, ("energy",), bid)
        by_building.append({"id": bid, "name": b.name, "current": round(b.energy, 1),
                            "avg": st.get("avg"), "max": st.get("max"),
                            "available": st.get("available", False)})
    live_anomalies = [a for a in state.anomalies
                      if str(a.get("metric", "")).lower() in ("energy", "power", "kw")]
    if not series:
        return {"available": False, "reason": "no energy readings in window",
                "series": [], "by_building": by_building,
                **meta(window, "sensor_readings")}
    return {
        "available": True, "series": series, "stats": stats,
        "current": round(state.campus_energy(), 1),
        "trend": trend(series),
        "abnormal": {"count": abnormal_rows, "available": True,
                     "definition": "readings outside sensor normal_min/normal_max"},
        "anomalies_live": [{"id": a.get("id"), "score": a.get("score"),
                            "sensor": a.get("sensor_id"), "status": a.get("status")}
                           for a in live_anomalies],
        "by_building": by_building,
        **meta(window, "sensor_readings"),
    }


def _out_of_range(db: Session, window: Window, sensor_types: tuple[str, ...],
                  building_id: str | None = None) -> int:
    q = (db.query(func.count(SensorReading.id))
         .join(Sensor, Sensor.id == SensorReading.sensor_id)
         .filter(SensorReading.created_at >= window.start,
                 SensorReading.created_at <= window.end,
                 Sensor.type.in_(sensor_types),
                 or_(SensorReading.value < Sensor.normal_min,
                     SensorReading.value > Sensor.normal_max)))
    if building_id:
        q = q.filter(Sensor.building_id == building_id)
    return int(q.scalar() or 0)


# ------------------------------------------------------------- environment

ENV_METRICS = {
    "temperature": ("temperature", "°C"),
    "humidity": ("humidity", "%"),
    "air_quality": ("air_quality", "AQI"),
    "smoke": ("smoke", "ppm"),
    "water": ("water", "L/min"),
}


def environment_analytics(db: Session, state: TwinState, window: Window,
                          building_id: str | None = None) -> dict:
    metrics = []
    for key, (stype, unit) in ENV_METRICS.items():
        series = sensor_series(db, window, (stype,), building_id=building_id)
        stats = _reading_stats(db, window, (stype,), building_id)
        abnormal = _out_of_range(db, window, (stype,), building_id)
        metrics.append({
            "metric": key, "unit": unit, "available": stats.get("available", False),
            "stats": stats, "series": series, "trend": trend(series),
            "abnormal_readings": abnormal,
            "reason": None if stats.get("available") else "no readings in window",
        })
    return {"metrics": metrics, "live_temperature": round(state.campus_temperature(), 1),
            **meta(window, "sensor_readings")}


# --------------------------------------------------------------- sensors

def sensor_health(db: Session, state: TwinState, window: Window) -> dict:
    now = datetime.now(timezone.utc)
    total = len(state.sensors)
    online = sum(1 for s in state.sensors.values() if s.healthy)
    diagnostics: list[dict] = []
    stale_cutoff = now - timedelta(minutes=15)

    last_readings: dict[str, datetime] = {}
    for sid, ts in db.query(SensorReading.sensor_id, func.max(SensorReading.created_at)).group_by(
            SensorReading.sensor_id).all():
        last_readings[sid] = _aware(ts) or now

    out_of_range = _out_of_range(db, window, tuple(ENV_METRICS) + ("energy", "occupancy",
                                                                   "traffic", "parking"))
    for sid, s in sorted(state.sensors.items()):
        issues: list[str] = []
        last_at = last_readings.get(sid)
        age_s = (now - last_at).total_seconds() if last_at else None
        if not s.healthy:
            issues.append("sensor marked unhealthy by live engine")
        if age_s is None:
            issues.append("no persisted readings")
        elif last_at < stale_cutoff:
            issues.append(f"stale reading ({int(age_s // 60)}m old)")
        db_row_status = "ONLINE"
        row = db.get(Sensor, sid)
        if row is not None:
            db_row_status = row.status
            if row.status not in ("ONLINE",):
                issues.append(f"db status {row.status}")
            if row.normal_min is not None and s.value < row.normal_min:
                issues.append(f"value {s.value:.1f} below normal min {row.normal_min}")
            if row.normal_max is not None and s.value > row.normal_max:
                issues.append(f"value {s.value:.1f} above normal max {row.normal_max}")
        if issues:
            diagnostics.append({
                "sensor_id": sid, "name": s.name, "type": s.type,
                "building_id": s.building_id, "zone_id": s.zone_id,
                "sensor_code": s.sensor_code, "value": round(s.value, 2),
                "unit": s.unit, "status": s.status, "db_status": db_row_status,
                "last_reading_at": _iso(last_at), "age_seconds": round(age_s, 1) if age_s else None,
                "issues": issues,
            })

    by_type: dict[str, dict] = {}
    for s in state.sensors.values():
        d = by_type.setdefault(s.type, {"type": s.type, "total": 0, "healthy": 0})
        d["total"] += 1
        d["healthy"] += 1 if s.healthy else 0
    for d in by_type.values():
        d["health_pct"] = round(100.0 * d["healthy"] / max(1, d["total"]), 1)

    pct = round(100.0 * online / max(1, total), 1)
    return {
        "totals": {"total": total, "online": online, "offline": total - online,
                   "health_pct": pct, "out_of_range_readings": out_of_range,
                   "diagnostics": len(diagnostics)},
        "status": "HEALTHY" if pct >= 95 else ("DEGRADED" if pct >= 80 else "UNHEALTHY"),
        "by_type": sorted(by_type.values(), key=lambda d: d["type"]),
        "diagnostics": diagnostics[:100],
        "ai_status": state.sensor_ai_status,
        **meta(window, "live twin state + sensor_readings"),
    }


def sensor_detail(db: Session, state: TwinState, sensor_id: str, window: Window) -> dict | None:
    row = db.get(Sensor, sensor_id)
    live = state.sensors.get(sensor_id)
    if row is None and live is None:
        return None
    be = _bucket_expr(SensorReading, window.bucket_s)
    rows = (db.query(be, func.avg(SensorReading.value), func.min(SensorReading.value),
                     func.max(SensorReading.value), func.count(SensorReading.id))
            .filter(SensorReading.sensor_id == sensor_id,
                    SensorReading.created_at >= window.start,
                    SensorReading.created_at <= window.end)
            .group_by(be).all())
    points = {int(b): {"value": round(float(a or 0), 2), "min": round(float(mn or 0), 2),
                       "max": round(float(mx or 0), 2), "samples": int(c)}
              for b, a, mn, mx, c in rows}
    series = _dense(points, window)
    all_stats = {"available": bool(series)}
    if series:
        vals = [p["value"] for p in series]
        all_stats = {"available": True, "avg": round(sum(vals) / len(vals), 2),
                     "min": round(min(vals), 2), "max": round(max(vals), 2),
                     "samples": len(vals)}
    return {
        "sensor": {"id": row.id if row else sensor_id,
                   "sensor_code": row.sensor_code if row else (live.sensor_code if live else ""),
                   "name": row.name if row else (live.name if live else ""),
                   "type": row.type if row else (live.type if live else ""),
                   "building_id": row.building_id if row else (live.building_id if live else None),
                   "zone_id": row.zone_id if row else (live.zone_id if live else None),
                   "unit": row.unit if row else (live.unit if live else ""),
                   "normal_min": row.normal_min if row else (live.normal_min if live else None),
                   "normal_max": row.normal_max if row else (live.normal_max if live else None)},
        "status": live.status if live else (row.status if row else "UNKNOWN"),
        "healthy": live.healthy if live else True,
        "current": round(live.value, 2) if live else None,
        "series": series, "stats": all_stats,
        "trend": trend(series),
        **meta(window, "sensor_readings"),
    }


# -------------------------------------------------------------- buildings

def buildings_analytics(db: Session, state: TwinState, window: Window) -> dict:
    items = []
    for bid, b in sorted(state.buildings.items()):
        risk_s = risk_series(db, window, bid)
        occ_s = occupancy_series(db, window, bid)
        energy_stats = _reading_stats(db, window, ("energy",), bid)
        inc_count = (db.query(func.count(Incident.id))
                     .filter(Incident.building_id == bid,
                             Incident.started_at >= window.start,
                             Incident.started_at <= window.end).scalar() or 0)
        sensors = [s for s in state.sensors.values() if s.building_id == bid]
        healthy = sum(1 for s in sensors if s.healthy)
        occ_now = b.occupancy
        items.append({
            "id": bid, "name": b.name, "code": b.code, "type": b.type, "status": b.status,
            "risk": round(b.risk, 1), "risk_level": b.risk_level,
            "risk_avg": round(sum(p["value"] for p in risk_s) / len(risk_s), 1) if risk_s else None,
            "risk_trend": trend(risk_s),
            "occupancy": occ_now, "capacity": b.capacity,
            "occupancy_pct": round(100.0 * occ_now / max(1, b.capacity), 1),
            "occupancy_avg": round(sum(p["value"] for p in occ_s) / len(occ_s), 1) if occ_s else None,
            "energy": round(b.energy, 1), "energy_avg": energy_stats.get("avg"),
            "temperature": round(b.temperature, 1),
            "incidents": int(inc_count),
            "sensors": len(sensors), "sensor_health": round(100.0 * healthy / max(1, len(sensors)), 1),
        })
    return {"buildings": items, "count": len(items), **meta(window, "twin state + persisted series")}


def building_detail(db: Session, state: TwinState, building_id: str,
                    window: Window) -> dict | None:
    if building_id not in state.buildings:
        row = db.get(Building, building_id)
        if row is None:
            return None
    b = state.buildings.get(building_id)
    base = buildings_analytics(db, state, window)
    item = next((x for x in base["buildings"] if x["id"] == building_id), None)
    incs = (db.query(Incident)
            .filter(Incident.building_id == building_id,
                    Incident.started_at >= window.start, Incident.started_at <= window.end)
            .order_by(Incident.started_at.desc()).all())
    env = environment_analytics(db, state, window, building_id)
    occ_series = occupancy_series(db, window, building_id)
    sensors = [{"id": s.id, "name": s.name, "type": s.type, "status": s.status,
                "healthy": s.healthy, "value": round(s.value, 2), "unit": s.unit,
                "zone_id": s.zone_id}
               for s in state.sensors.values() if s.building_id == building_id]
    return {
        "building": item, "risk": risk_analytics(db, state, window, building_id),
        "occupancy": {"series": occ_series, "trend": trend(occ_series)},
        "environment": env["metrics"],
        "incidents": [{"id": i.id, "code": i.incident_code, "title": i.title, "kind": i.kind,
                       "severity": i.severity, "status": i.status,
                       "started_at": _iso_naive(i.started_at),
                       "resolved_at": _iso_naive(i.resolved_at)} for i in incs],
        "sensors": sensors,
        **meta(window, "twin state + persisted series"),
    }


def buildings_compare(db: Session, state: TwinState, ids: list[str],
                      window: Window) -> dict:
    ids = [i for i in ids if i in state.buildings][:6]
    if len(ids) < 2:
        return {"available": False, "reason": "need at least 2 valid building ids",
                "rows": [], "buildings": []}
    detail = buildings_analytics(db, state, window)
    items = {x["id"]: x for x in detail["buildings"] if x["id"] in ids}

    def _norm(values: dict[str, float | None]) -> dict[str, dict]:
        present = [v for v in values.values() if v is not None]
        hi = max(present) if present else 0
        lo = min(present) if present else 0
        out = {}
        for k, v in values.items():
            if v is None:
                out[k] = {"raw": None, "norm": None}
            elif hi == lo:
                out[k] = {"raw": v, "norm": 50.0}
            else:
                out[k] = {"raw": v, "norm": round(100.0 * (v - lo) / (hi - lo), 1)}
        return out

    metrics = [
        {"metric": "risk", "label": "Risk score", "unit": "score",
         "values": _norm({k: items[k]["risk"] for k in ids if k in items})},
        {"metric": "risk_avg", "label": "Avg risk (window)", "unit": "score",
         "values": _norm({k: items[k]["risk_avg"] for k in ids if k in items})},
        {"metric": "occupancy_pct", "label": "Occupancy", "unit": "%",
         "values": _norm({k: items[k]["occupancy_pct"] for k in ids if k in items})},
        {"metric": "energy", "label": "Energy draw", "unit": "kW",
         "values": _norm({k: items[k]["energy"] for k in ids if k in items})},
        {"metric": "temperature", "label": "Temperature", "unit": "°C",
         "values": _norm({k: items[k]["temperature"] for k in ids if k in items})},
        {"metric": "incidents", "label": "Incidents (window)", "unit": "count",
         "values": _norm({k: items[k]["incidents"] for k in ids if k in items})},
        {"metric": "sensor_health", "label": "Sensor health", "unit": "%",
         "values": _norm({k: items[k]["sensor_health"] for k in ids if k in items})},
    ]
    return {"available": True,
            "buildings": [{"id": k, "name": items[k]["name"]} for k in ids if k in items],
            "rows": metrics, "note": "norm = 0-100 min-max across selected buildings",
            **meta(window, "twin state + persisted series")}


# ----------------------------------------------------------------- routes

def routes_analytics(db: Session, state: TwinState, window: Window) -> dict:
    rows = (db.query(RouteEvent)
            .filter(RouteEvent.created_at >= window.start,
                    RouteEvent.created_at <= window.end)
            .order_by(RouteEvent.created_at).all())
    from collections import Counter
    by_event = Counter(r.event for r in rows)
    by_mode = Counter(r.mode for r in rows)

    be = _bucket_expr(RouteEvent, window.bucket_s)
    buckets = (db.query(be, func.count(RouteEvent.id), func.avg(RouteEvent.risk_score))
               .filter(RouteEvent.created_at >= window.start,
                       RouteEvent.created_at <= window.end)
               .group_by(be).all())
    series = _dense({int(b): {"value": int(c), "risk": round(float(r or 0), 1)}
                     for b, c, r in buckets}, window)

    intervals = []
    for a, b in zip(rows, rows[1:]):
        intervals.append((b.created_at - a.created_at).total_seconds())
    avg_interval = round(sum(intervals) / len(intervals), 1) if intervals else None

    risk_vals = [r.risk_score for r in rows]
    recalc = by_event.get("recalculated", 0) + by_event.get("emergency_updated", 0)
    current_routes = state.routes or []
    return {
        "available": True,
        "stats": {
            "events": len(rows),
            "recalculations": recalc,
            "by_event": dict(by_event), "by_mode": dict(by_mode),
            "avg_distance": round(_avg(r.distance for r in rows) or 0.0, 1),
            "avg_eta_s": round(_avg(r.eta_s for r in rows) or 0.0, 1),
            "avg_risk_score": round(sum(risk_vals) / len(risk_vals), 1) if risk_vals else None,
            "avg_congestion": round(_avg(r.congestion_score for r in rows) or 0.0, 1),
            "avg_interval_s": avg_interval,
        },
        "trend": trend(series),
        "series": series,
        "current": {
            "active_routes": len(current_routes),
            "route_version": state.route_version,
            "mode": state.route_mode,
            "bottlenecks": list(state.bottleneck_ids),
            "evacuation_status": (state.evacuation or {}).get("status", "IDLE"),
            "in_memory_history": len(state.route_history),
        },
        **meta(window, "route_events + live route state"),
    }


# ------------------------------------------------------------------- AI

def ai_analytics(db: Session, state: TwinState, window: Window) -> dict:
    analyses = (db.query(AiAnalysis)
                .filter(AiAnalysis.created_at >= window.start,
                        AiAnalysis.created_at <= window.end)
                .order_by(AiAnalysis.created_at).all())
    ids = [a.id for a in analyses]
    recs = []
    if ids:
        recs = (db.query(AiRecommendation)
                .filter(AiRecommendation.created_at >= window.start,
                        AiRecommendation.created_at <= window.end)
                .all())
    evidence_count = 0
    if ids:
        evidence_count = db.query(func.count(AiEvidence.id)).filter(
            AiEvidence.analysis_id.in_(ids)).scalar() or 0

    from collections import Counter
    dec_total = sum(1 for r in recs if r.status in ("ACCEPTED", "DISMISSED"))
    dec_ok = sum(1 for r in recs if r.status == "ACCEPTED")

    be = _bucket_expr(AiAnalysis, window.bucket_s)
    buckets = (db.query(be, func.count(AiAnalysis.id))
               .filter(AiAnalysis.created_at >= window.start,
                       AiAnalysis.created_at <= window.end).group_by(be).all())
    series = _dense({int(b): {"value": int(c)} for b, c in buckets}, window)

    conf = [a.confidence for a in analyses]
    lat = [a.latency_ms for a in analyses]
    health = state.analyst_health
    return {
        "available": True,
        "stats": {
            "analyses": len(analyses),
            "by_mode": dict(Counter(a.mode for a in analyses)),
            "by_severity": dict(Counter(a.severity for a in analyses)),
            "by_priority": dict(Counter(a.priority for a in analyses)),
            "by_source": dict(Counter(a.source for a in analyses)),
            "avg_confidence": round(sum(conf) / len(conf), 3) if conf else None,
            "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
            "recommendations": len(recs),
            "recommendations_by_status": dict(Counter(r.status for r in recs)),
            "recommendations_by_priority": dict(Counter(r.priority for r in recs)),
            "decisions": dec_total,
            "acceptance_rate": round(100.0 * dec_ok / dec_total, 1) if dec_total else None,
            "evidence_items": evidence_count,
        },
        "trend": trend(series),
        "series": series,
        "engine": {
            "analyst": health,
            "ai": state.ai_health,
            "anomalies": len(state.anomalies),
            "predictions": len(state.predictions),
        },
        **meta(window, "ai_analyses/ai_recommendations/ai_evidence"),
    }


# ------------------------------------------------------------ system health

def system_status(db: Session, state: TwinState) -> dict:
    now = datetime.now(timezone.utc)
    components: list[dict] = []

    def _age(dt_naive: datetime | None) -> float | None:
        if dt_naive is None:
            return None
        return round((now - (_aware(dt_naive) or now)).total_seconds(), 1)

    try:
        from sqlalchemy import inspect as sa_inspect
        tables = sa_inspect(db.connection()).get_table_names()
    except Exception:
        tables = []
    components.append({"id": "api", "name": "API", "status": "ONLINE",
                       "message": "FastAPI service responding", "updated_at": now.isoformat()})
    components.append({"id": "database", "name": "Database", "status": "ONLINE" if tables else "DEGRADED",
                       "message": f"{len(tables)} tables" if tables else "schema not readable",
                       "updated_at": now.isoformat()})

    from app.websocket.manager import manager
    from app.core.config import settings
    ws_ok = bool(getattr(settings, "WEBSOCKET_ENABLED", True))
    components.append({"id": "websocket", "name": "WebSocket", "status": "ONLINE" if ws_ok else "OFFLINE",
                       "message": f"{manager.connected} client(s) connected" if ws_ok else "disabled",
                       "updated_at": now.isoformat()})

    sim_status = "ONLINE" if state.sim_status == "RUNNING" else "DEGRADED"
    components.append({"id": "simulation", "name": "Simulation engine", "status": sim_status,
                       "message": f"active sim {state.active_sim.id}" if state.active_sim else "idle",
                       "updated_at": now.isoformat()})

    last_analysis = db.query(func.max(AiAnalysis.created_at)).scalar()
    analyst_stale = (_age(last_analysis) or 0) > 900
    ai_health = state.ai_health
    ai_status = "DEGRADED" if (analyst_stale or not ai_health.get("ok", True)) else "ONLINE"
    components.append({"id": "ai", "name": "AI engine", "status": ai_status,
                       "message": "analyst + anomaly engines nominal" if ai_status == "ONLINE"
                       else "analyst stale or degraded",
                       "updated_at": _iso(last_analysis)})

    last_risk = db.query(func.max(RiskScore.created_at)).scalar()
    risk_status = "DEGRADED" if (_age(last_risk) or 0) > 600 else "ONLINE"
    components.append({"id": "risk", "name": "Risk engine", "status": risk_status,
                       "message": f"last score {int((_age(last_risk) or 0))}s ago",
                       "updated_at": _iso(last_risk)})

    last_route = db.query(func.max(RouteEvent.created_at)).scalar()
    components.append({"id": "routes", "name": "Route engine",
                       "status": "ONLINE" if state.route_plan or state.routes else "DEGRADED",
                       "message": f"v{state.route_version} · mode {state.route_mode}",
                       "updated_at": _iso(last_route)})

    sensors_total = len(state.sensors)
    sensors_ok = sum(1 for s in state.sensors.values() if s.healthy)
    pct = 100.0 * sensors_ok / max(1, sensors_total)
    components.append({"id": "sensors", "name": "Sensor network",
                       "status": "ONLINE" if pct >= 95 else ("DEGRADED" if pct >= 80 else "OFFLINE"),
                       "message": f"{sensors_ok}/{sensors_total} healthy",
                       "updated_at": now.isoformat()})

    last_occ = db.query(func.max(OccupancyRecord.created_at)).scalar()
    occ_status = "DEGRADED" if (_age(last_occ) or 0) > 600 else "ONLINE"
    components.append({"id": "occupancy", "name": "Occupancy feed", "status": occ_status,
                       "message": "persisting" if occ_status == "ONLINE" else "stale feed",
                       "updated_at": _iso(last_occ)})

    return {"components": components,
            "summary": {"total": len(components),
                        "online": sum(1 for c in components if c["status"] == "ONLINE"),
                        "degraded": sum(1 for c in components if c["status"] == "DEGRADED"),
                        "offline": sum(1 for c in components if c["status"] == "OFFLINE")},
            "computed_at": now.isoformat()}


def campus_health(db: Session, state: TwinState, window: Window) -> dict:
    """Composite campus health score §46 (weighted, transparent contributions)."""
    risk_s = risk_series(db, window, "campus")
    occ_s = occupancy_series(db, window)
    sensors_total = len(state.sensors)
    sensors_ok = sum(1 for s in state.sensors.values() if s.healthy)
    active = [i for i in db.query(Incident).filter(Incident.status == "ACTIVE")]
    high_active = [i for i in active if i.severity in ("HIGH", "CRITICAL")]
    route_rows = (db.query(RouteEvent)
                  .filter(RouteEvent.created_at >= window.start,
                          RouteEvent.created_at <= window.end).all())
    acc = prediction_accuracy(db, window)

    risk_avg = sum(p["value"] for p in risk_s) / len(risk_s) if risk_s else None
    occ_pct = (occ_s[-1].get("pct") if occ_s else None)

    components = []

    def add(cid: str, label: str, weight: float, value: float | None, detail: str,
            inverse: bool = False):
        if value is None:
            score = 75.0
            note = "neutral (no data in window)"
        else:
            score = max(0.0, min(100.0, 100.0 - value if inverse else value))
            note = None
        components.append({"id": cid, "label": label, "weight": weight,
                           "value": round(value, 1) if value is not None else None,
                           "score": round(score, 1), "detail": detail, "note": note})

    add("risk", "Risk", 30.0, risk_avg, "avg campus risk score (inverse)", inverse=True)
    if occ_pct is None:
        add("occupancy", "Occupancy", 15.0, None, "campus occupancy pressure")
    else:
        pressure = occ_pct if occ_pct <= 85 else 85 + (occ_pct - 85) * 3
        add("occupancy", "Occupancy", 15.0, pressure, f"campus at {occ_pct}% capacity")
    add("sensors", "Sensors", 20.0, 100.0 * sensors_ok / max(1, sensors_total),
        f"{sensors_ok}/{sensors_total} healthy")
    inc_penalty = min(100.0, len(active) * 15.0 + len(high_active) * 10.0)
    add("incidents", "Incidents", 15.0, inc_penalty,
        f"{len(active)} active ({len(high_active)} high/critical)", inverse=True)
    route_risk = _avg(r.risk_score for r in route_rows)
    add("routes", "Routes", 10.0, route_risk, "avg route risk (inverse)", inverse=True)
    if acc.get("available"):
        add("predictions", "Predictions", 10.0, acc.get("accuracy"),
            f"{acc.get('samples')} samples verified")
    else:
        add("predictions", "Predictions", 10.0, None, "no verified samples in window")

    score = sum(c["score"] * c["weight"] for c in components) / max(
        1.0, sum(c["weight"] for c in components))
    level = "GOOD" if score >= 80 else ("FAIR" if score >= 60 else "POOR")
    return {"score": round(score, 1), "level": level, "components": components,
            "weights_total": sum(c["weight"] for c in components),
            **meta(window, "risk_scores/occupancy_records/incidents/route_events/state")}


# ------------------------------------------------------------ what changed

def what_changed(db: Session, state: TwinState, ago_minutes: int) -> dict:
    """NOW vs N-minutes-ago comparison across core metrics (§44)."""
    ago_minutes = max(1, min(10080, int(ago_minutes)))
    now = datetime.now(timezone.utc)
    cur_w = Window(preset="NOW", start=_naive(now - timedelta(minutes=15)), end=_naive(now),
                   bucket_s=60)
    prev_w = Window(preset="PREV", start=_naive(now - timedelta(minutes=15 + ago_minutes)),
                    end=_naive(now - timedelta(minutes=ago_minutes)), bucket_s=60)

    def _series_mean(fn, w: Window) -> float | None:
        s = fn(w)
        vals = [p["value"] for p in s if p.get("value") is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _count_incidents(w: Window) -> int:
        return db.query(func.count(Incident.id)).filter(
            Incident.status == "ACTIVE",
            Incident.started_at <= w.end).scalar() or 0

    def _count_route_events(w: Window) -> int:
        return db.query(func.count(RouteEvent.id)).filter(
            RouteEvent.created_at >= w.start, RouteEvent.created_at <= w.end).scalar() or 0

    def _count_analyses(w: Window) -> int:
        return db.query(func.count(AiAnalysis.id)).filter(
            AiAnalysis.created_at >= w.start, AiAnalysis.created_at <= w.end).scalar() or 0

    def _count_preds(w: Window) -> int:
        return db.query(func.count(Prediction.id)).filter(
            Prediction.created_at >= w.start, Prediction.created_at <= w.end).scalar() or 0

    def _count_route_recalcs(w: Window) -> int:
        return db.query(func.count(RouteEvent.id)).filter(
            RouteEvent.created_at >= w.start, RouteEvent.created_at <= w.end,
            RouteEvent.event.in_(("recalculated", "emergency_updated"))).scalar() or 0

    specs = [
        ("risk", "Campus risk", "score", lambda w: _series_mean(
            lambda ww: risk_series(db, ww, "campus"), w), "worse_when_up", 1),
        ("occupancy", "Occupancy", "people", lambda w: _series_mean(
            lambda ww: occupancy_series(db, ww), w), "neutral", 1),
        ("energy", "Energy draw", "kW", lambda w: _series_mean(
            lambda ww: sensor_series(db, ww, ("energy",), reduce="sum"), w), "worse_when_up", 1),
        ("active_incidents", "Active incidents", "count", _count_incidents, "worse_when_up", 0),
        ("route_recalculations", "Route recalculations", "count", _count_route_recalcs,
         "info", 0),
        ("ai_analyses", "AI analyses", "count", _count_analyses, "info", 0),
        ("predictions", "Predictions issued", "count", _count_preds, "info", 0),
        ("route_events", "Route events", "count", _count_route_events, "info", 0),
    ]

    rows = []
    improved = worsened = unchanged = 0
    for mid, label, unit, fn, sense, digits in specs:
        current = fn(cur_w)
        previous = fn(prev_w)
        if current is None or previous is None:
            rows.append({"metric": mid, "label": label, "unit": unit,
                         "previous": previous, "current": current, "delta": None,
                         "delta_pct": None, "direction": "flat", "change": "same",
                         "impact": "info", "available": False})
            continue
        delta = round(current - previous, digits)
        pct = (round(100.0 * delta / abs(previous), 1) if abs(previous) > 1e-9 else
               (0.0 if delta == 0 else 100.0))
        change = "same" if abs(delta) < 1e-9 else ("up" if delta > 0 else "down")
        if change == "same":
            impact = "same"
            unchanged += 1
        elif sense == "worse_when_up":
            impact = "worse" if change == "up" else "better"
            worsened += impact == "worse"
            improved += impact == "better"
        else:
            impact = "info"
        rows.append({"metric": mid, "label": label, "unit": unit,
                     "previous": previous, "current": current, "delta": delta,
                     "delta_pct": pct, "direction": change, "change": change,
                     "impact": impact, "available": True})

    headline_bits = [f"{r['label']} {r['change']} {abs(r['delta'])} {r['unit']}"
                     for r in rows if r["available"] and r["change"] != "same"][:3]
    return {
        "ago_minutes": ago_minutes,
        "rows": rows,
        "summary": {"improved": improved, "worsened": worsened, "unchanged": unchanged,
                    "headline": ", ".join(headline_bits) if headline_bits else "no material change"},
        "note": f"current = last 15 min, previous = same span {ago_minutes} min earlier",
        "computed_at": now.isoformat(),
    }


# ------------------------------------------------------------------- CSV

def rows_to_csv(headers: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def export_dataset(db: Session, state: TwinState, kind: str, window: Window) -> tuple[str, str, str]:
    """Return (filename, media_type, body) for CSV export (§33)."""
    kind = (kind or "").lower()
    if kind == "risk":
        rows = (db.query(RiskScore)
                .filter(RiskScore.created_at >= window.start,
                        RiskScore.created_at <= window.end)
                .order_by(RiskScore.created_at).all())
        return ("risk.csv", "text/csv", rows_to_csv(
            ["created_at", "entity_id", "entity_type", "score", "level"],
            [[_iso(r.created_at), r.entity_id, r.entity_type, r.score, r.level] for r in rows]))
    if kind == "occupancy":
        rows = (db.query(OccupancyRecord)
                .filter(OccupancyRecord.created_at >= window.start,
                        OccupancyRecord.created_at <= window.end)
                .order_by(OccupancyRecord.created_at).all())
        return ("occupancy.csv", "text/csv", rows_to_csv(
            ["created_at", "building_id", "occupancy", "capacity_pct"],
            [[_iso(r.created_at), r.building_id, r.occupancy, r.capacity_pct] for r in rows]))
    if kind == "energy":
        rows = (db.query(SensorReading.created_at, Sensor.sensor_code, Sensor.building_id,
                         SensorReading.value, SensorReading.quality)
                .join(Sensor, Sensor.id == SensorReading.sensor_id)
                .filter(Sensor.type == "energy",
                        SensorReading.created_at >= window.start,
                        SensorReading.created_at <= window.end)
                .order_by(SensorReading.created_at).all())
        return ("energy.csv", "text/csv", rows_to_csv(
            ["created_at", "sensor_code", "building_id", "kw", "quality"],
            [[_iso(r[0]), r[1], r[2], r[3], r[4]] for r in rows]))
    if kind == "incidents":
        rows = _incident_rows(db, window)
        return ("incidents.csv", "text/csv", rows_to_csv(
            ["id", "code", "title", "kind", "severity", "status", "building_id",
             "started_at", "resolved_at", "simulation_id", "risk_score"],
            [[r.id, r.incident_code, r.title, r.kind, r.severity, r.status, r.building_id,
              _iso(r.started_at), _iso(r.resolved_at), r.simulation_id, r.risk_score]
             for r in rows]))
    if kind == "simulations":
        rows = (db.query(Simulation)
                .filter(Simulation.created_at >= window.start,
                        Simulation.created_at <= window.end)
                .order_by(Simulation.created_at.desc()).all())
        return ("simulations.csv", "text/csv", rows_to_csv(
            ["id", "code", "scenario", "target_id", "status", "severity", "peak_risk",
             "people_affected", "recovery_time_s", "created_at", "ended_at"],
            [[r.id, r.simulation_code, r.scenario, r.target_id, r.status, r.severity,
              r.peak_risk, r.people_affected, r.recovery_time_s, _iso(r.created_at),
              _iso(r.ended_at)] for r in rows]))
    if kind == "sensor_health":
        health = sensor_health(db, state, window)
        return ("sensor_health.csv", "text/csv", rows_to_csv(
            ["sensor_id", "name", "type", "building_id", "status", "value", "unit",
             "last_reading_at", "issues"],
            [[d["sensor_id"], d["name"], d["type"], d["building_id"], d["status"],
              d["value"], d["unit"], d["last_reading_at"], "; ".join(d["issues"])]
             for d in health["diagnostics"]]))
    if kind == "buildings":
        data = buildings_analytics(db, state, window)
        return ("buildings.csv", "text/csv", rows_to_csv(
            ["id", "name", "risk", "risk_level", "occupancy", "capacity", "occupancy_pct",
             "energy_kw", "temperature_c", "incidents", "sensor_health_pct"],
            [[b["id"], b["name"], b["risk"], b["risk_level"], b["occupancy"], b["capacity"],
              b["occupancy_pct"], b["energy"], b["temperature"], b["incidents"],
              b["sensor_health"]] for b in data["buildings"]]))
    if kind == "routes":
        rows = (db.query(RouteEvent)
                .filter(RouteEvent.created_at >= window.start,
                        RouteEvent.created_at <= window.end)
                .order_by(RouteEvent.created_at).all())
        return ("routes.csv", "text/csv", rows_to_csv(
            ["created_at", "event", "origin", "destination", "mode", "distance_m",
             "eta_s", "risk_score", "congestion", "simulation_id"],
            [[_iso(r.created_at), r.event, r.origin, r.destination, r.mode, r.distance,
              r.eta_s, r.risk_score, r.congestion_score, r.simulation_id] for r in rows]))
    if kind == "summary":
        data = overview(db, state, window)
        return ("summary.csv", "text/csv", rows_to_csv(
            ["kpi", "label", "value", "unit", "status", "trend_direction",
             "trend_delta_pct", "updated_at"],
            [[k["id"], k["label"], k["value"], k["unit"], k["status"],
              k["trend"].get("direction"), k["trend"].get("delta_pct"), k["updated_at"]]
             for k in data["kpis"]]))
    raise ValueError(f"unknown export kind {kind!r}")


EXPORT_KINDS = ("risk", "occupancy", "energy", "incidents", "simulations",
                "sensor_health", "buildings", "routes", "summary")
