"""Batched persistence helpers for the runtime loop (keeps the loop fast)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.entities import (
    EvacuationRoute,
    Incident,
    OccupancyRecord,
    Prediction,
    Recommendation,
    RiskScore,
    SensorReading,
    Simulation,
    SystemAlert,
)
from app.services.state import TwinState


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def save_recommendation(rec: dict) -> None:
    with SessionLocal() as db:
        db.merge(Recommendation(
            id=rec["id"], title=rec["title"], priority=rec["priority"],
            entity_id=rec.get("entity_id"), action=rec["action"],
            rationale=rec.get("rationale", ""), status=rec.get("status", "PENDING"),
            payload=rec.get("payload", {}),
        ))
        db.commit()


def save_recommendation_update(rec: dict) -> None:
    with SessionLocal() as db:
        row = db.get(Recommendation, rec["id"])
        if row:
            row.status = rec["status"]
            if rec.get("applied_at"):
                row.applied_at = datetime.fromisoformat(rec["applied_at"])
            db.commit()


def resolve_incidents_for(sim_target: str | None, kinds: list[str] | None = None) -> None:
    with SessionLocal() as db:
        q = db.query(Incident).filter(Incident.status == "ACTIVE")
        if sim_target:
            q = q.filter(Incident.building_id == sim_target)
        for row in q.all():
            if kinds and row.kind not in kinds:
                continue
            row.status = "RESOLVED"
            row.resolved_at = _utc()
        db.commit()


def persist_readings(state: TwinState) -> None:
    now = _utc()
    with SessionLocal() as db:
        for s in state.sensors.values():
            db.add(SensorReading(sensor_id=s.id, value=round(s.value, 3), created_at=now))
        for b in state.buildings.values():
            db.add(OccupancyRecord(building_id=b.id, occupancy=b.occupancy,
                                   capacity_pct=round(100.0 * b.occupancy / max(1, b.capacity), 1),
                                   created_at=now))
        db.commit()


def persist_risk(state: TwinState) -> None:
    """Persist the Phase 5 stabilised (smoothed + hysteresis) risk history
    when available, falling back to the raw computation."""
    now = _utc()
    published = getattr(state, "risk_published", {}) or {}
    campus_pub = published.get("campus") or {}
    with SessionLocal() as db:
        db.add(RiskScore(entity_id="campus", entity_type="campus",
                         score=campus_pub.get("score", state.risk.get("score", 0)),
                         level=campus_pub.get("level", state.risk.get("level", "LOW")),
                         factors=campus_pub.get("factors", state.risk.get("factors", [])),
                         explanation=campus_pub.get("explanation", state.risk.get("explanation", "")),
                         created_at=now))
        for bid, r in state.building_risk.items():
            pub = published.get(bid) or {}
            db.add(RiskScore(entity_id=bid, entity_type="building",
                             score=pub.get("score", r["score"]),
                             level=pub.get("level", r["level"]),
                             factors=pub.get("factors", r["factors"]),
                             explanation=pub.get("explanation", r["explanation"]),
                             created_at=now))
        db.commit()


def persist_routes(state: TwinState) -> None:
    with SessionLocal() as db:
        for r in state.routes:
            db.merge(EvacuationRoute(
                id=r["id"], origin_id=r.get("origin_id", ""), exit_id=r.get("exit_id") or "",
                node_path=r.get("node_path", []), road_path=r.get("road_path", []),
                distance=r.get("distance", 0.0), eta_s=r.get("evac_time_s", 0.0),
                risk=r.get("risk", 0.0), status=r.get("status", "SAFE"),
                reason=r.get("reason", ""), is_primary=r.get("building_id") == (state.active_sim.target_id if state.active_sim else None),
            ))
        db.commit()


def persist_predictions(state: TwinState) -> None:
    now = _utc()
    with SessionLocal() as db:
        for p in state.predictions:
            db.add(Prediction(entity_id=p.get("entity_id", ""), metric=p.get("metric", ""),
                              current_value=p.get("current_value", 0.0),
                              predicted_value=p.get("predicted_value", 0.0),
                              horizon_min=p.get("horizon_min", 20),
                              confidence=p.get("confidence", 0.0),
                              model_name=p.get("model_name", ""),
                              summary=p.get("summary", ""), created_at=now))
        db.commit()


def save_completed_simulation(state: TwinState, sim) -> None:
    with SessionLocal() as db:
        row = db.get(Simulation, sim.id)
        if row:
            row.status = sim.status
            row.peak_risk = sim.peak_risk
            row.people_affected = sim.max_people_at_risk or sim.people_at_risk
            row.recovery_time_s = sim.recover_t
            row.progress = 100.0
            row.current_step = row.total_steps
            row.ended_at = _utc()
            row.result = {
                "scenario": sim.scenario, "target_id": sim.target_id,
                "events": sim.events[-20:], "peak_risk": sim.peak_risk,
                "people_affected": sim.max_people_at_risk or sim.people_at_risk,
                "results": dict(sim.results) if sim.results else {},
            }
            db.commit()


def add_alert(level: str, title: str, message: str, entity: str | None) -> None:
    with SessionLocal() as db:
        db.add(SystemAlert(level=level, type="SYSTEM", severity=level,
                           title=title, message=message, entity_id=entity,
                           entity_type="building" if entity else None, is_active=True))
        db.commit()
