"""Phase 9 §56–§58 — deterministic replay reconstruction from stored events.

`build_replay` turns persisted history (simulation_events + risk_scores +
occupancy_records + route_events + ai_analyses + incidents) into an ordered
timeline plus sampled frames the UI can PLAY/PAUSE/SEEK — including a 3D
frame view (burning zones, per-building risk, active incident/route/AI).

The reconstruction is a pure function of stored rows: two calls always return
identical payloads (§61 replay determinism), and every input table is named in
`source` so nothing looks simulated that is not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.entities import (
    AiAnalysis,
    Incident,
    OccupancyRecord,
    RiskScore,
    RouteEvent,
    Simulation,
    SimulationEvent,
)
from app.services.history_service import category_for

REPLAY_SPEEDS = [0.5, 1.0, 2.0, 5.0, 10.0]
MAX_FRAMES = 500

LIFECYCLE_STATUS = {
    "created": "CREATED", "started": "RUNNING", "paused": "PAUSED",
    "resumed": "RUNNING", "reset": "CREATED", "recovering": "RECOVERING",
    "stabilized": "AWAITING_RECOVERY", "recovered": "RECOVERED",
    "completed": "COMPLETED",
}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class WallClockMap:
    """Piecewise wall-clock ↔ simulation-time mapping built from event pairs.

    Events are taken in wall order but only while sim-time `t` stays
    non-decreasing (a post-completion reset would otherwise invert time).
    """

    def __init__(self, pairs: list[tuple[datetime, float]], duration: float,
                 fallback_start: datetime | None, fallback_end: datetime | None):
        self.duration = duration
        mono: list[tuple[datetime, float]] = []
        last = -1.0
        for w, t in sorted(pairs, key=lambda p: p[0]):
            if t < last - 1e-9:
                break
            mono.append((_aware(w) or w, t))
            last = t
        if len(mono) >= 2:
            self.points = mono
        else:
            start = _aware(fallback_start) or (mono[0][0] if mono
                                               else datetime.now(timezone.utc))
            end = _aware(fallback_end) or (start + timedelta(seconds=max(duration, 1.0)))
            if end <= start:
                end = start + timedelta(seconds=max(duration, 1.0))
            self.points = [(start, 0.0), (end, duration)]

    @property
    def wall_start(self) -> datetime:
        return self.points[0][0]

    @property
    def wall_end(self) -> datetime:
        return self.points[-1][0]

    def t_to_wall(self, t: float) -> datetime:
        pts = self.points
        if t <= pts[0][1]:
            return pts[0][0]
        if t >= pts[-1][1]:
            return pts[-1][0]
        for (w1, t1), (w2, t2) in zip(pts, pts[1:]):
            if t1 <= t <= t2:
                if t2 - t1 <= 1e-9:
                    return w2
                frac = (t - t1) / (t2 - t1)
                return w1 + (w2 - w1) * frac
        return pts[-1][0]

    def wall_to_t(self, w: datetime) -> float | None:
        pts = self.points
        w = _aware(w) or w
        if w < pts[0][0] or w > pts[-1][0]:
            return None
        for (w1, t1), (w2, t2) in zip(pts, pts[1:]):
            if w1 <= w <= w2:
                if (w2 - w1).total_seconds() <= 1e-9:
                    return t2
                frac = (w - w1).total_seconds() / (w2 - w1).total_seconds()
                return t1 + (t2 - t1) * frac
        return None

    def wall_to_t_clamped(self, w: datetime) -> float:
        """Map wall time into sim time, clamping outside the run to 0/duration.

        Used for tables that keep writing a moment before/after the run
        (risk scores persisted at completion, adjacent AI analyses).
        """
        pts = self.points
        w = _aware(w) or w
        if w <= pts[0][0]:
            return float(pts[0][1])
        if w >= pts[-1][0]:
            return float(pts[-1][1])
        t = self.wall_to_t(w)
        return float(t) if t is not None else float(pts[-1][1])


def _frame_step(duration: float, override: float | None) -> float:
    if override and 0.5 <= override <= 60:
        step = float(override)
    else:
        step = max(2.0, min(15.0, duration / 60.0)) if duration > 0 else 1.0
    return step


def build_replay(db: Session, sim_id: str, frame_step: float | None = None) -> dict | None:
    sim = db.get(Simulation, sim_id)
    if sim is None:
        return None

    events = (db.query(SimulationEvent)
              .filter(SimulationEvent.simulation_id == sim.id)
              .order_by(SimulationEvent.t, SimulationEvent.id).all())
    duration = max((e.t for e in events), default=0.0)
    wall = WallClockMap([(e.created_at, e.t) for e in events], duration,
                        _aware(sim.created_at), _aware(sim.ended_at))
    wall_start, wall_end = wall.wall_start, wall.wall_end

    timeline = [{
        "id": e.id, "t": round(e.t, 2), "kind": e.kind,
        "category": category_for(e.kind), "message": e.message,
        "data": e.data or {}, "wall": _iso(e.created_at),
    } for e in events]

    # ---- zone map + cumulative event facts -------------------------------
    zone_buildings: dict[str, str] = {}
    totals_events: list[dict] = []
    for ev in timeline:
        data = ev.get("data") or {}
        z = data.get("zone_id") or data.get("zone")
        if z and data.get("building_id"):
            zone_buildings[z] = data["building_id"]
        elif z and ev["kind"] == "ignition":
            zone_buildings.setdefault(z, sim.target_id or "")
        if isinstance(data.get("totals"), dict):
            totals_events.append(ev)

    # ---- persisted risk mapped into sim time (clamped ±90s around run) ----
    risk_rows = (db.query(RiskScore)
                 .filter(RiskScore.created_at >= wall_start.replace(tzinfo=None) - timedelta(seconds=90),
                         RiskScore.created_at <= wall_end.replace(tzinfo=None) + timedelta(seconds=90))
                 .order_by(RiskScore.created_at, RiskScore.id).all())
    risk_by_entity: dict[str, list[tuple[float, float]]] = {}
    for r in risk_rows:
        t = wall.wall_to_t_clamped(_aware(r.created_at) or r.created_at)
        risk_by_entity.setdefault(r.entity_id, []).append((t, float(r.score)))
    risk_series = [{"t": round(t, 2), "entity": e, "score": round(s, 1)}
                   for e, pts in sorted(risk_by_entity.items())
                   for t, s in pts]

    def _risk_at(entity: str, t: float) -> float | None:
        pts = risk_by_entity.get(entity) or []
        best = None
        for pt, score in pts:
            if pt <= t + 1e-6:
                best = score
            else:
                break
        return round(best, 1) if best is not None else None

    # ---- occupancy (campus) mapped into sim time -------------------------
    occ_rows = (db.query(OccupancyRecord)
                .filter(OccupancyRecord.created_at >= wall_start.replace(tzinfo=None) - timedelta(minutes=2),
                        OccupancyRecord.created_at <= wall_end.replace(tzinfo=None) + timedelta(minutes=2))
                .order_by(OccupancyRecord.created_at).all())
    occ_points: list[tuple[float, int]] = []
    per_wall: dict[datetime, int] = {}
    for row in occ_rows:
        per_wall[row.created_at] = per_wall.get(row.created_at, 0) + int(row.occupancy)
    for w, total in per_wall.items():
        occ_points.append((wall.wall_to_t_clamped(_aware(w) or w), total))
    occ_points.sort()

    def _occupancy_at(t: float) -> int | None:
        best = None
        for pt, v in occ_points:
            if pt <= t + 1e-6:
                best = v
            else:
                break
        return best

    # ---- route events for this simulation --------------------------------
    route_rows = (db.query(RouteEvent)
                  .filter(RouteEvent.simulation_id == sim.id)
                  .order_by(RouteEvent.created_at, RouteEvent.id).all())
    route_points: list[tuple[float, dict]] = []
    for r in route_rows:
        t = wall.wall_to_t_clamped(_aware(r.created_at) or r.created_at)
        route_points.append((t, {
            "id": r.id, "event": r.event, "mode": r.mode, "origin": r.origin,
            "destination": r.destination, "distance": round(r.distance, 1),
            "eta_s": round(r.eta_s, 1), "risk_score": round(r.risk_score, 1),
            "path": r.path or [], "wall": _iso(r.created_at),
        }))
    route_points.sort(key=lambda p: p[0])

    # ---- AI analyses (sim-scoped first, else temporally adjacent) --------
    adjacent = False
    ai_rows = (db.query(AiAnalysis)
               .filter(AiAnalysis.simulation_id == sim.id)
               .order_by(AiAnalysis.created_at, AiAnalysis.id).all())
    if not ai_rows:
        near = timedelta(seconds=120)
        ai_rows = (db.query(AiAnalysis)
                   .filter(AiAnalysis.created_at >= wall_start - near,
                           AiAnalysis.created_at <= wall_end + near)
                   .order_by(AiAnalysis.created_at, AiAnalysis.id).all())
        adjacent = bool(ai_rows)
    ai_points: list[tuple[float, dict]] = []
    for a in ai_rows:
        t = wall.wall_to_t_clamped(_aware(a.created_at) or a.created_at)
        ai_points.append((t, {"id": a.id, "mode": a.mode, "severity": a.severity,
                              "title": a.title, "confidence": a.confidence,
                              "summary": a.summary[:400],
                              "adjacent": adjacent, "wall": _iso(a.created_at)}))
    ai_points.sort(key=lambda p: p[0])

    # ---- incidents linked to this simulation -----------------------------
    incidents = (db.query(Incident)
                 .filter(Incident.simulation_id == sim.id)
                 .order_by(Incident.started_at, Incident.id).all())
    incident_items = [{
        "id": i.id, "code": i.incident_code, "title": i.title, "kind": i.kind,
        "severity": i.severity, "status": i.status,
        "started_wall": _iso(i.started_at), "resolved_wall": _iso(i.resolved_at),
        "start_t": wall.wall_to_t(_aware(i.started_at) or i.started_at),
        "end_t": wall.wall_to_t(_aware(i.resolved_at)) if i.resolved_at else None,
    } for i in incidents]
    for inc in incident_items:
        if inc["start_t"] is None and inc["started_wall"]:
            try:
                inc["start_t"] = wall.wall_to_t_clamped(
                    datetime.fromisoformat(inc["started_wall"]))
            except (ValueError, TypeError):
                inc["start_t"] = None
        if inc["end_t"] is None and inc["resolved_wall"]:
            try:
                inc["end_t"] = wall.wall_to_t_clamped(
                    datetime.fromisoformat(inc["resolved_wall"]))
            except (ValueError, TypeError):
                inc["end_t"] = None

    # ---- frames ----------------------------------------------------------
    step = _frame_step(duration, frame_step)
    t_values: list[float] = [0.0]
    t = 0.0
    while t + step < duration - 1e-6:
        t += step
        t_values.append(round(t, 3))
    if duration > 0 and (not t_values or t_values[-1] < duration - 1e-6):
        t_values.append(round(duration, 3))
    t_values = t_values[:MAX_FRAMES]

    frames: list[dict] = []
    ev_i = 0
    burning: list[str] = []
    status = "CREATED"
    latest_totals: dict = {}
    last_event_kind = "created"
    for ft in t_values:
        while ev_i < len(timeline) and timeline[ev_i]["t"] <= ft + 1e-6:
            ev = timeline[ev_i]
            data = ev.get("data") or {}
            kind = ev["kind"]
            if kind == "ignition":
                z = data.get("zone") or data.get("zone_id")
                if z and z not in burning:
                    burning.append(z)
            elif kind == "spread":
                z = data.get("zone_id")
                if z and z not in burning:
                    burning.append(z)
            if kind in LIFECYCLE_STATUS:
                status = LIFECYCLE_STATUS[kind]
            if isinstance(data.get("totals"), dict):
                latest_totals = data["totals"]
            last_event_kind = kind
            ev_i += 1

        route_active = None
        for pt, payload in route_points:
            if pt <= ft + 1e-6:
                route_active = payload
            else:
                break
        ai_active = None
        for pt, payload in ai_points:
            if pt <= ft + 1e-6:
                ai_active = payload
            else:
                break
        incident_active = None
        for inc in incident_items:
            s_t = inc["start_t"]
            if s_t is None or s_t > ft + 1e-6:
                continue
            e_t = inc["end_t"]
            if e_t is None or e_t >= ft - 1e-6:
                incident_active = {"id": inc["id"], "code": inc["code"],
                                   "title": inc["title"], "severity": inc["severity"]}
                break

        risk_map: dict[str, float | None] = {}
        for entity in sorted(set(["campus", sim.target_id or "campus",
                                  *zone_buildings.values()])):
            if not entity:
                continue
            v = _risk_at(entity, ft)
            if v is not None:
                risk_map[entity] = v

        frames.append({
            "t": round(ft, 2),
            "wall": _iso(wall.t_to_wall(ft)),
            "status": status,
            "last_kind": last_event_kind,
            "people_at_risk": int(latest_totals.get("people_at_risk", 0) or 0),
            "fire_fraction": round(float(latest_totals.get("fire_fraction", 0.0) or 0.0), 3),
            "burning_zones": list(burning),
            "risk": risk_map,
            "occupancy": _occupancy_at(ft),
            "route": route_active,
            "ai": ai_active,
            "incident": incident_active,
        })

    # ---- related snapshots for the UI ------------------------------------
    sim_wall = {
        "start": _iso(wall_start), "end": _iso(wall_end),
        "span_s": round((wall_end - wall_start).total_seconds(), 1),
        "clock_hour": wall_start.hour + wall_start.minute / 60.0,
    }

    return {
        "simulation": {"id": sim.id, "code": sim.simulation_code,
                       "scenario": sim.scenario, "target_id": sim.target_id,
                       "status": sim.status, "severity": sim.severity,
                       "peak_risk": sim.peak_risk,
                       "people_affected": sim.people_affected,
                       "recovery_time_s": round(sim.recovery_time_s, 1),
                       "created_at": _iso(sim.created_at),
                       "ended_at": _iso(sim.ended_at)},
        "duration_s": round(duration, 2),
        "frame_step_s": step,
        "wall": sim_wall,
        "categories": sorted({e["category"] for e in timeline}),
        "speeds": list(REPLAY_SPEEDS),
        "zone_buildings": zone_buildings,
        "events": timeline,
        "frames": frames,
        "risk_series": risk_series,
        "route_events": [{"t": round(t, 2), **payload} for t, payload in route_points],
        "ai_analyses": [{"t": round(t, 2), **payload} for t, payload in ai_points],
        "incidents": incident_items,
        "notes": {
            "risk": "interpolated from persisted risk_scores within the simulation wall-clock window",
            "zones": "burning zones derived from persisted ignition/spread events",
            "ai_adjacent": adjacent,
        },
        "source": "simulation_events + risk_scores + occupancy_records + "
                  "route_events + ai_analyses + incidents",
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def replay_frame(db: Session, sim_id: str, t: float) -> dict | None:
    """Nearest frame at or after simulation time `t` (seek helper)."""
    payload = build_replay(db, sim_id)
    if payload is None:
        return None
    if not payload["frames"]:
        return None
    for frame in payload["frames"]:
        if frame["t"] >= t:
            return frame
    return payload["frames"][-1]
