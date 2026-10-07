"""Sensor simulation engine.

Values follow realistic bounded behaviour: diurnal occupancy curves, energy
correlated with occupancy, gradual temperature drift with noise, parking and
traffic correlated with campus activity. A random seed makes runs repeatable.
"""

from __future__ import annotations

import math

from app.services.state import (
    START_CLOCK,
    BuildingState,
    SimulationContext,
    TwinState,
    ZoneState,
    build_simulation_context,
)

BUILDING_PROFILE = {
    "admin": {"base": 0.62, "morning": 0.85, "lunch": 0.45, "evening": 0.25},
    "eng": {"base": 0.70, "morning": 0.92, "lunch": 0.55, "evening": 0.35},
    "cs": {"base": 0.66, "morning": 0.90, "lunch": 0.52, "evening": 0.42},
    "lib": {"base": 0.60, "morning": 0.72, "lunch": 0.62, "evening": 0.70},
    "canteen": {"base": 0.55, "morning": 0.25, "lunch": 0.95, "evening": 0.40},
    "clinic": {"base": 0.40, "morning": 0.70, "lunch": 0.60, "evening": 0.30},
}


def occupancy_curve(hour: float, profile: dict) -> float:
    """Fraction of capacity that would normally be present at `hour`."""
    h = hour % 24
    base = profile["base"]
    if h < 5:
        frac = 0.03
    elif h < 8:
        frac = 0.03 + (h - 5) / 3 * (profile["morning"] * 0.75 - 0.03)
    elif h < 12:
        frac = profile["morning"] * (0.94 + 0.06 * math.sin((h - 8) * 1.5))
    elif h < 13.5:
        frac = profile["lunch"]
    elif h < 17:
        frac = base * (0.95 + 0.08 * math.sin((h - 13.5)))
    elif h < 20:
        frac = profile["evening"] + (base - profile["evening"]) * max(0.0, 1 - (h - 17) / 3) * 0.4
    else:
        frac = max(0.04, profile["evening"] * (1 - (h - 20) / 6) * 0.6)
    return max(0.0, min(1.0, frac))


def outdoor_temperature(hour: float) -> float:
    return 19.0 + 9.0 * math.sin(math.pi * max(0.0, min(1.0, (hour - 5.0) / 14.0)))


def _noise(state: TwinState, scale: float) -> float:
    return (state.rng.random() - 0.5) * 2.0 * scale


def distribute_building_zones(state: TwinState, b: BuildingState,
                              ctx: SimulationContext | None = None) -> list[ZoneState]:
    """Spread a building's occupancy across its zones proportionally (capped)."""
    zones = [z for z in state.zones.values() if z.building_id == b.id]
    total_cap = sum(z.capacity for z in zones) or 1
    remaining = b.occupancy
    for i, z in enumerate(zones):
        share = int(b.occupancy * z.capacity / total_cap)
        if i == len(zones) - 1:
            share = max(0, remaining)
        z.occupancy = max(0, min(z.capacity, share))
        remaining -= share
    if ctx and ctx.blocked_zones:
        for z in zones:
            if z.id in ctx.blocked_zones:
                z.occupancy = 0
    return zones


def reset_telemetry(state: TwinState) -> None:
    """Restore telemetry to baseline at the start-of-day clock (realtime reset)."""
    state.clock = START_CLOCK
    state.last_tick_at = None
    for s in state.sensors.values():
        s.value = s.baseline
        s.healthy = True
        s.updated_at = state.clock
    for b in state.buildings.values():
        profile = BUILDING_PROFILE.get(b.id, BUILDING_PROFILE["eng"])
        b.occupancy = int(b.capacity * occupancy_curve(state.clock_hour, profile))
        b.temperature = 24.0
        b.humidity = 45.0
        b.energy = round(b.capacity * 0.06, 1)
        b.smoke = 0.0
        b.air_quality = 42.0
        b.water = 0.0
        distribute_building_zones(state, b)
    state.sim_context = build_simulation_context(state)


def tick_sensors(state: TwinState, dt_virtual: float) -> None:
    hour = state.clock_hour
    outdoor = outdoor_temperature(hour)
    ctx = state.sim_context = build_simulation_context(state)
    temp_event = bool(ctx.active and ctx.scenario == "temperature")
    power_target = ctx.target_id if (ctx.active and ctx.scenario == "power") else None

    for b in state.buildings.values():
        profile = BUILDING_PROFILE.get(b.id, BUILDING_PROFILE["eng"])
        frac = occupancy_curve(hour, profile)
        target_occ = int(b.capacity * frac)

        if ctx.active and ctx.target_id == b.id:
            if ctx.scenario == "crowd":
                cap = ctx.occupancy_cap_fraction or 1.15
                target_occ = int(min(b.capacity * cap, b.capacity * frac * ctx.occupancy_multiplier))
            elif ctx.scenario == "fire":
                target_occ = max(0, int(b.occupancy + ctx.occupancy_delta))

        # smooth approach (occupied buildings change gradually)
        delta = target_occ - b.occupancy
        step = max(1, int(abs(delta) * 0.08))
        b.occupancy += step if delta > 0 else -step
        b.occupancy = max(0, min(int(b.capacity * 1.2), b.occupancy))

        # distribute across zones proportionally
        zones = distribute_building_zones(state, b, ctx)

        if power_target == b.id and ctx.status == "RUNNING":
            b.power = False
            b.backup_power = b.has_backup_power
            b.status = "POWER_FAILURE"

        occ_load = b.occupancy / max(1, b.capacity)
        working = 1.0 if 7 <= hour <= 19 else 0.35
        energy_target = (b.capacity * 0.055 * (0.35 + 0.75 * occ_load) * working)
        if b.power:
            if temp_event and b.id in ({ctx.target_id} | {"eng", "cs", "lib"}):
                energy_target *= ctx.energy_multiplier  # cooling load
            b.energy += (energy_target - b.energy) * 0.12 + _noise(state, 1.2)
            b.energy = max(0.0, b.energy)
        else:
            b.energy += ((b.capacity * 0.006 if b.backup_power else 0.0) - b.energy) * 0.3

        base_temp = outdoor * 0.35 + 19.5 + occ_load * 3.0
        if ctx.temperature_offset:
            base_temp += ctx.temperature_offset
        if ctx.active and ctx.scenario == "fire" and b.id == ctx.target_id:
            # Phase 6 §15: zone fire heat feeds building/sensor temperature.
            # Scaled by zone heat (distance proxy: far zones contribute less
            # because only the hottest zone drives the cap) and capped so
            # sensor values stay in a plausible instrument range.
            zone_heat = max((z.temperature for z in zones), default=24.0)
            if zone_heat > 30.0:
                base_temp += min(30.0, (zone_heat - 24.0) * 0.25)
        if not b.power and not b.backup_power:
            base_temp += 3.0
        if b.smoke > 5:
            base_temp += b.smoke * 0.05
        b.temperature += (base_temp - b.temperature) * 0.06 + _noise(state, 0.12)
        b.temperature = max(0.0, b.temperature)

        b.humidity += ((52 - outdoor * 0.4) - b.humidity) * 0.05 + _noise(state, 0.6)

        fire_smoke = sum(z.smoke for z in zones if z.building_id == b.id) * ctx.smoke_multiplier
        b.smoke += ((fire_smoke / max(1, len(zones))) - b.smoke) * 0.25
        b.smoke = max(0.0, b.smoke)

        aqi_target = 42 + 18 * max(0.0, math.sin((hour - 6) / 12 * math.pi)) + b.smoke * 1.6
        b.air_quality += (aqi_target - b.air_quality) * 0.1 + _noise(state, 1.5)
        b.air_quality = max(0.0, b.air_quality)

        b.water = max(0.0, (b.occupancy / max(1, b.capacity)) * 40 * working + _noise(state, 1.5))

        unhealthy = sum(1 for s in state.sensors.values() if s.building_id == b.id and not s.healthy)
        total = max(1, sum(1 for s in state.sensors.values() if s.building_id == b.id))
        b.sensor_health = round(100.0 * (1 - unhealthy / total), 1)

    # campus-wide sensors
    campus_occ_pct = 100.0 * state.campus_occupancy() / max(1, state.campus_capacity())
    for s in state.sensors.values():
        if s.type == "occupancy" and s.building_id:
            s.value = 100.0 * state.buildings[s.building_id].occupancy / max(1, state.buildings[s.building_id].capacity)
        elif s.type == "temperature" and s.building_id:
            s.value = state.buildings[s.building_id].temperature
        elif s.type == "energy" and s.building_id:
            s.value = state.buildings[s.building_id].energy
        elif s.type == "smoke" and s.building_id:
            s.value = state.buildings[s.building_id].smoke
        elif s.type == "air_quality" and s.building_id:
            s.value = state.buildings[s.building_id].air_quality
        elif s.type == "humidity" and s.building_id:
            s.value = state.buildings[s.building_id].humidity
        elif s.type == "temperature" and not s.building_id:
            s.value = outdoor_temperature(hour) + _noise(state, 0.3)
        elif s.type == "traffic":
            peak = 1.0
            if 8 <= hour <= 9.5 or 17 <= hour <= 18.5:
                peak = 2.2
            elif 12.5 <= hour <= 13.5:
                peak = 1.6
            elif hour < 6 or hour > 21:
                peak = 0.25
            road = state.roads.get(s.node_id or "", {})
            if road.get("blocked") or s.node_id in ctx.blocked_roads:
                s.value = 0.0
            else:
                base = 6.0 * peak * (1 + road.get("congestion", 0.0))
                s.value = max(0.0, base + _noise(state, 1.4))
        elif s.type == "parking":
            target = campus_occ_pct * 0.95
            s.value += (target - s.value) * 0.1 + _noise(state, 1.0)
            s.value = max(0.0, min(100.0, s.value))
        elif s.type == "water":
            target = sum(b.water for b in state.buildings.values()) + 20
            s.value += (target - s.value) * 0.15 + _noise(state, 2.0)
            s.value = max(0.0, s.value)

        if ctx.scenario == "power" and ctx.status in ("RUNNING", "RECOVERING"):
            if s.building_id == ctx.target_id and not state.buildings[s.building_id].power and s.type in ("occupancy", "temperature"):
                if state.rng.random() < 0.02:
                    s.healthy = not s.healthy
                    state.buildings[s.building_id].sensor_health = max(
                        0.0, state.buildings[s.building_id].sensor_health - 12
                    )

        s.updated_at = state.clock
        s.history.append(round(s.value, 2))
        if len(s.history) > 180:
            del s.history[: len(s.history) - 180]


def seed_history_values(hour: float, buildings_snapshot: dict) -> dict:
    """Deterministic 24h backfill used for prediction/anomaly warm-up."""
    out: dict[str, list[float]] = {}
    for bid, meta in buildings_snapshot.items():
        profile = BUILDING_PROFILE.get(meta["type_hint"], BUILDING_PROFILE["eng"])
        series = []
        for step in range(96):
            h = (hour - (95 - step) * 0.25) % 24
            frac = occupancy_curve(h, profile)
            series.append(round(meta["capacity"] * frac, 1))
        out[bid] = series
    return out
