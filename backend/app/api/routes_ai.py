import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ai.anomaly import backend_name as anomaly_backend_name
from ai.anomaly import filtered as filter_anomalies
from app.core.audit import audit
from app.core.config import settings
from app.core.database import get_db
from app.core.security import require
from app.models.entities import AiRecommendation, Incident, SystemAlert
from app.schemas.common import (
    AnalyzeRequest,
    IncidentCreate,
    RecommendationDecision,
)
from app.services import ai_service, analyst_service
from app.services.actions import apply_recommendation
from app.services.state import get_state

router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/ai/anomalies")
def anomalies(
    severity: str | None = None,
    building_id: str | None = None,
    sensor_id: str | None = None,
    metric: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: dict = Depends(require("read"))):
    """Phase 5: filtered anomaly feed with per-sensor AI status."""
    state = get_state()
    result = ai_service.refresh_anomalies(state)
    rows = filter_anomalies(
        result["anomalies"], severity=severity, building_id=building_id,
        sensor_id=sensor_id, metric=metric, start=start, end=end, limit=limit)
    return {
        "anomalies": rows,
        "count": len(rows),
        "total": len(result["anomalies"]),
        "engine": anomaly_backend_name(),
        "sensor_status": result["sensor_status"],
        "data_quality": result["data_quality"],
        "score_threshold": settings.ANOMALY_SCORE_THRESHOLD,
        "min_samples": settings.ANOMALY_MIN_SAMPLES,
        "bands": {"NORMAL": [0, 20], "LOW": [21, 40], "MODERATE": [41, 60],
                  "HIGH": [61, 80], "CRITICAL": [81, 100]},
        "generated_at": result["generated_at"],
    }


@router.get("/ai/anomalies/{anomaly_id}")
def anomaly_detail(anomaly_id: str, principal: dict = Depends(require("read"))):
    state = get_state()
    ai_service.refresh_anomalies(state)
    row = next((a for a in state.anomalies if a["id"] == anomaly_id), None)
    if row is None:
        raise HTTPException(404, f"Anomaly not found: '{anomaly_id}'")
    return row


@router.get("/ai/predictions")
def predictions(
    horizon_min: int | None = None,
    entity_id: str | None = None,
    metric: str | None = None,
    limit: int = Query(100, ge=1, le=400),
    principal: dict = Depends(require("read"))):
    state = get_state()
    ai_service.refresh_predictions(state, horizon_min=horizon_min)
    rows = state.predictions
    if entity_id:
        rows = [p for p in rows if p.get("entity_id") == entity_id]
    if metric:
        rows = [p for p in rows if p.get("metric") == metric]
    rows = rows[:limit]
    return {
        "predictions": rows,
        "count": len(rows),
        "total": len(state.predictions),
        "horizons": list(settings.PREDICTION_HORIZONS),
        "engine": ai_service.prediction_backend(),
    }


@router.get("/ai/predictions/{entity_id}")
def predictions_for_entity(entity_id: str,
                           principal: dict = Depends(require("read"))):
    state = get_state()
    ai_service.refresh_predictions(state)
    known = (entity_id == "campus" or entity_id in state.buildings
             or entity_id in state.sensors)
    rows = [p for p in state.predictions if p.get("entity_id") == entity_id]
    if not known and not rows:
        raise HTTPException(404, f"Entity not found: '{entity_id}'")
    return {"entity_id": entity_id, "predictions": rows, "count": len(rows)}


@router.get("/ai/events")
def ai_events(limit: int = Query(40, ge=1, le=100),
              principal: dict = Depends(require("read"))):
    """Bounded AI event timeline (anomalies raised, risk level changes,
    data quality transitions, degraded/recovered system events)."""
    state = get_state()
    return {"events": state.ai_events[:limit], "count": min(limit, len(state.ai_events)),
            "ai_health": state.ai_health}


@router.get("/predictions")
def stored_predictions(principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    """Phase 2 endpoint: return stored predictions without heavy computation."""
    from app.models.entities import Prediction as PredictionRow

    state = get_state()
    if state.predictions:
        preds = []
        for p in state.predictions:
            entity_id = p.get("entity_id", "")
            entity_type = p.get("entity_type") or (
                "campus" if entity_id == "campus" else
                "sensor" if entity_id in state.sensors else
                "building" if entity_id in state.buildings else "unknown")
            preds.append({**p, "entity_type": entity_type,
                          "prediction_time": p.get("created_at")
                          or datetime.now(timezone.utc).isoformat()})
    else:
        rows = (db.query(PredictionRow)
                .order_by(PredictionRow.created_at.desc())
                .limit(50)
                .all())
        preds = [{
            "entity_id": r.entity_id, "entity_type": r.entity_type, "metric": r.metric,
            "current_value": r.current_value, "predicted_value": r.predicted_value,
            "horizon_min": r.horizon_min, "confidence": r.confidence,
            "model_name": r.model_name, "summary": r.summary,
            "prediction_time": r.created_at.isoformat(),
        } for r in rows]
    return {"predictions": preds, "count": len(preds), "data_source": "SIMULATED"}


@router.post("/ai/analyze")
async def analyze_endpoint(body: AnalyzeRequest,
                           principal: dict = Depends(require("analyze"))):
    """Phase 8 §49 — explicit analyst run. Always bypasses cache/cooldown;
    `mode` (or legacy `focus`) selects an analysis mode, `question` is
    answered from structured data only (§54)."""
    state = get_state()
    try:
        return await analyst_service.analyze_now(
            state, question=body.question, mode=body.mode or body.focus,
            force=True, trigger="api")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/ai/analyst")
async def analyst_latest(principal: dict = Depends(require("read"))):
    state = get_state()
    if not state.analyst:
        state.analyst = await ai_service.run_analyst(state)
    return state.analyst


@router.get("/ai/analysis")
def list_analyses(limit: int = Query(20, ge=1, le=100),
                  mode: str | None = None, severity: str | None = None,
                  principal: dict = Depends(require("read")),
                  db: Session = Depends(get_db)):
    """Phase 8 §57 — persisted analyst history (bounded, newest first)."""
    rows = analyst_service.list_analyses(db, limit=limit, mode=mode,
                                         severity=severity)
    return {"analyses": rows, "count": len(rows)}


@router.get("/ai/analysis/latest")
def latest_analysis(principal: dict = Depends(require("read")),
                    db: Session = Depends(get_db)):
    state = get_state()
    if state.analyst:
        return state.analyst
    rows = analyst_service.list_analyses(db, limit=1)
    if rows:
        return rows[0]
    raise HTTPException(404, "No analyst result has been produced yet")


@router.get("/ai/analysis/{analysis_id}")
def analysis_detail(analysis_id: str, principal: dict = Depends(require("read")),
                    db: Session = Depends(get_db)):
    payload = analyst_service.get_analysis(db, analysis_id)
    if payload is None:
        raise HTTPException(404, f"Analysis not found: '{analysis_id}'")
    return payload


@router.get("/ai/recommendations")
def analyst_recommendations(status: str | None = None,
                            analysis_id: str | None = None,
                            principal: dict = Depends(require("read")),
                            db: Session = Depends(get_db)):
    """Phase 8 §21/§24 — analyst recommendation cards with human decision state."""
    rows = analyst_service.list_recommendations(db, status=status,
                                                analysis_id=analysis_id)
    return {"recommendations": rows, "count": len(rows)}


@router.get("/ai/recommendations/{rec_id}")
def analyst_recommendation_detail(rec_id: str,
                                  principal: dict = Depends(require("read")),
                                  db: Session = Depends(get_db)):
    row = db.get(AiRecommendation, rec_id)
    if row is None:
        raise HTTPException(404, f"Analyst recommendation not found: '{rec_id}'")
    rows = analyst_service.list_recommendations(db, analysis_id=row.analysis_id)
    match = next((r for r in rows if r["recommendation_id"] == rec_id), None)
    if match is None:  # pragma: no cover - defensive
        raise HTTPException(404, f"Analyst recommendation not found: '{rec_id}'")
    return match


@router.post("/ai/recommendations/{rec_id}/decision")
def analyst_recommendation_decision(rec_id: str, body: RecommendationDecision,
                                    principal: dict = Depends(require("apply")),
                                    db: Session = Depends(get_db)):
    """Phase 8 §24 — human-in-the-loop: operators accept or dismiss; the
    Analyst never acts on its own."""
    try:
        outcome = analyst_service.decide_recommendation(
            db, rec_id, body.decision, principal.get("username", "?"))
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    audit(db, "analyst.recommendation.decision",
          actor=principal.get("username", "?"), entity=rec_id,
          detail=outcome["status"])
    return outcome


@router.get("/ai/evidence/{evidence_id}")
def evidence_detail(evidence_id: str, principal: dict = Depends(require("read")),
                    db: Session = Depends(get_db)):
    """Phase 8 §9 — one grounding evidence item behind an analysis."""
    payload = analyst_service.get_evidence(db, evidence_id)
    if payload is None:
        raise HTTPException(404, f"Evidence not found: '{evidence_id}'")
    return payload


@router.get("/ai/status")
def ai_engine_status(principal: dict = Depends(require("read"))):
    state = get_state()
    return {**ai_service.ai_status(state), "analyst": analyst_service.status(state)}


@router.get("/recommendations")
def list_recommendations(status: str | None = None, principal: dict = Depends(require("read"))):
    state = get_state()
    recs = state.recommendations
    if status:
        recs = [r for r in recs if r["status"] == status]
    return [{**r, "recommendation_id": r["id"], "reason": r.get("rationale", "")} for r in recs]


@router.post("/recommendations/{rec_id}/apply")
def apply(rec_id: str, principal: dict = Depends(require("apply")), db: Session = Depends(get_db)):
    state = get_state()
    try:
        rec = apply_recommendation(state, rec_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    audit(db, "recommendation.apply", actor=principal.get("username", "?"),
          entity=rec.get("entity_id") or "", detail=rec.get("title", ""))
    return rec


@router.get("/incidents")
def list_incidents(status: str | None = None, principal: dict = Depends(require("read")),
                   db: Session = Depends(get_db)):
    state = get_state()
    rows = state.incidents
    if status:
        rows = [i for i in rows if i["status"] == status]
    return rows


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, principal: dict = Depends(require("read")),
                 db: Session = Depends(get_db)):
    state = get_state()
    inc = next((i for i in state.incidents if i["id"] == incident_id), None)
    if inc:
        return inc
    row = db.get(Incident, incident_id)
    if not row:
        row = (db.query(Incident).filter(Incident.incident_code == incident_id.upper()).first())
    if not row:
        raise HTTPException(404, f"Incident not found: '{incident_id}'")
    return {
        "id": row.id, "incident_code": row.incident_code, "title": row.title,
        "kind": row.kind, "building_id": row.building_id,
        "location_type": row.location_type, "location_id": row.location_id,
        "severity": row.severity, "status": row.status, "description": row.description,
        "risk_score": row.risk_score, "started_at": row.started_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


@router.post("/incidents")
def create_incident(body: IncidentCreate, principal: dict = Depends(require("simulate")),
                    db: Session = Depends(get_db)):
    state = get_state()
    if body.building_id and body.building_id not in state.buildings:
        raise HTTPException(404, "Building not found")
    incident_code = f"INC-{uuid.uuid4().hex[:6].upper()}"
    inc = {
        "id": f"inc_{uuid.uuid4().hex[:8]}", "incident_code": incident_code,
        "title": body.title, "kind": body.kind,
        "building_id": body.building_id,
        "location_type": "BUILDING" if body.building_id else "CAMPUS",
        "location_id": body.building_id or "campus",
        "severity": body.severity, "status": "ACTIVE",
        "description": body.description, "risk_score": 0.0,
        "started_at": datetime.now(timezone.utc).isoformat(), "resolved_at": None,
        "source": "manual",
    }
    state.incidents.insert(0, inc)
    db.add(Incident(id=inc["id"], incident_code=incident_code, title=inc["title"],
                    kind=inc["kind"], building_id=inc["building_id"],
                    location_type=inc["location_type"], location_id=inc["location_id"],
                    severity=inc["severity"], status="ACTIVE", description=inc["description"]))
    db.commit()
    state.alerts.append({
        "id": f"alert_{len(state.alerts) + 1}", "level": body.severity,
        "severity": body.severity, "type": "MANUAL",
        "title": body.title, "message": body.description,
        "entity_id": body.building_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "acknowledged": False,
        "resolved_at": None,
    })
    db.commit()
    audit(db, "incident.create", actor=principal.get("username", "?"), entity=body.building_id or "",
          detail=body.title)
    return inc


@router.post("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, principal: dict = Depends(require("simulate")),
                     db: Session = Depends(get_db)):
    state = get_state()
    inc = next((i for i in state.incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    inc["status"] = "RESOLVED"
    inc["resolved_at"] = datetime.now(timezone.utc).isoformat()
    row = db.get(Incident, incident_id)
    if row:
        row.status = "RESOLVED"
        row.resolved_at = datetime.now(timezone.utc)
        db.commit()
    audit(db, "incident.resolve", actor=principal.get("username", "?"), entity=incident_id)
    return inc


@router.get("/alerts")
def list_alerts(principal: dict = Depends(require("read"))):
    rows = [{**a,
             "severity": a.get("severity") or a.get("level", "INFO"),
             "type": a.get("type", "SYSTEM"),
             "is_active": a.get("resolved_at") is None}
            for a in reversed(get_state().alerts[-20:])]
    return rows


@router.delete("/alerts")
def clear_alerts(principal: dict = Depends(require("simulate"))):
    state = get_state()
    state.alerts = []
    return {"status": "cleared"}
