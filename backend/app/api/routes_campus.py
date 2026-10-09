from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require
from app.models.entities import Building, Floor, OccupancyRecord, SensorReading
from app.services.optimization_service import compute_routes, route_report
from app.services.state import TwinState, get_state

router = APIRouter(prefix="/api", tags=["campus"])

DATA_SOURCE = "SIMULATED"


def _resolve_building(state: TwinState, key: str) -> str:
    """Accept internal id (``eng``) or campus code (``ENG-B``), case-insensitive."""
    if key in state.buildings:
        return key
    upper = key.upper()
    for b in state.buildings.values():
        if b.code and b.code.upper() == upper:
            return b.id
    raise HTTPException(404, f"Building not found: '{key}' (use id or code, e.g. ENG-B)")


def _resolve_sensor(state: TwinState, key: str) -> str:
    if key in state.sensors:
        return key
    upper = key.upper()
    for s in state.sensors.values():
        if s.sensor_code and s.sensor_code.upper() == upper:
            return s.id
    raise HTTPException(404, f"Sensor not found: '{key}' (use id or sensor_code, e.g. ENG-B-TEMP-01)")


def _parse_ts(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Invalid {label} timestamp (ISO-8601 expected): {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/campus")
def get_campus(principal: dict = Depends(require("read"))):
    state = get_state()
    snap = state.snapshot()
    snap.pop("zones", None)
    snap.pop("sensors", None)
    snap["route_report"] = route_report(state)
    metrics = snap.get("metrics", {})
    gates = [n for n in snap.get("nodes", []) if n.get("kind") == "GATE" or n.get("is_exit")]
    snap["data_source"] = DATA_SOURCE
    snap["metadata"] = {
        "name": "TwinSphere Smart Campus",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": settings.RANDOM_SEED,
        "data_source": DATA_SOURCE,
    }
    snap["summary"] = {
        "buildings": len(state.buildings),
        "floors": sum(b.floors for b in state.buildings.values()),
        "zones": len(state.zones),
        "sensors": len(state.sensors),
        "roads": len(state.roads),
        "gates": len(gates),
        "exits": len([n for n in snap.get("nodes", []) if n.get("kind") == "EXIT"]),
        "occupancy": metrics.get("occupancy", 0),
        "occupancy_pct": metrics.get("occupancy_pct", 0),
        "risk_score": metrics.get("risk", 0),
        "risk_level": metrics.get("risk_level", "LOW"),
        "active_incidents": metrics.get("incidents", 0),
        "active_simulations": 1 if state.active_sim else 0,
    }
    return snap


@router.get("/buildings")
def list_buildings(type: str | None = None, status: str | None = None,
                   principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    state = get_state()
    rows = {b.id: b for b in db.query(Building).all()}
    out = []
    for b in state.buildings.values():
        if type and b.type != type:
            continue
        if status and b.status != status:
            continue
        dbrow = rows.get(b.id)
        d = b.to_dict()
        d["zone_count"] = len([z for z in state.zones.values() if z.building_id == b.id])
        d["sensor_count"] = len([s for s in state.sensors.values() if s.building_id == b.id])
        d["floor_count"] = b.floors
        d["active_incidents"] = [
            i for i in state.incidents if i.get("building_id") == b.id and i["status"] == "ACTIVE"
        ]
        d["risk_detail"] = state.building_risk.get(b.id, {})
        d["has_backup_power"] = dbrow.has_backup_power if dbrow else b.has_backup_power
        out.append(d)
    return out


@router.get("/buildings/{building_id}")
def get_building(building_id: str, principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    state = get_state()
    building_id = _resolve_building(state, building_id)
    b = state.buildings[building_id]
    d = b.to_dict()
    d["zones"] = [z.to_dict() for z in state.zones.values() if z.building_id == building_id]
    d["sensors"] = [s.to_dict() for s in state.sensors.values() if s.building_id == building_id]
    d["risk_detail"] = state.building_risk.get(building_id, {})
    d["exits"] = [
        {**state.nodes[nid], "risk": state.node_risk.get(nid, 0)}
        for nid in state.exits_for(building_id) if nid in state.nodes
    ]
    d["routes"] = [r for r in state.routes if r.get("building_id") == building_id]
    d["incidents"] = [i for i in state.incidents if i.get("building_id") == building_id]
    d["predictions"] = [p for p in state.predictions if p.get("entity_id") == building_id]
    d["zones_meta"] = d["zones"]
    return d


@router.get("/buildings/{building_id}/floors")
def building_floors(building_id: str, principal: dict = Depends(require("read")),
                    db: Session = Depends(get_db)):
    state = get_state()
    building_id = _resolve_building(state, building_id)
    rows = (db.query(Floor)
            .filter(Floor.building_id == building_id)
            .order_by(Floor.floor_number)
            .all())
    if not rows:
        raise HTTPException(404, f"No floors found for building '{building_id}'")
    return [
        {
            "id": r.id, "building_id": r.building_id, "floor_number": r.floor_number,
            "name": r.name, "zone_count": r.zone_count, "area_sqm": r.area_sqm,
            "is_evacuation_level": r.is_evacuation_level,
        }
        for r in rows
    ]


@router.get("/floors")
def list_floors(building_id: str | None = None, principal: dict = Depends(require("read")),
                db: Session = Depends(get_db)):
    state = get_state()
    q = db.query(Floor).order_by(Floor.building_id, Floor.floor_number)
    if building_id:
        q = q.filter(Floor.building_id == _resolve_building(state, building_id))
    return [
        {
            "id": r.id, "building_id": r.building_id, "floor_number": r.floor_number,
            "name": r.name, "zone_count": r.zone_count, "area_sqm": r.area_sqm,
            "is_evacuation_level": r.is_evacuation_level,
        }
        for r in q.all()
    ]


@router.get("/floors/{floor_id}")
def get_floor(floor_id: str, principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    r = db.get(Floor, floor_id.upper())
    if not r:
        for candidate in db.query(Floor).all():
            if candidate.id.lower() == floor_id.lower():
                r = candidate
                break
    if not r:
        raise HTTPException(404, f"Floor not found: '{floor_id}' (e.g. ENG-B-F1)")
    state = get_state()
    return {
        "id": r.id, "building_id": r.building_id, "floor_number": r.floor_number,
        "name": r.name, "zone_count": r.zone_count, "area_sqm": r.area_sqm,
        "is_evacuation_level": r.is_evacuation_level,
        "building": state.buildings.get(r.building_id).to_dict() if r.building_id in state.buildings else None,
        "zones": [z.to_dict() for z in state.zones.values() if z.floor_id == r.id],
    }


@router.get("/zones")
def list_zones(building_id: str | None = None, floor_id: str | None = None,
               floor: int | None = None, zone_type: str | None = None,
               kind: str | None = None, risk_level: str | None = None,
               principal: dict = Depends(require("read"))):
    state = get_state()
    if building_id:
        building_id = _resolve_building(state, building_id)
    out = []
    for z in state.zones.values():
        if building_id and z.building_id != building_id:
            continue
        if floor_id and (z.floor_id or "").upper() != floor_id.upper():
            continue
        if floor is not None and z.floor != floor:
            continue
        wanted = zone_type or kind
        if wanted and z.kind != wanted:
            continue
        if risk_level and z.risk_level != risk_level:
            continue
        out.append(z.to_dict())
    return out


@router.get("/zones/{zone_id}")
def get_zone(zone_id: str, principal: dict = Depends(require("read"))):
    state = get_state()
    z = state.zones.get(zone_id)
    if not z:
        raise HTTPException(404, f"Zone not found: '{zone_id}'")
    d = z.to_dict()
    b = state.buildings.get(z.building_id)
    d["building"] = b.to_dict() if b else None
    d["sensors"] = [s.to_dict() for s in state.sensors.values() if s.zone_id == z.id]
    d["risk_detail"] = {
        "score": {"LOW": 8.0, "MODERATE": 35.0, "HIGH": 65.0, "CRITICAL": 90.0}.get(z.risk_level, 8.0),
        "level": z.risk_level,
        "factors": [],
        "explanation": f"Zone state: {z.status}.",
    }
    return d


@router.get("/roads")
def list_roads(principal: dict = Depends(require("read"))):
    state = get_state()
    return {"nodes": list(state.nodes.values()), "roads": list(state.roads.values())}


@router.get("/routes")
def get_routes(recompute: bool = False, principal: dict = Depends(require("read"))):
    state = get_state()
    if recompute:
        # Phase 10 §7: a GET that mutates route state needs `apply`, not `read`
        # (VIEWER must never trigger recomputation via a query parameter).
        from app.core.security import has_permission

        if not has_permission(principal, "apply"):
            raise HTTPException(403, f"Role {principal.get('role', 'VIEWER')} lacks 'apply' permission")
        compute_routes(state, primary_building=state.active_sim.target_id if state.active_sim else None)
    return {"routes": state.routes, "report": route_report(state)}


@router.post("/routes/recompute")
def recompute_routes(principal: dict = Depends(require("apply"))):
    state = get_state()
    compute_routes(state, primary_building=state.active_sim.target_id if state.active_sim else None)
    return {"routes": state.routes, "report": route_report(state)}


@router.get("/sensors")
def list_sensors(type: str | None = None, building_id: str | None = None,
                 zone_id: str | None = None, status: str | None = None,
                 principal: dict = Depends(require("read"))):
    state = get_state()
    if building_id:
        building_id = _resolve_building(state, building_id)
    out = [s.to_dict() for s in state.sensors.values()
           if (type is None or s.type == type)
           and (building_id is None or s.building_id == building_id)
           and (zone_id is None or s.zone_id == zone_id)
           and (status is None or s.status == status)]
    return out


@router.get("/sensors/{sensor_id}")
def get_sensor(sensor_id: str, principal: dict = Depends(require("read"))):
    state = get_state()
    sensor_id = _resolve_sensor(state, sensor_id)
    s = state.sensors[sensor_id]
    d = s.to_dict()
    d["history"] = list(s.history[-60:])
    d["data_source"] = DATA_SOURCE
    return d


@router.get("/sensors/{sensor_id}/history")
def sensor_history(sensor_id: str, limit: int = 96, start: str | None = None,
                   end: str | None = None, principal: dict = Depends(require("read")),
                   db: Session = Depends(get_db)):
    state = get_state()
    sensor_id = _resolve_sensor(state, sensor_id)
    s = state.sensors[sensor_id]
    q = db.query(SensorReading).filter(SensorReading.sensor_id == sensor_id)
    start_dt = _parse_ts(start, "start")
    end_dt = _parse_ts(end, "end")
    if start_dt:
        q = q.filter(SensorReading.created_at >= start_dt)
    if end_dt:
        q = q.filter(SensorReading.created_at <= end_dt)
    rows = q.order_by(SensorReading.created_at.desc()).limit(min(max(limit, 1), 500)).all()
    return {
        "sensor": s.to_dict(),
        "data_source": DATA_SOURCE,
        "source": DATA_SOURCE,
        "live": list(s.history[-120:]),
        "persisted": [
            {"value": r.value, "at": r.created_at.isoformat(),
             "timestamp": r.created_at.isoformat(),
             "quality": r.quality, "source": r.source}
            for r in reversed(rows)
        ],
    }


@router.get("/risk")
def get_risk(principal: dict = Depends(require("read"))):
    state = get_state()
    published = state.risk_published or {}
    return {
        "campus": state.risk,
        "buildings": state.building_risk,
        "metrics": state.metrics(),
        # Phase 5: stabilised (EMA + hysteresis) view + entity hierarchy
        "published": {
            "campus": published.get("campus"),
            "buildings": {k: v for k, v in published.items() if k != "campus"},
        },
        "hierarchy": state.risk_hierarchy,
        "risk_history": {"campus": (state.risk_stability.trend("campus")
                                    if state.risk_stability else [])},
        "data_source": DATA_SOURCE,
    }


@router.get("/risk/{entity_id}")
def risk_for(entity_id: str, principal: dict = Depends(require("read"))):
    state = get_state()
    published = state.risk_published or {}
    if entity_id == "campus":
        return {"entity_id": "campus", **state.risk,
                "published": published.get("campus"),
                "history": (state.risk_stability.trend("campus")
                            if state.risk_stability else [])}
    detail = state.building_risk.get(entity_id)
    if not detail:
        try:
            resolved = _resolve_building(state, entity_id)
            detail = state.building_risk.get(resolved)
            if detail:
                return {"entity_id": resolved, **detail,
                        "published": published.get(resolved)}
        except HTTPException:
            pass
        raise HTTPException(404, f"Entity not found: '{entity_id}'")
    return {"entity_id": entity_id, **detail,
            "published": published.get(entity_id),
            "history": (state.risk_stability.trend(entity_id)
                        if state.risk_stability else [])}


@router.get("/occupancy-history")
def occupancy_history(building_id: str | None = None, limit: int = 200,
                      principal: dict = Depends(require("read")), db: Session = Depends(get_db)):
    q = db.query(OccupancyRecord).order_by(OccupancyRecord.created_at.desc()).limit(limit)
    if building_id:
        q = q.filter(OccupancyRecord.building_id == building_id)
    rows = list(reversed(q.all()))
    return [{"building_id": r.building_id, "occupancy": r.occupancy,
             "capacity_pct": r.capacity_pct, "at": r.created_at.isoformat()} for r in rows]
