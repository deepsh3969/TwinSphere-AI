"""Extreme temperature model (Phase 6 §43) — explainable constants only."""

from __future__ import annotations

from typing import Any


def temperature_event(ambient_c: float = 38.0) -> dict[str, Any]:
    """Modifier set applied while the heat-wave scenario runs.

    temperature_offset  — added to indoor temperature targets (°C)
    energy_multiplier   — cooling-load multiplier on building energy
    ambient_target      — outdoor temperature target driving the event
    """
    offset = max(0.0, ambient_c - 29.0)  # 38°C ambient -> +9°C indoor offset
    return {
        "ambient_target": ambient_c,
        "temperature_offset": round(offset, 1),
        "energy_multiplier": 1.35,
    }
