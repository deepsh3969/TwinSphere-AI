"""Central digital twin state.

Backend is authoritative for incidents, simulations, sensor state, risk,
predictions, routes and recommendations. The frontend renders this state.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.campus_data import (
    BUILDINGS,
    BUILDING_EXITS,
    ROAD_NODES,
    ROADS,
    ZONE_TEMPLATES,
)

CLOCK_RATE = 15.0  # virtual seconds per real second at 1x speed
START_CLOCK = 10 * 3600.0  # 10:00 campus time
WALK_SPEED = 1.35  # units (metres) per second
ALLOWED_SPEEDS = (1.0, 2.0, 5.0, 10.0)  # Phase 4 realtime simulator speeds (§36)
SIM_STATUS_RUNNING = "RUNNING"
SIM_STATUS_PAUSED = "PAUSED"
SIM_STATUS_STOPPED = "STOPPED"
_BUILDING_IDS = frozenset(b["id"] for b in BUILDINGS)


def risk_level(score: float) -> str:
    if score <= 20:
        return "LOW"
    if score <= 40:
        return "MODERATE"
    if score <= 60:
        return "ELEVATED"
    if score <= 80:
        return "HIGH"
    return "CRITICAL"


@dataclass
class ZoneState:
    id: str
    building_id: str
    name: str
    floor: int
    capacity: int
    occupancy: int
    kind: str
    adjacent: list[str]
    fire: float = 0.0  # 0 = normal, 1 = fully burning
    smoke: float = 0.0
    temperature: float = 24.0
    status: str = "NORMAL"
    local_x: float = 0.0
    local_z: float = 0.0
    floor_id: str | None = None
    width: float = 4.0
    depth: float = 4.0
    height: float = 3.5

    @property
    def zone_type(self) -> str:
        return self.kind

    @property
    def risk_level(self) -> str:
        if self.status == "FIRE" or self.fire > 0.5:
            return "CRITICAL"
        if self.status == "SMOKE" or self.smoke > 8.0:
            return "HIGH"
        if self.status == "AFFECTED":
            return "MODERATE"
        return "LOW"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "building_id": self.building_id, "name": self.name,
            "floor": self.floor, "floor_id": self.floor_id,
            "capacity": self.capacity, "occupancy": self.occupancy,
            "kind": self.kind, "zone_type": self.kind, "risk_level": self.risk_level,
            "width": self.width, "depth": self.depth, "height": self.height,
            "adjacent": self.adjacent, "fire": round(self.fire, 3),
            "smoke": round(self.smoke, 2), "temperature": round(self.temperature, 1),
            "status": self.status, "local_x": self.local_x, "local_z": self.local_z,
        }


@dataclass
class BuildingState:
    id: str
    name: str
    type: str
    capacity: int
    occupancy: int
    floors: int
    status: str
    position_x: float
    position_z: float
    size_x: float
    size_z: float
    height: float
    color: str
    has_backup_power: bool
    code: str = ""
    description: str = ""
    latitude: float | None = None
    longitude: float | None = None
    temperature: float = 24.0
    humidity: float = 45.0
    energy: float = 0.0
    smoke: float = 0.0
    air_quality: float = 42.0
    water: float = 0.0
    risk: float = 0.0
    risk_level: str = "LOW"
    sensor_health: float = 100.0
    power: bool = True
    backup_power: bool = False
    evacuation_order: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "code": self.code, "name": self.name, "type": self.type,
            "description": self.description, "capacity": self.capacity,
            "occupancy": self.occupancy, "floors": self.floors, "status": self.status,
            "position": {"x": self.position_x, "y": 0.0, "z": self.position_z},
            "latitude": self.latitude, "longitude": self.longitude,
            "size": {"x": self.size_x, "z": self.size_z}, "height": self.height,
            "color": self.color, "has_backup_power": self.has_backup_power,
            "temperature": round(self.temperature, 1), "humidity": round(self.humidity, 1),
            "energy": round(self.energy, 1), "smoke": round(self.smoke, 1),
            "air_quality": round(self.air_quality, 0), "water": round(self.water, 1),
            "risk": round(self.risk, 1), "risk_level": self.risk_level,
            "sensor_health": round(self.sensor_health, 1), "power": self.power,
            "backup_power": self.backup_power, "evacuation_order": self.evacuation_order,
            "occupancy_pct": round(100.0 * self.occupancy / max(1, self.capacity), 1),
        }


@dataclass
class SensorState:
    id: str
    name: str
    type: str
    building_id: str | None
    unit: str
    x: float
    z: float
    value: float
    baseline: float
    healthy: bool = True
    node_id: str | None = None
    history: list[float] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    sensor_code: str = ""
    zone_id: str | None = None
    y: float = 0.0
    min_value: float | None = None
    max_value: float | None = None
    normal_min: float | None = None
    normal_max: float | None = None

    @property
    def status(self) -> str:
        return "ONLINE" if self.healthy else "OFFLINE"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "sensor_code": self.sensor_code, "name": self.name,
            "type": self.type, "building_id": self.building_id, "zone_id": self.zone_id,
            "unit": self.unit, "status": self.status, "healthy": self.healthy,
            "x": self.x, "y": self.y, "z": self.z,
            "min_value": self.min_value, "max_value": self.max_value,
            "normal_min": self.normal_min, "normal_max": self.normal_max,
            "value": round(self.value, 2), "last_reading": round(self.value, 2),
            "baseline": round(self.baseline, 2),
            "node_id": self.node_id, "updated_at": self.updated_at,
        }


@dataclass
class SimulationState:
    id: str
    scenario: str
    target_id: str | None
    params: dict
    simulation_code: str = ""
    status: str = "CREATED"  # CREATED/PAUSED/RUNNING/RECOVERING/COMPLETED/RESET
    t: float = 0.0
    duration: float = 0.0
    progress: float = 0.0
    peak_risk: float = 0.0
    people_at_risk: int = 0
    phase: str = "idle"
    events: list[dict] = field(default_factory=list)
    recover_t: float = 0.0
    recover_duration: float = 120.0
    started_at: float | None = None
    # Phase 6 peak/live metrics for results + live panel (§46/§48)
    weighted_people: int = 0
    affected_zones: int = 0
    max_people_at_risk: int = 0
    peak_temperature: float = 24.0
    peak_smoke: float = 0.0
    results: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "simulation_code": self.simulation_code,
            "scenario": self.scenario, "scenario_type": self.scenario,
            "target_id": self.target_id,
            "target_type": "BUILDING" if self.target_id in _BUILDING_IDS else
            ("ROAD" if self.scenario == "road" else "CAMPUS"),
            "params": self.params, "parameters": self.params,
            "status": self.status, "t": round(self.t, 1),
            "duration": self.duration, "progress": round(self.progress, 2),
            "current_step": int(round(self.progress * 60 / 100)),
            "total_steps": 60,
            "peak_risk": round(self.peak_risk, 1), "people_at_risk": self.people_at_risk,
            "weighted_people": self.weighted_people,
            "affected_zones": self.affected_zones,
            "max_people_at_risk": self.max_people_at_risk,
            "peak_temperature": round(self.peak_temperature, 1),
            "peak_smoke": round(self.peak_smoke, 1),
            "results": self.results,
            "phase": self.phase, "recover_t": round(self.recover_t, 1),
            "recover_duration": self.recover_duration, "events": self.events[-12:],
        }


@dataclass
class SimulationContext:
    """Modifier interface between an active scenario and the sensor sim (Phase 4).

    Built every tick from `TwinState.active_sim` (see `build_simulation_context`).
    Default values are neutral so the sensor engine behaves identically when no
    scenario is running. Future scenario types (e.g. fire with blocked areas)
    can extend the modifier fields without touching the tick loop.
    """
    active: bool = False
    scenario: str | None = None
    target_id: str | None = None
    params: dict = field(default_factory=dict)
    status: str | None = None
    t: float = 0.0
    duration: float = 0.0
    # generic modifiers (applied by sensor_engine.tick_sensors)
    occupancy_multiplier: float = 1.0
    occupancy_cap_fraction: float | None = None
    occupancy_delta: float = 0.0
    temperature_offset: float = 0.0
    energy_multiplier: float = 1.0
    smoke_multiplier: float = 1.0
    blocked_zones: list[str] = field(default_factory=list)
    blocked_roads: list[str] = field(default_factory=list)


def build_simulation_context(state: "TwinState") -> SimulationContext:
    """Derive this tick's `SimulationContext` from the active scenario.

    Pure function (no RNG, no side effects) so call order of `state.rng` is
    unchanged and the tick loop stays deterministic for a given seed.
    """
    from ai.simulation import crowd_occupancy_multiplier, temperature_event

    sim = state.active_sim
    if sim is None:
        return SimulationContext()
    ctx = SimulationContext(
        active=sim.status in ("RUNNING", "PAUSED"),
        scenario=sim.scenario, target_id=sim.target_id,
        params=sim.params, status=sim.status, t=sim.t, duration=sim.duration,
    )
    if not ctx.active:
        return ctx
    if sim.scenario == "crowd":
        increase = float(sim.params.get("occupancy_increase", 40))
        ctx.occupancy_multiplier = crowd_occupancy_multiplier(increase, sim.t, sim.duration)
        ctx.occupancy_cap_fraction = 1.15
    elif sim.scenario == "fire":
        affected = sum(
            z.occupancy for z in state.zones.values()
            if z.building_id == sim.target_id and z.status in ("FIRE", "SMOKE", "AFFECTED")
        )
        evac_progress = min(1.0, sim.t / max(60.0, sim.duration * 0.6))
        ctx.occupancy_delta = -affected * evac_progress * 0.1
    elif sim.scenario == "temperature":
        heat = temperature_event(float(sim.params.get("ambient_c", 38.0)))
        ctx.temperature_offset = heat["temperature_offset"]
        ctx.energy_multiplier = heat["energy_multiplier"]
    return ctx


class TwinState:
    def __init__(self, seed: int = 42) -> None:
        from app.core.config import settings

        self.rng = random.Random(seed)
        self.seed = seed
        self.clock = START_CLOCK
        default_speed = float(getattr(settings, "DEFAULT_SPEED", 1.0))
        self.speed = default_speed if default_speed in ALLOWED_SPEEDS else 1.0
        self.sim_status = SIM_STATUS_RUNNING if settings.SIMULATION_ENABLED else SIM_STATUS_STOPPED
        self.sim_context = SimulationContext()
        self.last_tick_at: str | None = None
        self.tick_count = 0
        self.status = "NORMAL"
        self.buildings: dict[str, BuildingState] = {}
        self.zones: dict[str, ZoneState] = {}
        self.sensors: dict[str, SensorState] = {}
        self.roads: dict[str, dict] = {}
        self.nodes: dict[str, dict] = {}
        self.node_risk: dict[str, float] = {}
        self.incidents: list[dict] = []
        self.risk: dict[str, Any] = {"score": 0, "level": "LOW", "factors": [], "explanation": ""}
        self.building_risk: dict[str, dict] = {}
        # Phase 5: stabilised (smoothed + hysteresis) risk for AI surfaces
        self.risk_published: dict[str, dict] = {}
        self.risk_stability: Any = None          # ai.risk.RiskStability (lazily built)
        self.risk_hierarchy: Any = None          # campus/building/floor/zone/sensor detail
        self.ai_events: list[dict] = []          # bounded AI timeline for the UI
        self.ai_health: dict[str, Any] = {"ok": True, "last_cycle": None, "errors": 0,
                                          "data_quality": "OK", "degraded": False}
        self.predictions: list[dict] = []
        self.anomalies: list[dict] = []
        self.sensor_ai_status: dict[str, dict] = {}
        self.recommendations: list[dict] = []
        self.routes: list[dict] = []
        # Phase 7: route & evacuation optimisation state
        self.route_plan: dict | None = None      # active computed plan (see route_service)
        self.route_version: int = 0              # global monotonic route version (§11)
        self.route_mode: str = "balanced"        # current active route mode (§7)
        self.route_history: list[dict] = []      # bounded recent calculations (§33)
        self.evacuation: dict = {"status": "IDLE", "buildings": [], "bottlenecks": [],
                                 "people_at_risk": 0}
        self.bottleneck_ids: list[str] = []      # last detected bottleneck locations
        self._route_signature: tuple | None = None   # invalidation fingerprint (§10)
        self._evac_sig: tuple | None = None          # campus evacuation content sig
        self.alerts: list[dict] = []
        self.analyst: dict = {}
        # Phase 8: AI Analyst runtime bookkeeping (§36/§44/§56)
        self.analyst_health: dict[str, Any] = {
            "status": "STARTING", "llm_configured": False, "runs": 0,
            "cache_hits": 0, "fallbacks": 0, "llm_errors": 0,
            "fail_streak": 0, "last_run": None, "last_latency_ms": 0,
            "last_error": None, "last_source": None,
        }
        self.analyst_last_run: float = 0.0            # monotonic cooldown clock
        self.analyst_last_signature: str = ""         # §44 cache key of last run
        self.analyst_cache: dict[str, dict] = {}      # signature -> result (bounded)
        self._analyst_inflight: bool = False          # background-run guard
        self._analyst_prev_ctx: dict | None = None    # previous context (§28 what_changed)
        self.active_sim: SimulationState | None = None
        # Phase 6: typed simulation.* WS events queued by the engine (sync),
        # flushed by the runtime loop via manager.emit (async).
        self.pending_sim_events: list[dict] = []
        self.recovery_progress: float = 100.0
        self.history: list[dict] = []
        self.series: dict[str, list] = {}
        self._last_series_sample: float = START_CLOCK
        self.metric_history: dict[str, list[dict]] = {
            "occupancy": [], "energy": [], "temperature": [], "risk": [],
            "incidents": [], "water": [],
        }
        self.system_health = {"backend": True, "database": True, "simulation": True, "ai": True}
        self._init_static()

    # ------------------------------------------------------------------ setup
    def _init_static(self) -> None:
        from app.services.campus_data import build_sensors, floor_id_for, zone_dims

        for b in BUILDINGS:
            self.buildings[b["id"]] = BuildingState(
                id=b["id"], name=b["name"], type=b["type"], capacity=b["capacity"],
                occupancy=b["occupancy"], floors=b["floors"], status="OPERATIONAL",
                position_x=b["position_x"], position_z=b["position_z"],
                size_x=b["size_x"], size_z=b["size_z"], height=b["height"],
                color=b["color"], has_backup_power=b["has_backup_power"],
                code=b["code"], description=b.get("description", ""),
                latitude=b.get("latitude"), longitude=b.get("longitude"),
                energy=round(b["capacity"] * 0.06, 1),
            )
            template = ZONE_TEMPLATES.get(b["id"], [])
            width, depth, fheight = zone_dims(b["id"])
            for i, (zid, zname, floor, zcap, zkind, adj) in enumerate(template):
                n = max(1, len(template))
                angle = 2 * math.pi * i / n
                self.zones[zid] = ZoneState(
                    id=zid, building_id=b["id"], name=zname, floor=floor,
                    capacity=zcap, occupancy=int(zcap * 0.6), kind=zkind,
                    adjacent=[a[1] for a in adj],
                    local_x=math.cos(angle) * b["size_x"] * 0.3,
                    local_z=math.sin(angle) * b["size_z"] * 0.3,
                    floor_id=floor_id_for(b["id"], floor),
                    width=width, depth=depth, height=fheight,
                )

        for node in ROAD_NODES:
            self.nodes[node["id"]] = dict(node)
            self.node_risk[node["id"]] = 0.0
        for road in ROADS:
            a = self.nodes[road["from_node"]]
            b = self.nodes[road["to_node"]]
            length = math.dist((a["x"], a["z"]), (b["x"], b["z"]))
            self.roads[road["id"]] = {
                **road, "length": round(length, 2), "congestion": 0.0,
                "blocked": False, "capacity": 1.0, "risk": 0.0,
            }

        for s in build_sensors():
            baseline = {
                "occupancy": 60.0, "temperature": 24.0, "energy": 40.0,
                "smoke": 2.0, "air_quality": 45.0, "humidity": 45.0,
                "traffic": 6.0, "parking": 55.0, "water": 40.0,
            }.get(s["type"], 0.0)
            self.sensors[s["id"]] = SensorState(
                id=s["id"], name=s["name"], type=s["type"], building_id=s["building_id"],
                unit=s["unit"], x=s["x"], z=s["z"], value=baseline, baseline=baseline,
                healthy=True, node_id=s.get("node_id"),
                sensor_code=s.get("sensor_code", ""), zone_id=s.get("zone_id"),
                y=s.get("y", 0.0), min_value=s.get("min_value"), max_value=s.get("max_value"),
                normal_min=s.get("normal_min"), normal_max=s.get("normal_max"),
            )

    # -------------------------------------------------------------- utilities
    @property
    def clock_hour(self) -> float:
        return (self.clock / 3600.0) % 24.0

    def exits_for(self, building_id: str) -> list[str]:
        return BUILDING_EXITS.get(building_id, [])

    def campus_occupancy(self) -> int:
        return sum(b.occupancy for b in self.buildings.values())

    def campus_capacity(self) -> int:
        return sum(b.capacity for b in self.buildings.values())

    def campus_energy(self) -> float:
        return sum(b.energy for b in self.buildings.values())

    def campus_temperature(self) -> float:
        temps = [b.temperature for b in self.buildings.values()]
        return sum(temps) / max(1, len(temps))

    def snapshot(self) -> dict:
        return {
            "clock": self.clock,
            "clock_hour": round(self.clock_hour, 3),
            "speed": self.speed,
            "sim_status": self.sim_status,
            "status": self.status,
            "recovery_progress": round(self.recovery_progress, 1),
            "buildings": [b.to_dict() for b in self.buildings.values()],
            "zones": [z.to_dict() for z in self.zones.values()],
            "sensors": [s.to_dict() for s in self.sensors.values()],
            "roads": list(self.roads.values()),
            "nodes": list(self.nodes.values()),
            "incidents": self.incidents,
            "risk": self.risk,
            "building_risk": self.building_risk,
            "predictions": self.predictions,
            "anomalies": self.anomalies,
            "recommendations": self.recommendations,
            "routes": self.routes,
            "route_plan": self.route_plan,
            "route_version": self.route_version,
            "evacuation": self.evacuation,
            "alerts": self.alerts[-10:],
            "active_sim": self.active_sim.to_dict() if self.active_sim else None,
            "metrics": self.metrics(),
            "system_health": self.system_health,
            "connected_clients": 0,
        }

    def metrics(self) -> dict:
        occ_pct = 100.0 * self.campus_occupancy() / max(1, self.campus_capacity())
        return {
            "occupancy": self.campus_occupancy(),
            "occupancy_pct": round(occ_pct, 1),
            "energy": round(self.campus_energy(), 1),
            "temperature": round(self.campus_temperature(), 1),
            "water": round(sum(s.value for s in self.sensors.values() if s.type == "water"), 1),
            "risk": round(self.risk.get("score", 0), 1),
            "risk_level": self.risk.get("level", "LOW"),
            "incidents": len([i for i in self.incidents if i["status"] == "ACTIVE"]),
            "people_at_risk": self.active_sim.people_at_risk if self.active_sim else 0,
            "anomalies": len(self.anomalies),
            "clock_hour": round(self.clock_hour, 2),
            "status": self.status,
            "recovery_progress": round(self.recovery_progress, 1),
        }


_state: TwinState | None = None


def _configured_seed() -> int:
    from app.core.config import settings
    return settings.SIMULATION_SEED if settings.SIMULATION_SEED is not None else settings.RANDOM_SEED


def get_state() -> TwinState:
    global _state
    if _state is None:
        _state = TwinState(seed=_configured_seed())
    return _state


def reset_state() -> TwinState:
    global _state
    _state = TwinState(seed=_configured_seed())
    return _state
