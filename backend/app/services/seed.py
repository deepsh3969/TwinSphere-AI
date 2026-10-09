"""Database initialisation + realistic seeded campus data.

Run standalone from ``backend/``:

    python -m app.services.seed            # init schema + seed if empty + print stats
    python -m app.services.seed --stats    # print seed statistics only
    python -m app.services.seed --reset    # drop everything, reseed, print stats
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, settings
from app.core.database import Base, SessionLocal, ensure_schema, engine
from app.core.security import hash_password
from app.models.entities import (
    AuditLog,
    Building,
    Floor,
    Incident,
    OccupancyRecord,
    Prediction,
    Recommendation,
    RiskScore,
    Road,
    RoadNode,
    Sensor,
    SensorReading,
    Simulation,
    SimulationEvent,
    SystemAlert,
    User,
    Zone,
)
from app.services.campus_data import (
    BUILDINGS,
    ROAD_NODES,
    ROADS,
    ZONE_TEMPLATES,
    build_floors,
    build_sensors,
    zone_dims,
)
from app.services.sensor_engine import (
    BUILDING_PROFILE,
    occupancy_curve,
    outdoor_temperature,
)

SEED_USERS = [
    ("admin", "admin@twinsphere.local", "admin123", "ADMIN"),
    ("operator", "operator@twinsphere.local", "operator123", "OPERATOR"),
    ("analyst", "analyst@twinsphere.local", "analyst123", "ANALYST"),
    ("viewer", "viewer@twinsphere.local", "viewer123", "VIEWER"),
]

READING_INTERVAL_MIN = 5      # seed resolution: 24h of readings at 5-minute steps
READING_STEPS = 24 * 60 // READING_INTERVAL_MIN  # 288 per sensor


def init_db() -> None:
    """Create missing tables and additively sync columns/indexes of existing ones."""
    ensure_schema()


def _historic_value(stype: str, hour: float, building: dict | None, rng: random.Random) -> float:
    profile = BUILDING_PROFILE.get((building or {}).get("id", ""), BUILDING_PROFILE["eng"])
    frac = occupancy_curve(hour, profile)
    cap = (building or {}).get("capacity", 500)
    working = 1.0 if 7 <= hour <= 19 else 0.35
    if stype == "occupancy":
        return round(100.0 * frac + rng.uniform(-3, 3), 1)
    if stype == "energy":
        return round(max(0.0, cap * 0.055 * (0.35 + 0.75 * frac) * working + rng.uniform(-4, 4)), 1)
    if stype == "temperature":
        return round(outdoor_temperature(hour) * 0.35 + 19.5 + frac * 3 + rng.uniform(-0.6, 0.6), 1)
    if stype == "humidity":
        return round(50 - outdoor_temperature(hour) * 0.3 + rng.uniform(-4, 4), 1)
    if stype == "smoke":
        return round(max(0.5, rng.uniform(1.0, 4.5)), 1)
    if stype == "air_quality":
        return round(42 + 18 * max(0.0, __import__("math").sin((hour - 6) / 12 * 3.14159)) + rng.uniform(-6, 6), 1)
    if stype == "traffic":
        peak = 2.2 if (8 <= hour <= 9.5 or 17 <= hour <= 18.5) else (1.6 if 12.5 <= hour <= 13.5 else (0.3 if hour < 6 or hour > 21 else 1.0))
        return round(max(0.0, 6 * peak + rng.uniform(-1.5, 1.5)), 1)
    if stype == "parking":
        return round(min(100.0, max(0.0, 100 * frac * 0.9 + rng.uniform(-4, 4))), 1)
    if stype == "water":
        return round(max(0.0, frac * 40 * working + rng.uniform(-3, 3)), 1)
    return round(rng.uniform(0, 100), 1)


def sync_static_campus(db: Session, sensors: list[dict]) -> None:
    """Upsert the static campus model (buildings, floors, zones, graph, sensors)."""
    for b in BUILDINGS:
        db.merge(Building(
            id=b["id"], code=b["code"], name=b["name"], type=b["type"],
            description=b.get("description", ""), capacity=b["capacity"],
            occupancy=b["occupancy"], floors=b["floors"], status="OPERATIONAL",
            position_x=b["position_x"], position_y=0.0, position_z=b["position_z"],
            latitude=b.get("latitude"), longitude=b.get("longitude"),
            size_x=b["size_x"], size_z=b["size_z"], height=b["height"],
            color=b["color"], has_backup_power=b["has_backup_power"],
        ))

    zone_counts: dict[str, int] = {}
    for bid, template in ZONE_TEMPLATES.items():
        b = next(x for x in BUILDINGS if x["id"] == bid)
        width, depth, zheight = zone_dims(bid)
        n = max(1, len(template))
        for i, (zid, zname, floor, zcap, zkind, adj) in enumerate(template):
            angle = 2 * math.pi * i / n
            zone_counts[f"{b['code']}-F{floor + 1}"] = zone_counts.get(f"{b['code']}-F{floor + 1}", 0) + 1
            db.merge(Zone(
                id=zid, building_id=bid, name=zname, floor=floor,
                floor_id=f"{b['code']}-F{floor + 1}" if 0 <= floor < b["floors"] else None,
                capacity=zcap, occupancy=int(zcap * 0.6), kind=zkind, risk_level="LOW",
                width=width, depth=depth, height=zheight,
                adjacent=[a[1] for a in adj],
                local_x=math.cos(angle) * b["size_x"] * 0.3,
                local_z=math.sin(angle) * b["size_z"] * 0.3,
            ))

    for f in build_floors():
        db.merge(Floor(
            id=f["id"], building_id=f["building_id"], floor_number=f["floor_number"],
            name=f["name"], zone_count=zone_counts.get(f["id"], 0),
            area_sqm=f["area_sqm"], is_evacuation_level=f["is_evacuation_level"],
        ))

    for n in ROAD_NODES:
        db.merge(RoadNode(id=n["id"], name=n["name"], x=n["x"], z=n["z"],
                          kind=n.get("kind", "JUNCTION"),
                          is_exit=bool(n.get("is_exit", False)),
                          exit_capacity=float(n.get("exit_capacity", 1.0))))
    for r in ROADS:
        a = next(x for x in ROAD_NODES if x["id"] == r["from_node"])
        b = next(x for x in ROAD_NODES if x["id"] == r["to_node"])
        db.merge(Road(id=r["id"], name=r["name"], from_node=r["from_node"], to_node=r["to_node"],
                      length=round(math.dist((a["x"], a["z"]), (b["x"], b["z"])), 2),
                      kind=r.get("kind", "INTERNAL")))

    for s in sensors:
        db.merge(Sensor(
            id=s["id"], sensor_code=s["sensor_code"], name=s["name"], type=s["type"],
            building_id=s.get("building_id"), node_id=s.get("node_id"),
            zone_id=s.get("zone_id"), unit=s.get("unit", ""),
            status=s.get("status", "ONLINE"),
            x=s.get("x", 0.0), y=s.get("y", 0.0), z=s.get("z", 0.0),
            min_value=s.get("min_value"), max_value=s.get("max_value"),
            normal_min=s.get("normal_min"), normal_max=s.get("normal_max"),
            healthy=True,
        ))


def backfill_codes(db: Session) -> None:
    """Give legacy rows (pre-Phase 2) stable human-readable codes and locations."""
    for row in db.query(Incident).filter(Incident.incident_code.is_(None)).all():
        row.incident_code = f"INC-{row.id.removeprefix('inc_').upper()}"
    for row in db.query(Incident).filter(Incident.location_id.is_(None)).all():
        row.location_type = "BUILDING" if row.building_id else "CAMPUS"
        row.location_id = row.building_id or "campus"
    for row in db.query(Simulation).filter(Simulation.simulation_code.is_(None)).all():
        row.simulation_code = f"SIM-{row.id.removeprefix('sim_').upper()}"


def seed_data(db: Session) -> dict:
    """Seed users + demo content once; always keep the static campus model in sync.

    Returns seed statistics (counts per table).
    """
    fresh = db.query(User).first() is None
    now = datetime.now(timezone.utc)
    sensors = build_sensors()
    buildings_by_id = {b["id"]: b for b in BUILDINGS}

    # Phase 10 §6: demo accounts are seeded only when explicitly enabled
    # (development default; disabled when APP_ENV=production).  Production
    # creates its first administrator via `python -m app.services.bootstrap_admin`.
    if fresh and settings.DEMO_USERS_ENABLED:
        for username, email, password, role in SEED_USERS:
            db.add(User(id=f"u_{username}", username=username, email=email,
                        password_hash=hash_password(password), role=role))
        db.flush()

    sync_static_campus(db, sensors)
    backfill_codes(db)

    if fresh:
        rng = random.Random(settings.RANDOM_SEED)
        start = now - timedelta(hours=24)
        occ_seen: set[str] = set()
        for sensor in sensors:
            b = buildings_by_id.get(sensor["building_id"]) if sensor["building_id"] else None
            last = 0.0
            for step in range(READING_STEPS):
                ts = start + timedelta(minutes=READING_INTERVAL_MIN * step)
                hour = ts.hour + ts.minute / 60.0
                value = _historic_value(sensor["type"], hour, b, rng)
                last = value
                db.add(SensorReading(sensor_id=sensor["id"], value=value, quality="GOOD",
                                     source="SIMULATED", created_at=ts))
            row = db.get(Sensor, sensor["id"])
            if row:
                row.current_value = last
            if sensor["building_id"] and sensor["building_id"] not in occ_seen:
                occ_seen.add(sensor["building_id"])
                frac = occupancy_curve(10.0, BUILDING_PROFILE.get(sensor["building_id"], BUILDING_PROFILE["eng"]))
                db.add(OccupancyRecord(building_id=sensor["building_id"],
                                       occupancy=int(b["capacity"] * frac),
                                       capacity_pct=round(100 * frac, 1),
                                       created_at=now - timedelta(minutes=5)))

        seed_incidents = [
            ("inc_seed_1", "INC-0001", "Water leak — CS Building basement", "INFRASTRUCTURE",
             "cs", "MEDIUM", "ACTIVE", "Slow leak detected near server room; facilities notified.",
             34.0, now - timedelta(hours=3), None),
            ("inc_seed_2", "INC-0002", "Fire drill — Library", "DRILL",
             "lib", "LOW", "RESOLVED", "Scheduled drill completed successfully.",
             18.0, now - timedelta(days=1), now - timedelta(days=1, hours=-1)),
            ("inc_seed_3", "INC-0003", "Overnight HVAC fault — Admin", "INFRASTRUCTURE",
             "admin", "LOW", "RESOLVED", "Chiller restarted after reset.",
             22.0, now - timedelta(days=2), now - timedelta(days=2, hours=-2)),
        ]
        for iid, code, title, kind, bid, sev, status, desc, risk, started, ended in seed_incidents:
            db.add(Incident(id=iid, incident_code=code, title=title, kind=kind,
                            building_id=bid, location_type="BUILDING", location_id=bid,
                            severity=sev, status=status, description=desc, risk_score=risk,
                            started_at=started, resolved_at=ended))

        seed_sims = [
            ("sim_seed_fire", "SIM-0001", "fire", "eng", "BUILDING",
             {"intensity": 6, "wind": "E", "ignition_zone": "eng_electronics"},
             "COMPLETED", 78.5, 214, 128.0, "HIGH", now - timedelta(days=1, hours=2)),
            ("sim_seed_crowd", "SIM-0002", "crowd", "lib", "BUILDING",
             {"occupancy_increase": 45},
             "COMPLETED", 52.0, 610, 84.0, "MEDIUM", now - timedelta(days=3)),
            ("sim_seed_road", "SIM-0003", "road", None, "ROAD",
             {"road_id": "r_s2_gate"},
             "COMPLETED", 41.0, 0, 76.0, "MEDIUM", now - timedelta(days=5)),
            ("sim_seed_power", "SIM-0004", "power", "canteen", "BUILDING",
             {},
             "COMPLETED", 47.5, 305, 108.0, "MEDIUM", now - timedelta(days=7)),
        ]
        for (sid, code, scen, target, ttype, params, status, peak, affected, rec, sev,
             created) in seed_sims:
            db.add(Simulation(id=sid, simulation_code=code, scenario=scen, target_id=target,
                              target_type=ttype, params=params, status=status,
                              simulation_speed=1.0, current_step=60, total_steps=60,
                              progress=100.0, peak_risk=peak, people_affected=affected,
                              recovery_time_s=rec, severity=sev,
                              result={"scenario": scen, "target_id": target},
                              created_by="operator",
                              created_at=created, started_at=created,
                              ended_at=created + timedelta(minutes=9)))
            events = [
                (0.0, "created", f"{scen} simulation created"),
                (5.0, "started", "Simulation started"),
                (120.0, "peak", f"Peak risk {peak} reached"),
                (240.0, "recovered", "Recovery completed"),
            ]
            for t, kind, msg in events:
                db.add(SimulationEvent(simulation_id=sid, t=t, kind=kind, message=msg, data={}))

        for eid, etype, score, level in [("campus", "campus", 24.0, "MODERATE"),
                                         ("eng", "building", 31.0, "MODERATE"),
                                         ("cs", "building", 36.0, "MODERATE"),
                                         ("lib", "building", 18.0, "LOW")]:
            db.add(RiskScore(entity_id=eid, entity_type=etype,
                             score=score, level=level, factors=[],
                             explanation="Seed snapshot of normal operations.", created_at=now))

        db.add(Recommendation(id="rec_seed_1", title="Monitor CS basement leak", priority="MEDIUM",
                              entity_id="cs", action="monitor",
                              rationale="Leak is contained; re-inspect in 4 hours.",
                              estimated_impact="Avoids service disruption in the server room; "
                                               "no evacuation required.",
                              status="PENDING", payload={}))
        db.add(SystemAlert(level="INFO", type="SYSTEM", severity="INFO",
                           title="Platform initialised",
                           message="TwinSphere AI seeded with campus model.",
                           entity_id=None, is_active=True))
        db.add(AuditLog(action="system.seed", actor="system", user_id="system",
                        entity="campus", entity_type="campus", entity_id="campus",
                        detail="Initial campus seed data created", created_at=now))
        db.add(Prediction(entity_id="eng", entity_type="building", metric="occupancy",
                          current_value=840, predicted_value=885,
                          horizon_min=20, confidence=0.71, model_name="RandomForestRegressor",
                          summary="Engineering Building occupancy trending toward 885 in 20 minutes.",
                          created_at=now))

    db.commit()
    if fresh:
        _dump_simulation_data(sensors, buildings_by_id)
    return seed_stats(db)


def seed_stats(db: Session | None = None) -> dict:
    own = db is None
    if own:
        db = SessionLocal()
    try:
        stats = {
            "users": db.query(User).count(),
            "buildings": db.query(Building).count(),
            "floors": db.query(Floor).count(),
            "zones": db.query(Zone).count(),
            "road_nodes": db.query(RoadNode).count(),
            "roads": db.query(Road).count(),
            "sensors": db.query(Sensor).count(),
            "sensor_readings": db.query(SensorReading).count(),
            "incidents": db.query(Incident).count(),
            "simulations": db.query(Simulation).count(),
            "predictions": db.query(Prediction).count(),
            "recommendations": db.query(Recommendation).count(),
            "audit_logs": db.query(AuditLog).count(),
        }
    finally:
        if own:
            db.close()
    return stats


def _dump_simulation_data(sensors, buildings_by_id) -> None:
    try:
        out_dir = BASE_DIR / "simulation-data"
        out_dir.mkdir(parents=True, exist_ok=True)
        campus = {
            "buildings": BUILDINGS,
            "floors": build_floors(),
            "zones": {k: [list(t[:5]) + [[a[0], a[1]] for a in t[5]] for t in v]
                      for k, v in ZONE_TEMPLATES.items()},
            "road_nodes": ROAD_NODES,
            "roads": ROADS,
            "sensors": sensors,
        }
        (out_dir / "campus_model.json").write_text(json.dumps(campus, indent=2), encoding="utf-8")

        with open(out_dir / "sensor_history.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["sensor_id", "type", "building_id", "value", "hours_offset"])
            rng = random.Random(settings.RANDOM_SEED + 1)
            for s in sensors:
                b = buildings_by_id.get(s["building_id"]) if s["building_id"] else None
                for step in range(24):
                    hour = step
                    writer.writerow([s["id"], s["type"], s["building_id"] or "",
                                     _historic_value(s["type"], hour, b, rng), 24 - step])
    except Exception:
        import logging
        logging.getLogger("twinsphere.seed").exception("failed to dump simulation-data export")


def load_sensor_history(state) -> None:
    """Warm in-memory sensor history from the database (anomaly detection input)."""
    with SessionLocal() as db:
        for sensor in db.query(Sensor).all():
            st = state.sensors.get(sensor.id)
            if not st:
                continue
            st.value = sensor.current_value or st.value
            rows = (db.query(SensorReading)
                    .filter(SensorReading.sensor_id == sensor.id)
                    .order_by(SensorReading.created_at.desc())
                    .limit(80)
                    .all())
            st.history = [r.value for r in reversed(rows)] or st.history


def _print_stats(stats: dict, header: str = "Seed data loaded.") -> None:
    labels = {
        "users": "Users", "buildings": "Buildings", "floors": "Floors", "zones": "Zones",
        "road_nodes": "Road nodes", "roads": "Roads", "sensors": "Sensors",
        "sensor_readings": "Sensor readings", "incidents": "Incidents",
        "simulations": "Simulations", "predictions": "Predictions",
        "recommendations": "Recommendations", "audit_logs": "Audit logs",
    }
    parts = [f"{labels[k]}: {stats[k]}" for k in labels if k in stats]
    print(f"{header} " + ", ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(description="TwinSphere AI seed utilities")
    parser.add_argument("--stats", action="store_true", help="print seed statistics and exit")
    parser.add_argument("--reset", action="store_true", help="drop all tables, recreate and reseed")
    args = parser.parse_args()

    if args.stats:
        _print_stats(seed_stats(), header="Current database:")
        return
    if args.reset:
        Base.metadata.drop_all(bind=engine)
        print("Database reset (all tables dropped).")
    init_db()
    with SessionLocal() as db:
        stats = seed_data(db)
    _print_stats(stats)


if __name__ == "__main__":
    main()
