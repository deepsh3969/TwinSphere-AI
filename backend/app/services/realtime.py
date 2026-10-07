"""Phase 4 — realtime simulation status payloads shared by runtime + routes.

The realtime simulator (campus telemetry clock) is distinct from scenario
simulations (`SimulationState`): it can be started/paused/resumed/reset and
runs at 1x/2x/5x/10x speed (spec §36). These helpers build the authoritative
status payload pushed over WebSocket as `simulation.status` / `system.status`.
"""

from __future__ import annotations

from app.core.config import settings
from app.services.state import TwinState
from app.websocket.manager import manager


def simulation_status(state: TwinState, connected: int | None = None) -> dict:
    sim = state.active_sim
    return {
        "status": state.sim_status,
        "speed": state.speed,
        "simulation_time": round(state.clock, 1),
        "clock": round(state.clock, 1),
        "clock_hour": round(state.clock_hour, 3),
        "last_tick": state.last_tick_at,
        "tick_count": state.tick_count,
        "sensor_interval": settings.SENSOR_TICK_SECONDS,
        "enabled": settings.SIMULATION_ENABLED,
        "connected_clients": manager.connected if connected is None else connected,
        "data_source": "SIMULATED",
        "seed": state.seed,
        "scenario": sim.scenario if sim else None,
        "scenario_status": sim.status if sim else None,
    }


def system_status(state: TwinState, connected: int | None = None) -> dict:
    active_incidents = sum(1 for i in state.incidents if i.get("status") == "ACTIVE")
    return {
        "backend": True,
        "database": bool(state.system_health.get("database", True)),
        "websocket": settings.WEBSOCKET_ENABLED,
        "simulator": state.sim_status,
        "simulation_engine": bool(state.system_health.get("simulation", True)),
        "ai": bool(state.system_health.get("ai", True)),
        "connected_clients": manager.connected if connected is None else connected,
        "clock_hour": round(state.clock_hour, 3),
        "speed": state.speed,
        "risk_level": state.risk.get("level", "LOW"),
        "incidents": active_incidents,
        "metrics": state.metrics(),
    }


async def broadcast_simulation_status(state: TwinState) -> None:
    await manager.emit("simulation.status", simulation_status(state))


async def broadcast_system_status(state: TwinState) -> None:
    await manager.emit("system.status", system_status(state))
