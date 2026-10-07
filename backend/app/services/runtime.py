"""Runtime orchestrator: sensor ticks, simulation ticks, AI refresh, broadcasts."""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import settings
from app.services import (
    ai_service, analyst_service, persistence, realtime, route_service, sensor_engine,
)
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.simulation_engine import tick_simulation
from app.services.state import CLOCK_RATE, SIM_STATUS_RUNNING, TwinState, get_state
from app.websocket.manager import manager

log = logging.getLogger("twinsphere.runtime")

BROADCAST_LIGHT = {"type", "payload"}


class Runtime:
    def __init__(self) -> None:
        self.state: TwinState = get_state()
        self._running = False
        self._task: asyncio.Task | None = None
        self._sensor_acc = 0.0
        self._sim_acc = 0.0
        self._idle_acc = 0.0
        self._ai_acc = 0.0
        self._tick = 0
        self._prev_sensor: dict[str, tuple[float, bool]] = {}
        self._last_analyst = 0.0
        self._last_risk_level = "LOW"
        # Phase 6: simulation engine health (failure isolation §67) + zone diff
        self._sim_failures = 0
        self._prev_zone_status: dict[str, str] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="twinsphere-runtime")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        state = self.state
        last = time.monotonic()
        log.info("Runtime loop started (sim=%s, speed=%sx, clock=%s)",
                 state.sim_status, state.speed, state.clock)
        while self._running:
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                break
            now = time.monotonic()
            dt_real = min(2.0, now - last)
            last = now

            if state.sim_status != SIM_STATUS_RUNNING:
                # Paused/stopped (Phase 4): freeze clock + tick accumulators but
                # keep pushing state heartbeats so clients stay warm.
                self._sensor_acc = 0.0
                self._sim_acc = 0.0
                self._idle_acc += dt_real
                await self._flush_sim_events()
                if self._idle_acc >= settings.SENSOR_TICK_SECONDS:
                    self._idle_acc = 0.0
                    await self._broadcast_state()
                continue
            self._idle_acc = 0.0

            speed = max(0.1, state.speed)
            state.clock += dt_real * CLOCK_RATE * speed
            self._sensor_acc += dt_real
            self._sim_acc += dt_real
            self._ai_acc += dt_real

            await self._flush_sim_events()

            if self._sim_acc >= settings.SIM_TICK_SECONDS:
                dts = self._sim_acc
                self._sim_acc = 0.0
                await self._sim_step(dts * CLOCK_RATE * speed)

            if self._sensor_acc >= settings.SENSOR_TICK_SECONDS:
                self._sensor_acc = 0.0
                await self._sensor_step()

            # Phase 5: AI analysis scheduler (anomalies -> predictions ->
            # risk -> ai.*/risk.* events). Wall-clock cadence, isolated so a
            # failure degrades only the AI layer.
            if settings.AI_ENABLED and self._ai_acc >= settings.AI_ANALYSIS_INTERVAL_SECONDS:
                self._ai_acc = 0.0
                await self._ai_cycle()

    def on_control_change(self) -> None:
        """Realtime control routes call this so a resumed run starts a fresh
        tick window instead of flushing a stale partial accumulator."""
        self._sensor_acc = 0.0
        self._sim_acc = 0.0
        self._idle_acc = 0.0
        self._ai_acc = 0.0

    async def _sensor_step(self) -> None:
        from datetime import datetime, timezone
        state = self.state
        self._tick += 1
        state.tick_count = self._tick
        try:
            sensor_engine.tick_sensors(state, 1.0)
            state.last_tick_at = datetime.now(timezone.utc).isoformat()
        except Exception:
            log.exception("sensor tick failed")
        try:
            compute_risk(state)
        except Exception:
            log.exception("risk computation failed")
        ai_service.maybe_sample_series(state)
        self._record_metrics()

        # Phase 5: anomaly/prediction refresh moved to the AI scheduler
        # (run_ai_cycle on AI_ANALYSIS_INTERVAL_SECONDS cadence).
        if self._tick % 8 == 0:
            try:
                compute_routes(state, primary_building=state.active_sim.target_id
                               if state.active_sim else None)
            except Exception:
                log.exception("route computation failed")
        # Phase 7 §10: dynamic route revalidation (cheap signature check;
        # recalculates + emits route.* events only on real state changes)
        try:
            route_service.revalidate(state)
        except Exception:
            log.exception("route revalidation failed")
        persist_every = max(1, int(round(
            settings.SIMULATION_PERSIST_INTERVAL / max(0.1, settings.SENSOR_TICK_SECONDS))))
        if self._tick % persist_every == 0:
            try:
                persistence.persist_readings(state)
            except Exception:
                log.exception("reading persistence failed")
        if self._tick % 15 == 0:
            try:
                persistence.persist_risk(state)
            except Exception:
                pass
        if self._tick % 40 == 0:
            try:
                persistence.persist_predictions(state)
                persistence.persist_routes(state)
            except Exception:
                pass
        if self._tick % 30 == 0 or state.risk.get("level") != self._last_risk_level:
            risk_changed = state.risk.get("level") != self._last_risk_level
            self._last_risk_level = state.risk.get("level", "LOW")
            # Phase 8 §37: fire-and-forget (cooldown/cache inside); the LLM
            # call never blocks a simulation tick.
            try:
                analyst_service.schedule(
                    state, trigger="risk_change" if risk_changed else "cadence")
            except Exception:
                log.exception("analyst refresh failed")

        state.system_health.update({
            "backend": True,
            "database": True,
            "simulation": self._sim_failures == 0 and (
                state.active_sim is None or state.active_sim.status != "ERROR"),
            "ai": True,
        })
        await self._broadcast_telemetry()
        await self._broadcast_state()

    async def _ai_cycle(self) -> None:
        """Phase 5 AI scheduler unit: analysis + ai.*/risk.* event fan-out.

        Failure is contained here: the AI layer flips to degraded mode while
        simulation, WebSocket and REST keep running untouched.
        """
        state = self.state
        try:
            result = ai_service.run_ai_cycle(state)
        except Exception as exc:
            log.exception("AI analysis cycle failed")
            try:
                ai_service.mark_ai_degraded(state, str(exc) or exc.__class__.__name__)
            except Exception:
                pass
            return

        try:
            await manager.emit("ai.anomaly", {
                "anomalies": result["anomalies"],
                "count": len(result["anomalies"]),
                "new": [a["id"] for a in result.get("new_anomalies", [])],
                "data_quality": result["data_quality"],
                "sensor_status": result["sensor_status"],
                "clock": state.clock,
            })
            await manager.emit("ai.prediction", {
                "predictions": result["predictions"],
                "count": len(result["predictions"]),
                "horizons": list(settings.PREDICTION_HORIZONS),
                "clock": state.clock,
            })
            pub = result["risk"]
            await manager.emit("risk.update", {
                "campus": pub.get("campus"),
                "buildings": {k: v for k, v in pub.items() if k != "campus"},
                "raw_level": state.risk.get("level"),
                "clock": state.clock,
            })
        except Exception:
            log.exception("AI event broadcast failed")

    async def _broadcast_telemetry(self) -> None:
        """Phase 4 granular live events (spec §10/§11), emitted after each tick."""
        state = self.state
        changed: list[dict] = []
        for sid, s in state.sensors.items():
            cur = (round(s.value, 2), s.healthy)
            prev = self._prev_sensor.get(sid)
            self._prev_sensor[sid] = cur
            if prev != cur:
                changed.append({
                    "id": sid, "value": cur[0], "status": s.status,
                    "healthy": s.healthy, "unit": s.unit, "updated_at": s.updated_at,
                })
        if changed:
            await manager.emit("sensor.batch_update", {
                "sensors": changed, "count": len(changed),
                "clock": state.clock, "clock_hour": round(state.clock_hour, 3),
            })

        m = state.metrics()
        await manager.emit("occupancy.update", {
            "occupancy": m["occupancy"], "occupancy_pct": m["occupancy_pct"],
            "capacity": state.campus_capacity(),
            "buildings": [
                {"id": b.id, "occupancy": b.occupancy,
                 "occupancy_pct": round(100.0 * b.occupancy / max(1, b.capacity), 1)}
                for b in state.buildings.values()
            ],
        })
        await manager.emit("building.update", {"buildings": [
            {
                "id": b.id, "occupancy": b.occupancy,
                "occupancy_pct": round(100.0 * b.occupancy / max(1, b.capacity), 1),
                "temperature": round(b.temperature, 1), "humidity": round(b.humidity, 1),
                "energy": round(b.energy, 1), "water": round(b.water, 1),
                "smoke": round(b.smoke, 1), "air_quality": round(b.air_quality, 0),
                "risk": round(b.risk, 1), "risk_level": b.risk_level,
                "sensor_health": b.sensor_health, "status": b.status,
                "power": b.power, "backup_power": b.backup_power,
            }
            for b in state.buildings.values()
        ]})
        await realtime.broadcast_simulation_status(state)
        await realtime.broadcast_system_status(state)

    def _record_metrics(self) -> None:
        from datetime import datetime, timezone
        state = self.state
        m = state.metrics()
        now = datetime.now(timezone.utc).isoformat()
        for key, value in (
            ("risk", m["risk"]), ("occupancy", m["occupancy_pct"]),
            ("energy", m["energy"]), ("temperature", m["temperature"]),
            ("water", m["water"]), ("incidents", m["incidents"]),
        ):
            bucket = state.metric_history.setdefault(key, [])
            bucket.append({"t": now, "value": value})
            if len(bucket) > 600:
                del bucket[: len(bucket) - 600]

    async def _sim_step(self, dt_virtual: float) -> None:
        state = self.state
        if state.active_sim is None:
            return
        try:
            events = tick_simulation(state, dt_virtual)
        except Exception:
            # §67 failure isolation: degrade only the simulation engine flag —
            # twin, sensors, AI and WebSocket keep running.
            self._sim_failures += 1
            state.system_health["simulation"] = False
            log.exception("simulation tick failed")
            return
        self._sim_failures = 0
        state.system_health["simulation"] = True
        sim = state.active_sim
        sim.peak_risk = max(sim.peak_risk, state.risk.get("score", 0.0))
        for ev in events:
            await manager.broadcast("event", ev)
        if sim.status in ("RECOVERING", "AWAITING_RECOVERY", "RUNNING"):
            await manager.broadcast("simulation", sim.to_dict())
        await self._emit_simulation_telemetry(sim)

    async def _emit_simulation_telemetry(self, sim) -> None:
        """Phase 6 §27/§28 — typed simulation.tick / zone_update / risk_update."""
        state = self.state
        try:
            data = sim.to_dict()
            b = state.buildings.get(sim.target_id or "")
            data["risk"] = round(state.risk.get("score", 0.0), 1)
            data["risk_level"] = state.risk.get("level", "LOW")
            data["speed"] = state.speed
            data["building_smoke"] = round(b.smoke, 1) if b else None
            data["building_temperature"] = round(b.temperature, 1) if b else None
            data["building_status"] = b.status if b else None
            await manager.emit("simulation.tick", data)

            changed = []
            for zid, z in state.zones.items():
                prev = self._prev_zone_status.get(zid)
                if prev != z.status:
                    self._prev_zone_status[zid] = z.status
                    if prev is not None:
                        changed.append({"id": zid, "building_id": z.building_id,
                                        "status": z.status, "fire": round(z.fire, 3),
                                        "smoke": round(z.smoke, 2),
                                        "temperature": round(z.temperature, 1),
                                        "risk_level": z.risk_level})
            if changed:
                await manager.emit("simulation.zone_update", {
                    "simulation_id": sim.id, "changed": changed,
                    "count": len(changed), "clock": state.clock,
                })

            await manager.emit("simulation.risk_update", {
                "simulation_id": sim.id, "risk": round(state.risk.get("score", 0.0), 1),
                "level": state.risk.get("level", "LOW"),
                "target_id": sim.target_id,
                "target_risk": round((state.building_risk.get(sim.target_id or "")
                                      or {}).get("score", 0.0), 1),
                "people_at_risk": sim.people_at_risk,
                "clock": state.clock,
            })
        except Exception:
            log.exception("simulation telemetry broadcast failed")

    async def _flush_sim_events(self) -> None:
        """Drain typed simulation.* lifecycle events queued by the engine."""
        state = self.state
        if not state.pending_sim_events:
            return
        queued, state.pending_sim_events = state.pending_sim_events, []
        for item in queued[:20]:
            try:
                await manager.emit(item["event"], item["data"])
            except Exception:
                log.exception("simulation event broadcast failed")

    async def _broadcast_state(self) -> None:
        try:
            payload = self.state.snapshot()
            payload["connected_clients"] = manager.connected
            await manager.broadcast("state", payload)
        except Exception:
            log.exception("broadcast failed")

    async def push_state(self) -> None:
        """Public wrapper used by realtime control routes after a status change."""
        await self._broadcast_state()


runtime = Runtime()
