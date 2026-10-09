"""Phase 9 §50–§63 — history, replay and report endpoints.

All routes are read-only and RBAC-gated with ``require("read")`` (§48).  They
serve the History pages, incident/simulation detail views, replay playback
(PAYLOAD includes events + frames + 3D inputs) and CSV/JSON exports.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ratelimit import limit
from app.core.security import require
from app.services import history_service as hs
from app.services import replay_service as rs
from app.services.analytics_service import EXPORT_KINDS, export_dataset, resolve_window

router = APIRouter(prefix="/api/history", tags=["history"])


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is None else dt.astimezone(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------- incidents

@router.get("/incidents")
def incidents_list(
    status: str | None = Query(None), severity: str | None = Query(None),
    kind: str | None = Query(None), building_id: str | None = Query(None),
    simulation_id: str | None = Query(None), q: str | None = Query(None),
    start: str | None = Query(None), end: str | None = Query(None),
    sort: str = Query("started_at"), order: str = Query("desc"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    return hs.list_incidents(db, status=status, severity=severity, kind=kind,
                             building_id=building_id, simulation_id=simulation_id,
                             search=q, start=_parse_dt(start), end=_parse_dt(end),
                             sort=sort, order=order, page=page, page_size=page_size)


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, principal: dict = Depends(require("read")),
                    db: Session = Depends(get_db)):
    out = hs.incident_detail(db, incident_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return out


@router.get("/incidents/{incident_id}/report")
def incident_report(incident_id: str, principal: dict = Depends(require("read")),
                    db: Session = Depends(get_db)):
    out = hs.incident_report(db, incident_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return out


@router.get("/incidents/{incident_id}/export")
def incident_export(incident_id: str, format: str = Query("csv"),
                    _: None = Depends(limit("export")),
                    principal: dict = Depends(require("export")),
                    db: Session = Depends(get_db)):
    report = hs.incident_report(db, incident_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if format == "json":
        import json as _json
        return Response(content=_json.dumps(report, default=str),
                        media_type="application/json")
    rows = hs.rows_for_report_csv(report)
    return Response(content=rows, media_type="text/csv",
                    headers={"Content-Disposition":
                             f'attachment; filename="incident_{incident_id}.csv"'})


# --------------------------------------------------------------- simulations

@router.get("/simulations")
def simulations_list(
    scenario: str | None = Query(None), status: str | None = Query(None),
    severity: str | None = Query(None), target_id: str | None = Query(None),
    q: str | None = Query(None), start: str | None = Query(None),
    end: str | None = Query(None), sort: str = Query("created_at"),
    order: str = Query("desc"), page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    return hs.list_simulations(db, scenario=scenario, status=status, severity=severity,
                               target_id=target_id, search=q, start=_parse_dt(start),
                               end=_parse_dt(end), sort=sort, order=order, page=page,
                               page_size=page_size)


@router.get("/simulations/compare")
def simulations_compare(a: str = Query(...), b: str = Query(...),
                        principal: dict = Depends(require("read")),
                        db: Session = Depends(get_db)):
    out = hs.compare_simulations(db, a, b)
    if out is None:
        raise HTTPException(status_code=404, detail="One or both simulations not found")
    return out


@router.get("/simulations/{sim_id}")
def simulation_detail(sim_id: str, principal: dict = Depends(require("read")),
                      db: Session = Depends(get_db)):
    out = hs.simulation_detail(db, sim_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return out


@router.get("/simulations/{sim_id}/events")
def simulation_event_list(sim_id: str, principal: dict = Depends(require("read")),
                          db: Session = Depends(get_db)):
    out = hs.simulation_events(db, sim_id)
    if out is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return out


@router.get("/simulations/{sim_id}/replay")
def simulation_replay(sim_id: str, frame_step: float | None = Query(None, ge=0.5, le=60),
                      principal: dict = Depends(require("read")),
                      db: Session = Depends(get_db)):
    """Full replay payload: ordered events + sampled frames + 3D inputs (§56)."""
    out = rs.build_replay(db, sim_id, frame_step=frame_step)
    if out is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return out


@router.get("/simulations/{sim_id}/frame")
def simulation_frame(sim_id: str, t: float = Query(0.0, ge=0),
                     principal: dict = Depends(require("read")),
                     db: Session = Depends(get_db)):
    out = rs.replay_frame(db, sim_id, t)
    if out is None:
        raise HTTPException(status_code=404, detail="Simulation or replay not found")
    return out


# -------------------------------------------------------------------- export

@router.get("/export")
def history_export(kind: str = Query("incidents"), range: str = Query("30D"),
                   start: str | None = Query(None), end: str | None = Query(None),
                   format: str = Query("csv"),
                   _: None = Depends(limit("export")),
                   principal: dict = Depends(require("export")),
                   db: Session = Depends(get_db)):
    from app.services.state import get_state
    kind = (kind or "").lower()
    if kind not in EXPORT_KINDS:
        raise HTTPException(status_code=400,
                            detail=f"kind must be one of {', '.join(EXPORT_KINDS)}")
    window = resolve_window(range, start, end)
    try:
        filename, media_type, body = export_dataset(db, get_state(), kind, window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if format == "json":
        import json as _json
        return Response(content=_json.dumps({"kind": kind, "window": window.as_dict(),
                                             "csv": body}, default=str),
                        media_type="application/json")
    return Response(content=body, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
