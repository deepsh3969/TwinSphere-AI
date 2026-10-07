"""Zone/grid scenario models for campus emergencies (no CFD) — Phase 6.

Submodules hold the pure, deterministic models; this package re-exports the
public API so existing `from ai.simulation import ...` imports keep working:

    propagation.py                  fire/smoke spread on the zone graph
    fire_simulation.py              intensity/wind validation, bands, status
    crowd_simulation.py             density + occupancy multiplier
    power_failure_simulation.py     mains loss / backup state
    road_closure_simulation.py      blocked roads + traffic redistribution
    extreme_temperature_simulation.py  heat-wave modifiers
    recovery_engine.py              gradual (non-teleporting) recovery
"""

from __future__ import annotations

from ai.simulation.crowd_simulation import crowd_density, crowd_occupancy_multiplier
from ai.simulation.extreme_temperature_simulation import temperature_event
from ai.simulation.fire_simulation import (
    INTENSITY_LEVELS,
    WIND_DIRECTIONS,
    building_status,
    intensity_label,
    severity_weight,
    smoke_band,
    smoke_severity,
    validate_fire_params,
)
from ai.simulation.power_failure_simulation import backup_state, power_failure_effects
from ai.simulation.propagation import WIND_VECTORS, ignite, step_fire, suppress, zone_totals
from ai.simulation.recovery_engine import glide, is_complete, recovery_percent
from ai.simulation.road_closure_simulation import close_road, reopen_road, road_impact

__all__ = [
    "INTENSITY_LEVELS", "WIND_DIRECTIONS", "WIND_VECTORS",
    "backup_state", "building_status", "close_road", "crowd_density",
    "crowd_occupancy_multiplier", "glide", "ignite", "intensity_label",
    "is_complete", "power_failure_effects", "reopen_road", "recovery_percent",
    "road_impact", "severity_weight", "smoke_band", "smoke_severity",
    "step_fire", "suppress", "temperature_event", "validate_fire_params",
    "zone_totals",
]
