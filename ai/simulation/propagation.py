"""Zone-graph fire/smoke propagation model (no CFD).

Deterministic, cheap, visually convincing: fire spreads between zone graph
nodes with intensity and wind bias; smoke diffuses to neighbours and decays.

Zone dict fields consumed (matches `ZoneState.to_dict`):
    id, name, adjacent, local_x, local_z, fire, smoke, temperature,
    status, occupancy, building_id
"""

from __future__ import annotations

import math

WIND_VECTORS = {
    "N": (0.0, -1.0), "S": (0.0, 1.0), "E": (1.0, 0.0),
    "W": (-1.0, 0.0), "NE": (0.7071, -0.7071), "NW": (-0.7071, -0.7071),
    "SE": (0.7071, 0.7071), "SW": (-0.7071, 0.7071), "NONE": (0.0, 0.0),
}


def ignite(zones: dict[str, dict], ignition_id: str, intensity: float) -> dict | None:
    zone = zones.get(ignition_id)
    if not zone:
        return None
    zone["fire"] = max(zone.get("fire", 0.0), min(1.0, 0.35 + intensity / 14.0))
    zone["status"] = "FIRE"
    zone["temperature"] = max(zone.get("temperature", 24.0), 60.0 + intensity * 8)
    return {"zone_id": ignition_id, "message": f"Ignition in {zone.get('name', ignition_id)}"}


def step_fire(zones: dict[str, dict], *, dt: float, intensity: float,
              wind: str = "NONE", burn_rate: float = 1.0) -> list[dict]:
    """Advance fire + smoke one step. Returns event list."""
    events: list[dict] = []
    w = WIND_VECTORS.get(wind.upper(), (0.0, 0.0))
    power = max(0.2, intensity / 5.0)

    burning = [z for z in zones.values() if z.get("fire", 0) > 0.05]
    for z in burning:
        z["fire"] = min(1.0, z["fire"] + dt * 0.045 * power * burn_rate)
        z["smoke"] = min(300.0, z.get("smoke", 0.0) + dt * 6.0 * power)
        z["temperature"] = min(420.0, z.get("temperature", 24.0) + dt * 6.0 * power)

        for nid in z.get("adjacent", []):
            nb = zones.get(nid)
            if not nb:
                continue
            dx = nb.get("local_x", 0) - z.get("local_x", 0)
            dz = nb.get("local_z", 0) - z.get("local_z", 0)
            norm = math.hypot(dx, dz) or 1.0
            align = (dx / norm) * w[0] + (dz / norm) * w[1]
            wind_factor = 0.35 + 0.65 * ((align + 1.0) / 2.0)
            if w == (0.0, 0.0):
                wind_factor = 0.75
            spread = dt * 0.055 * power * wind_factor * (1.0 - nb.get("fire", 0.0)) * burn_rate
            if spread > 0 and nb.get("fire", 0.0) < 1.0:
                before = nb.get("fire", 0.0)
                nb["fire"] = min(1.0, nb.get("fire", 0.0) + spread)
                if before < 0.15 <= nb["fire"]:
                    events.append({
                        "zone_id": nid, "building_id": nb.get("building_id"),
                        "message": f"Fire spread to {nb.get('name', nid)}",
                    })
            nb["smoke"] = min(300.0, nb.get("smoke", 0.0) + dt * 3.0 * power * wind_factor)
            if nb.get("fire", 0) < 0.05 and nb.get("smoke", 0) > 8:
                nb["temperature"] = min(120.0, nb.get("temperature", 24.0) + dt * 1.6 * power)

    # decay for zones without active fire
    for z in zones.values():
        if z.get("fire", 0) <= 0.05 and z.get("smoke", 0) > 0:
            z["smoke"] = max(0.0, z["smoke"] - dt * 2.5)
        if z.get("fire", 0) <= 0.05 and z.get("temperature", 24) > 26:
            z["temperature"] = max(24.0, z["temperature"] - dt * 1.5)

    for z in zones.values():
        if z.get("fire", 0) >= 0.15:
            z["status"] = "FIRE"
        elif z.get("smoke", 0) >= 25:
            z["status"] = "SMOKE"
        elif z.get("smoke", 0) >= 6:
            z["status"] = "AFFECTED"
        elif z.get("status") in ("FIRE", "SMOKE", "AFFECTED"):
            z["status"] = "NORMAL"
    return events


def suppress(zones: dict[str, dict], dt: float, factor: float = 0.35) -> list[dict]:
    """Firefighting / recovery suppression step (gradual — never teleports)."""
    events = []
    for z in zones.values():
        if z.get("fire", 0) > 0:
            z["fire"] = max(0.0, z["fire"] - dt * factor)
            if z["fire"] == 0:
                events.append({"zone_id": z["id"], "message": f"Fire suppressed in {z.get('name', z['id'])}"})
        z["smoke"] = max(0.0, z.get("smoke", 0.0) - dt * 8.0)
        z["temperature"] = max(24.0, z.get("temperature", 24.0) - dt * 5.0)
        if z.get("fire", 0) < 0.15 and z.get("smoke", 0) < 6 and z.get("status") != "NORMAL":
            z["status"] = "NORMAL"
    return events


def zone_totals(zones: dict[str, dict], building_id: str | None = None) -> dict:
    """Aggregate fire-model state for a building (or all zones).

    people_at_risk          — raw occupants in affected zones (FIRE/SMOKE/AFFECTED)
    weighted_people_at_risk — severity-weighted occupancy (see fire_simulation)
    """
    from ai.simulation.fire_simulation import severity_weight, smoke_severity

    subset = [z for z in zones.values() if building_id is None or z.get("building_id") == building_id]
    burning = [z for z in subset if z.get("fire", 0) >= 0.15]
    affected = [z for z in subset if z.get("status") in ("FIRE", "SMOKE", "AFFECTED")]
    return {
        "total_zones": len(subset),
        "burning_zones": len(burning),
        "affected_zones": len(affected),
        "fire_fraction": (len(burning) / len(subset)) if subset else 0.0,
        "people_at_risk": sum(int(z.get("occupancy", 0)) for z in affected),
        "weighted_people_at_risk": int(round(sum(
            int(z.get("occupancy", 0)) * severity_weight(z.get("status", "NORMAL"))
            for z in affected))),
        "max_smoke": max((z.get("smoke", 0.0) for z in subset), default=0.0),
        "smoke_severity": smoke_severity(max((z.get("smoke", 0.0) for z in subset), default=0.0)),
        "max_fire": max((z.get("fire", 0.0) for z in subset), default=0.0),
        "max_temperature": max((z.get("temperature", 24.0) for z in subset), default=24.0),
    }
