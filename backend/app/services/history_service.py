"""Phase 9 §50–§56 — incident & simulation history, timelines, reports.

Reads persisted history only (incidents, simulations, simulation_events,
route_events, ai_analyses, risk_scores, recommendations) and merges it into
ordered timelines the UI can render directly.  Everything is labelled with its
source table so the provenance of each line stays auditable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.entities import (
    AiAnalysis,
    Incident,
    Recommendation,
    RiskScore,
    RouteEvent,
    Simulation,
    SimulationEvent,
)

# Event kind → timeline category (§25: SIMULATION/RISK/ROUTE/AI/RECOVERY/INCIDENT)
KIND_CATEGORY: dict[str, str] = {
    "created": "SIMULATION", "started": "SIMULATION", "paused": "SIMULATION",
    "resumed": "SIMULATION", "reset": "SIMULATION", "completed": "SIMULATION",
    "evacuation_started": "SIMULATION", "evacuation_completed": "SIMULATION",
    "ignition": "RISK", "smoke_detected": "RISK", "spread": "RISK",
    "risk_zone_expanding": "RISK", "zones_affected": "RISK", "peak": "RISK",
    "people_at_risk": "RISK", "power_lost": "RISK", "heat_wave": "RISK",
    "crowd_buildup": "RISK", "flood_detected": "RISK", "blocked": "RISK",
    "routes_recalculated": "ROUTE", "route_optimized": "ROUTE", "rerouted": "ROUTE",
    "road_closed": "ROUTE", "bottleneck_detected": "ROUTE",
    "response_recommended": "AI", "recommendation_generated": "AI",
    "recovering": "RECOVERY", "recovered": "RECOVERY", "stabilized": "RECOVERY",
    "recover": "RECOVERY", "system_normal": "RECOVERY",
    "incident_opened": "INCIDENT", "incident_resolved": "INCIDENT",
}


def category_for(kind: str) -> str:
    return KIND_CATEGORY.get(kind, "SIMULATION")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sim_window(db: Session, sim: Simulation) -> tuple[datetime | None, datetime | None]:
    first = (db.query(func.min(SimulationEvent.created_at))
             .filter(SimulationEvent.simulation_id == sim.id).scalar())
    last = (db.query(func.max(SimulationEvent.created_at))
            .filter(SimulationEvent.simulation_id == sim.id).scalar())
    start = _aware(first) or _aware(sim.started_at) or _aware(sim.created_at)
    end = _aware(last) or _aware(sim.ended_at)
    return start, end


# ----------------------------------------------------------------- incidents

def list_incidents(db: Session, *, status: str | None = None, severity: str | None = None,
                   kind: str | None = None, building_id: str | None = None,
                   simulation_id: str | None = None, search: str | None = None,
                   start: datetime | None = None, end: datetime | None = None,
                   sort: str = "started_at", order: str = "desc",
                   page: int = 1, page_size: int = 25) -> dict:
    q = db.query(Incident)
    if status and status.upper() != "ALL":
        q = q.filter(Incident.status == status.upper())
    if severity and severity.upper() != "ALL":
        q = q.filter(Incident.severity == severity.upper())
    if kind and kind.upper() != "ALL":
        q = q.filter(Incident.kind == kind.upper())
    if building_id:
        q = q.filter(Incident.building_id == building_id)
    if simulation_id:
        q = q.filter(Incident.simulation_id == simulation_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Incident.title.ilike(like), Incident.description.ilike(like),
                         Incident.incident_code.ilike(like), Incident.kind.ilike(like)))
    if start:
        q = q.filter(Incident.started_at >= start)
    if end:
        q = q.filter(Incident.started_at <= end)

    total = q.count()
    sort_col = {"started_at": Incident.started_at, "severity": Incident.severity,
                "status": Incident.status, "risk_score": Incident.risk_score,
                "resolved_at": Incident.resolved_at}.get(sort, Incident.started_at)
    q = q.order_by(sort_col.desc() if order != "asc" else sort_col.asc(), Incident.id)
    page = max(1, page)
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for r in rows:
        duration = None
        if r.resolved_at and r.started_at:
            duration = round((r.resolved_at - r.started_at).total_seconds(), 1)
        items.append({
            "id": r.id, "code": r.incident_code, "title": r.title, "kind": r.kind,
            "severity": r.severity, "status": r.status, "building_id": r.building_id,
            "location_type": r.location_type, "location_id": r.location_id,
            "risk_score": r.risk_score, "started_at": _iso(r.started_at),
            "resolved_at": _iso(r.resolved_at), "duration_s": duration,
            "simulation_id": r.simulation_id, "description": r.description,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "filters": {"status": status, "severity": severity, "kind": kind,
                        "building_id": building_id, "search": search},
            "source": "incidents", "generated_at": _now_iso()}


def _merged_timeline(db: Session, *, start: datetime | None, end: datetime | None,
                     simulation_id: str | None, incident: Incident | None = None) -> list[dict]:
    items: list[dict] = []
    if simulation_id:
        for e in (db.query(SimulationEvent)
                  .filter(SimulationEvent.simulation_id == simulation_id)
                  .order_by(SimulationEvent.t, SimulationEvent.id).all()):
            items.append({
                "id": f"sim_ev_{e.id}", "sim_t": round(e.t, 2), "t": _iso(e.created_at),
                "category": category_for(e.kind), "kind": e.kind, "title": e.message,
                "source": "simulation_events", "data": e.data or {},
            })
    if start and end:
        for r in (db.query(RouteEvent)
                  .filter(RouteEvent.created_at >= start, RouteEvent.created_at <= end)
                  .order_by(RouteEvent.created_at, RouteEvent.id).all()):
            if simulation_id and r.simulation_id and r.simulation_id != simulation_id:
                continue
            items.append({
                "id": f"route_{r.id}", "sim_t": None, "t": _iso(r.created_at),
                "category": "ROUTE", "kind": r.event,
                "title": f"Route {r.event.replace('_', ' ')}: {r.origin or '?'} → {r.destination or '?'}",
                "source": "route_events", "data": {"mode": r.mode, "distance": r.distance,
                                                   "eta_s": r.eta_s, "risk_score": r.risk_score},
            })
        for a in (db.query(AiAnalysis)
                  .filter(AiAnalysis.created_at >= start, AiAnalysis.created_at <= end)
                  .order_by(AiAnalysis.created_at, AiAnalysis.id).all()):
            if simulation_id and a.simulation_id and a.simulation_id != simulation_id:
                continue
            items.append({
                "id": f"ai_{a.id}", "sim_t": None, "t": _iso(a.created_at),
                "category": "AI", "kind": f"analysis_{a.mode.lower()}",
                "title": a.title, "source": "ai_analyses",
                "data": {"severity": a.severity, "confidence": a.confidence,
                         "summary": a.summary[:240]},
            })
    if incident is not None:
        items.append({"id": f"inc_{incident.id}", "sim_t": None, "t": _iso(incident.started_at),
                      "category": "INCIDENT", "kind": "incident_opened",
                      "title": f"Incident opened — {incident.title}",
                      "source": "incidents", "data": {"severity": incident.severity,
                                                      "code": incident.incident_code}})
        if incident.resolved_at:
            items.append({"id": f"inc_{incident.id}_res", "sim_t": None,
                          "t": _iso(incident.resolved_at), "category": "INCIDENT",
                          "kind": "incident_resolved", "title": "Incident resolved",
                          "source": "incidents", "data": {"code": incident.incident_code}})
        for rec in (db.query(Recommendation)
                    .filter(Recommendation.incident_id == incident.id)
                    .order_by(Recommendation.created_at).all()):
            items.append({
                "id": f"rec_{rec.id}", "sim_t": None, "t": _iso(rec.created_at),
                "category": "AI", "kind": "recommendation",
                "title": getattr(rec, "title", None) or "Recommendation",
                "source": "recommendations", "data": {"status": rec.status},
            })
    items.sort(key=lambda x: (x["t"] or "", x["source"], x["id"]))
    return items


def incident_detail(db: Session, incident_id: str) -> dict | None:
    inc = db.get(Incident, incident_id)
    if inc is None:
        return None
    start = _aware(inc.started_at)
    end = _aware(inc.resolved_at) or datetime.now(timezone.utc)
    sim = db.get(Simulation, inc.simulation_id) if inc.simulation_id else None

    entity = inc.building_id or "campus"
    risk_rows = (db.query(RiskScore)
                 .filter(RiskScore.entity_id == entity,
                         RiskScore.created_at >= inc.started_at,
                         RiskScore.created_at <= end)
                 .order_by(RiskScore.created_at).all())
    scores = [r.score for r in risk_rows]

    duration = None
    if inc.resolved_at and inc.started_at:
        duration = round((inc.resolved_at - inc.started_at).total_seconds(), 1)

    timeline = _merged_timeline(db, start=start, end=end,
                                simulation_id=inc.simulation_id, incident=inc)
    recs = (db.query(Recommendation).filter(Recommendation.incident_id == inc.id)
            .order_by(Recommendation.created_at).all())

    return {
        "incident": {
            "id": inc.id, "code": inc.incident_code, "title": inc.title, "kind": inc.kind,
            "severity": inc.severity, "status": inc.status, "building_id": inc.building_id,
            "location_type": inc.location_type, "location_id": inc.location_id,
            "description": inc.description, "risk_score": inc.risk_score,
            "started_at": _iso(inc.started_at), "resolved_at": _iso(inc.resolved_at),
            "updated_at": _iso(inc.updated_at), "duration_s": duration,
            "simulation_id": inc.simulation_id,
        },
        "simulation": ({"id": sim.id, "code": sim.simulation_code, "scenario": sim.scenario,
                        "status": sim.status, "peak_risk": sim.peak_risk,
                        "people_affected": sim.people_affected,
                        "recovery_time_s": sim.recovery_time_s} if sim else None),
        "metrics": {
            "duration_s": duration,
            "risk_entity": entity,
            "peak_risk": round(max(scores), 1) if scores else None,
            "avg_risk": round(sum(scores) / len(scores), 1) if scores else None,
            "risk_samples": len(scores),
            "people_affected": sim.people_affected if sim else None,
            "timeline_items": len(timeline),
            "recommendations": len(recs),
        },
        "timeline": timeline,
        "recommendations": [{"id": r.id, "title": getattr(r, "title", "") or "",
                             "status": r.status, "created_at": _iso(r.created_at)}
                            for r in recs],
        "source": "incidents + simulation_events/route_events/ai_analyses",
        "generated_at": _now_iso(),
    }


def incident_report(db: Session, incident_id: str) -> dict | None:
    detail = incident_detail(db, incident_id)
    if detail is None:
        return None
    inc = detail["incident"]
    timeline = detail["timeline"]
    categories: dict[str, int] = {}
    for item in timeline:
        categories[item["category"]] = categories.get(item["category"], 0) + 1

    factors = []
    entity = detail["metrics"]["risk_entity"]
    latest = (db.query(RiskScore)
              .filter(RiskScore.entity_id == entity,
                      RiskScore.created_at >= datetime.fromisoformat(inc["started_at"])
                      .astimezone(timezone.utc).replace(tzinfo=None))
              .order_by(RiskScore.created_at).first())
    if latest is not None:
        factors = [{"factor": f.get("name", str(f)), "weight": f.get("weight")}
                   if isinstance(f, dict) else {"factor": str(f), "weight": None}
                   for f in (latest.factors or [])]

    actions = [{"title": i["title"], "category": i["category"], "at": i["t"]}
               for i in timeline if i["category"] in ("ROUTE", "AI", "RECOVERY")]

    return {
        "report_type": "INCIDENT_REPORT",
        "incident": inc,
        "simulation": detail["simulation"],
        "executive_summary": (
            f"{inc['severity']} {inc['kind']} incident {inc['code']} at "
            f"{inc['building_id'] or 'campus'} — {inc['title']}. "
            + (f"Active for {inc['duration_s']}s. " if inc["duration_s"] is not None
               else "Still active. ")
            + f"Peak risk {detail['metrics']['peak_risk']} "
              f"({detail['metrics']['risk_samples']} samples)."
        ),
        "window": {"started_at": inc["started_at"], "resolved_at": inc["resolved_at"],
                   "duration_s": inc["duration_s"]},
        "metrics": detail["metrics"],
        "timeline_categories": categories,
        "contributing_factors": factors,
        "response_actions": actions[:40],
        "timeline": timeline,
        "recommendations": detail["recommendations"],
        "source": "persisted incident/simulation/risk/route/ai history",
        "generated_at": _now_iso(),
    }


def rows_for_report_csv(report: dict) -> str:
    """Flatten an incident report timeline into CSV text (§33)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["category", "kind", "time", "sim_t", "title", "source"])
    for item in report.get("timeline", []):
        w.writerow([item.get("category"), item.get("kind"), item.get("t"),
                    item.get("sim_t", ""), item.get("title"), item.get("source")])
    return buf.getvalue()


# -------------------------------------------------------------- simulations

def list_simulations(db: Session, *, scenario: str | None = None, status: str | None = None,
                     severity: str | None = None, target_id: str | None = None,
                     search: str | None = None, start: datetime | None = None,
                     end: datetime | None = None, sort: str = "created_at",
                     order: str = "desc", page: int = 1, page_size: int = 25) -> dict:
    q = db.query(Simulation)
    if scenario and scenario.upper() != "ALL":
        q = q.filter(Simulation.scenario == scenario.lower())
    if status and status.upper() != "ALL":
        q = q.filter(Simulation.status == status.upper())
    if severity and severity.upper() != "ALL":
        q = q.filter(Simulation.severity == severity.upper())
    if target_id:
        q = q.filter(Simulation.target_id == target_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Simulation.simulation_code.ilike(like),
                         Simulation.scenario.ilike(like),
                         Simulation.target_id.ilike(like)))
    if start:
        q = q.filter(Simulation.created_at >= start)
    if end:
        q = q.filter(Simulation.created_at <= end)

    total = q.count()
    sort_col = {"created_at": Simulation.created_at, "peak_risk": Simulation.peak_risk,
                "recovery_time_s": Simulation.recovery_time_s,
                "people_affected": Simulation.people_affected,
                "status": Simulation.status, "scenario": Simulation.scenario}.get(
        sort, Simulation.created_at)
    q = q.order_by(sort_col.desc() if order != "asc" else sort_col.asc(), Simulation.id)
    page = max(1, page)
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    event_counts: dict[str, int] = {}
    if rows:
        for sid, cnt in (db.query(SimulationEvent.simulation_id,
                                  func.count(SimulationEvent.id))
                         .filter(SimulationEvent.simulation_id.in_([r.id for r in rows]))
                         .group_by(SimulationEvent.simulation_id).all()):
            event_counts[sid] = cnt

    items = [{
        "id": r.id, "code": r.simulation_code, "scenario": r.scenario,
        "target_id": r.target_id, "target_type": r.target_type, "status": r.status,
        "severity": r.severity, "peak_risk": r.peak_risk,
        "people_affected": r.people_affected, "recovery_time_s": round(r.recovery_time_s, 1),
        "progress": r.progress, "created_at": _iso(r.created_at),
        "ended_at": _iso(r.ended_at), "created_by": r.created_by,
        "events": event_counts.get(r.id, 0),
    } for r in rows]

    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "filters": {"scenario": scenario, "status": status, "severity": severity,
                        "search": search},
            "source": "simulations", "generated_at": _now_iso()}


def simulation_detail(db: Session, sim_id: str) -> dict | None:
    sim = db.get(Simulation, sim_id)
    if sim is None:
        return None
    start, end = _sim_window(db, sim)
    events = (db.query(SimulationEvent)
              .filter(SimulationEvent.simulation_id == sim.id)
              .order_by(SimulationEvent.t, SimulationEvent.id).all())
    by_cat: dict[str, int] = {}
    for e in events:
        c = category_for(e.kind)
        by_cat[c] = by_cat.get(c, 0) + 1

    incs = (db.query(Incident).filter(Incident.simulation_id == sim.id)
            .order_by(Incident.started_at).all())
    route_count = db.query(func.count(RouteEvent.id)).filter(
        RouteEvent.simulation_id == sim.id).scalar() or 0
    ai_count = 0
    if start and end:
        ai_count = db.query(func.count(AiAnalysis.id)).filter(
            AiAnalysis.created_at >= start, AiAnalysis.created_at <= end).scalar() or 0

    risk_entity = sim.target_id or "campus"
    risk_rows = []
    if start:
        end_bound = end or datetime.now(timezone.utc)
        risk_rows = (db.query(RiskScore)
                     .filter(RiskScore.entity_id == risk_entity,
                             RiskScore.created_at >= start.replace(tzinfo=None),
                             RiskScore.created_at <= end_bound.replace(tzinfo=None))
                     .order_by(RiskScore.created_at).all())
    scores = [r.score for r in risk_rows]

    return {
        "simulation": {
            "id": sim.id, "code": sim.simulation_code, "scenario": sim.scenario,
            "target_id": sim.target_id, "target_type": sim.target_type,
            "params": sim.params, "status": sim.status, "severity": sim.severity,
            "peak_risk": sim.peak_risk, "people_affected": sim.people_affected,
            "recovery_time_s": round(sim.recovery_time_s, 1), "progress": sim.progress,
            "current_step": sim.current_step, "total_steps": sim.total_steps,
            "created_at": _iso(sim.created_at), "started_at": _iso(sim.started_at),
            "ended_at": _iso(sim.ended_at), "created_by": sim.created_by,
            "result": sim.result,
        },
        "metrics": {
            "events": len(events), "events_by_category": by_cat,
            "incidents": len(incs), "route_events": int(route_count),
            "ai_analyses_in_window": int(ai_count),
            "wall_start": _iso(start), "wall_end": _iso(end),
            "risk_entity": risk_entity,
            "peak_risk_persisted": round(max(scores), 1) if scores else None,
            "avg_risk_persisted": round(sum(scores) / len(scores), 1) if scores else None,
        },
        "incidents": [{"id": i.id, "code": i.incident_code, "title": i.title,
                       "severity": i.severity, "status": i.status,
                       "started_at": _iso(i.started_at), "resolved_at": _iso(i.resolved_at)}
                      for i in incs],
        "events": [_event_payload(e) for e in events],
        "source": "simulations/simulation_events",
        "generated_at": _now_iso(),
    }


def _event_payload(e: SimulationEvent) -> dict:
    return {"id": e.id, "t": round(e.t, 2), "kind": e.kind,
            "category": category_for(e.kind), "message": e.message,
            "data": e.data or {}, "created_at": _iso(e.created_at)}


def simulation_events(db: Session, sim_id: str) -> dict | None:
    sim = db.get(Simulation, sim_id)
    if sim is None:
        return None
    rows = (db.query(SimulationEvent)
            .filter(SimulationEvent.simulation_id == sim.id)
            .order_by(SimulationEvent.t, SimulationEvent.id).all())
    duration = max((e.t for e in rows), default=0.0)
    return {"simulation_id": sim.id, "code": sim.simulation_code,
            "scenario": sim.scenario, "status": sim.status,
            "duration_s": round(duration, 2), "count": len(rows),
            "events": [_event_payload(e) for e in rows],
            "source": "simulation_events", "generated_at": _now_iso()}


def compare_simulations(db: Session, a_id: str, b_id: str) -> dict | None:
    a = db.get(Simulation, a_id)
    b = db.get(Simulation, b_id)
    if a is None or b is None:
        return None

    def _stats(sim: Simulation) -> dict:
        events = (db.query(SimulationEvent)
                  .filter(SimulationEvent.simulation_id == sim.id)
                  .order_by(SimulationEvent.t, SimulationEvent.id).all())
        by_cat: dict[str, int] = {}
        for e in events:
            c = category_for(e.kind)
            by_cat[c] = by_cat.get(c, 0) + 1
        start, end = _sim_window(db, sim)
        wall = None
        if start and end:
            wall = round((end - start).total_seconds(), 1)
        inc_count = db.query(func.count(Incident.id)).filter(
            Incident.simulation_id == sim.id).scalar() or 0
        route_count = db.query(func.count(RouteEvent.id)).filter(
            RouteEvent.simulation_id == sim.id).scalar() or 0
        last_t = max((e.t for e in events), default=0.0)
        return {"events": len(events), "events_by_category": by_cat,
                "wall_span_s": wall, "sim_duration_s": round(last_t, 2),
                "incidents": int(inc_count), "route_events": int(route_count)}

    sa, sb = _stats(a), _stats(b)
    fields = [
        {"metric": "scenario", "label": "Scenario", "a": a.scenario, "b": b.scenario},
        {"metric": "status", "label": "Status", "a": a.status, "b": b.status},
        {"metric": "severity", "label": "Severity", "a": a.severity, "b": b.severity},
        {"metric": "peak_risk", "label": "Peak risk", "a": a.peak_risk, "b": b.peak_risk},
        {"metric": "people_affected", "label": "People affected",
         "a": a.people_affected, "b": b.people_affected},
        {"metric": "recovery_time_s", "label": "Recovery time (s)",
         "a": round(a.recovery_time_s, 1), "b": round(b.recovery_time_s, 1)},
        {"metric": "sim_duration_s", "label": "Simulation duration (s)",
         "a": sa["sim_duration_s"], "b": sb["sim_duration_s"]},
        {"metric": "wall_span_s", "label": "Wall-clock span (s)",
         "a": sa["wall_span_s"], "b": sb["wall_span_s"]},
        {"metric": "events", "label": "Persisted events", "a": sa["events"],
         "b": sb["events"]},
        {"metric": "incidents", "label": "Linked incidents", "a": sa["incidents"],
         "b": sb["incidents"]},
        {"metric": "route_events", "label": "Route events", "a": sa["route_events"],
         "b": sb["route_events"]},
        {"metric": "created_at", "label": "Created", "a": _iso(a.created_at),
         "b": _iso(b.created_at)},
    ]
    for cat in ("SIMULATION", "RISK", "ROUTE", "AI", "RECOVERY", "INCIDENT"):
        fields.append({"metric": f"cat_{cat.lower()}", "label": f"{cat.title()} events",
                       "a": sa["events_by_category"].get(cat, 0),
                       "b": sb["events_by_category"].get(cat, 0)})
    return {"a": {"id": a.id, "code": a.simulation_code},
            "b": {"id": b.id, "code": b.simulation_code},
            "rows": fields, "source": "simulations/simulation_events",
            "generated_at": _now_iso()}
