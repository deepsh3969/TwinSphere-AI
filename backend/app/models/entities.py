from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="VIEWER")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Building(Base):
    __tablename__ = "buildings"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    occupancy: Mapped[int] = mapped_column(Integer, default=0)
    floors: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="OPERATIONAL", index=True)
    position_x: Mapped[float] = mapped_column(Float)
    position_y: Mapped[float] = mapped_column(Float, default=0.0)
    position_z: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_x: Mapped[float] = mapped_column(Float)
    size_z: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float, default=8.0)
    color: Mapped[str] = mapped_column(String(16), default="#3b82f6")
    has_backup_power: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    zones: Mapped[list["Zone"]] = relationship(back_populates="building", cascade="all, delete-orphan")
    sensors: Mapped[list["Sensor"]] = relationship(back_populates="building", cascade="all, delete-orphan")
    building_floors: Mapped[list["Floor"]] = relationship(
        back_populates="building", cascade="all, delete-orphan"
    )


class Floor(Base):
    __tablename__ = "floors"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    floor_number: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(60))
    zone_count: Mapped[int] = mapped_column(Integer, default=0)
    area_sqm: Mapped[float] = mapped_column(Float, default=0.0)
    is_evacuation_level: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    building: Mapped[Building] = relationship(back_populates="building_floors")

    __table_args__ = (Index("ix_floors_building_number", "building_id", "floor_number"),)


class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    floor: Mapped[int] = mapped_column(Integer, default=0)
    floor_id: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=50)
    occupancy: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(30), default="ROOM")
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    width: Mapped[float] = mapped_column(Float, default=4.0)
    depth: Mapped[float] = mapped_column(Float, default=4.0)
    height: Mapped[float] = mapped_column(Float, default=3.5)
    adjacent: Mapped[list] = mapped_column(JSON, default=list)
    local_x: Mapped[float] = mapped_column(Float, default=0.0)
    local_z: Mapped[float] = mapped_column(Float, default=0.0)

    building: Mapped[Building] = relationship(back_populates="zones")


class Road(Base):
    __tablename__ = "roads"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    from_node: Mapped[str] = mapped_column(String(40))
    to_node: Mapped[str] = mapped_column(String(40))
    length: Mapped[float] = mapped_column(Float)
    capacity: Mapped[float] = mapped_column(Float, default=1.0)
    congestion: Mapped[float] = mapped_column(Float, default=0.0)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(20), default="INTERNAL")


class RoadNode(Base):
    __tablename__ = "road_nodes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    x: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(24), default="JUNCTION")
    is_exit: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_capacity: Mapped[float] = mapped_column(Float, default=1.0)


class Sensor(Base):
    __tablename__ = "sensors"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    sensor_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(30), index=True)
    building_id: Mapped[str | None] = mapped_column(ForeignKey("buildings.id"), nullable=True, index=True)
    node_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    zone_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(16), default="ONLINE", index=True)
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    z: Mapped[float] = mapped_column(Float, default=0.0)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normal_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    normal_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    current_value: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    building: Mapped[Building | None] = relationship(back_populates="sensors")


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(ForeignKey("sensors.id"), index=True)
    value: Mapped[float] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(8), default="GOOD")
    source: Mapped[str] = mapped_column(String(16), default="SIMULATED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


Index("ix_sensor_readings_sensor_time", SensorReading.sensor_id, SensorReading.created_at)


class OccupancyRecord(Base):
    __tablename__ = "occupancy_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    occupancy: Mapped[int] = mapped_column(Integer)
    capacity_pct: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# Phase 9: analytics range scans (building within window)
Index("ix_occupancy_records_building_time", OccupancyRecord.building_id,
      OccupancyRecord.created_at)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    incident_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))
    building_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    location_type: Mapped[str] = mapped_column(String(16), default="BUILDING")
    location_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="LOW")
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # Phase 6: incident produced by an emergency simulation (nullable, additive)
    simulation_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)


# Phase 9: incident history filters (severity/type facets)
Index("ix_incidents_severity", Incident.severity)
Index("ix_incidents_kind", Incident.kind)


class Simulation(Base):
    __tablename__ = "simulations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    simulation_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    scenario: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="CREATED", index=True)
    simulation_speed: Mapped[float] = mapped_column(Float, default=1.0)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    peak_risk: Mapped[float] = mapped_column(Float, default=0.0)
    people_affected: Mapped[int] = mapped_column(Integer, default=0)
    recovery_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), default="LOW")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimulationEvent(Base):
    __tablename__ = "simulation_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id"), index=True)
    t: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# Phase 9: replay reads a simulation's events in time order
Index("ix_simulation_events_sim_t", SimulationEvent.simulation_id, SimulationEvent.t)


class RiskScore(Base):
    __tablename__ = "risk_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(24), default="campus")
    score: Mapped[float] = mapped_column(Float)
    level: Mapped[str] = mapped_column(String(16))
    factors: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# Phase 9: analytics range scans (entity within window)
Index("ix_risk_scores_entity_time", RiskScore.entity_id, RiskScore.created_at)


class EvacuationRoute(Base):
    __tablename__ = "evacuation_routes"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    origin_id: Mapped[str] = mapped_column(String(60))
    exit_id: Mapped[str] = mapped_column(String(40))
    node_path: Mapped[list] = mapped_column(JSON, default=list)
    road_path: Mapped[list] = mapped_column(JSON, default=list)
    distance: Mapped[float] = mapped_column(Float, default=0.0)
    eta_s: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="SAFE")
    reason: Mapped[str] = mapped_column(Text, default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # Phase 7 additions (additive — ensure_schema/alembic upgrade in place)
    simulation_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    mode: Mapped[str] = mapped_column(String(16), default="balanced")
    kind: Mapped[str] = mapped_column(String(24), default="evacuation")
    congestion_score: Mapped[float] = mapped_column(Float, default=0.0)
    route_version: Mapped[int] = mapped_column(Integer, default=1)
    people_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class RouteEvent(Base):
    """Phase 7 §33/§34 — persisted route calculation history (Phase 9 input)."""

    __tablename__ = "route_events"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    route_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    simulation_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    event: Mapped[str] = mapped_column(String(32), default="calculated")
    origin: Mapped[str] = mapped_column(String(60), default="")
    destination: Mapped[str] = mapped_column(String(60), default="")
    mode: Mapped[str] = mapped_column(String(16), default="balanced")
    path: Mapped[list] = mapped_column(JSON, default=list)
    distance: Mapped[float] = mapped_column(Float, default=0.0)
    eta_s: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    congestion_score: Mapped[float] = mapped_column(Float, default=0.0)
    route_version: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# Phase 9: route analytics reads a simulation's route history in time order
Index("ix_route_events_sim_time", RouteEvent.simulation_id, RouteEvent.created_at)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(24), default="building", index=True)
    metric: Mapped[str] = mapped_column(String(30))
    current_value: Mapped[float] = mapped_column(Float)
    predicted_value: Mapped[float] = mapped_column(Float)
    horizon_min: Mapped[int] = mapped_column(Integer, default=20)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    model_name: Mapped[str] = mapped_column(String(60), default="statistical")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    title: Mapped[str] = mapped_column(String(140))
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    incident_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60))
    rationale: Mapped[str] = mapped_column(Text, default="")
    estimated_impact: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SystemAlert(Base):
    __tablename__ = "system_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    type: Mapped[str] = mapped_column(String(24), default="SYSTEM")
    severity: Mapped[str] = mapped_column(String(16), default="INFO")
    title: Mapped[str] = mapped_column(String(140))
    message: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity: Mapped[str] = mapped_column(String(60), default="")
    entity_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AiAnalysis(Base):
    """Phase 8 §57 — persisted AI Analyst analyses (Phase 9 input)."""

    __tablename__ = "ai_analyses"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)  # analysis_id
    mode: Mapped[str] = mapped_column(String(16), default="CAMPUS", index=True)
    severity: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="LOW")
    status: Mapped[str] = mapped_column(String(24), default="completed")
    source: Mapped[str] = mapped_column(String(24), default="local_fallback")
    provider: Mapped[str] = mapped_column(String(24), default="deterministic")
    model: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(160), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[str] = mapped_column(String(16), default="LOW")
    question: Mapped[str] = mapped_column(String(500), default="")
    context_signature: Mapped[str] = mapped_column(String(40), default="", index=True)
    simulation_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AiRecommendation(Base):
    """Phase 8 §57 — analyst recommendation cards + human-in-the-loop state."""

    __tablename__ = "ai_recommendations"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)  # card id
    analysis_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=1, index=True)
    category: Mapped[str] = mapped_column(String(24), default="GENERAL")
    action: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AiEvidence(Base):
    """Phase 8 §57 — grounding evidence rows behind each analysis."""

    __tablename__ = "ai_evidence"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # {analysis_id}:{ev_id}
    analysis_id: Mapped[str] = mapped_column(String(60), index=True)
    label: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(24), default="campus")
    source_id: Mapped[str] = mapped_column(String(60), default="")
    metric: Mapped[str] = mapped_column(String(40), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(16), default="")
    severity: Mapped[str] = mapped_column(String(16), default="INFO")
    timestamp: Mapped[str] = mapped_column(String(40), default="")
    age_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
