"""Crowd surge model (Phase 6 §39) — occupancy/density only, no human agents."""

from __future__ import annotations

from typing import Any


def crowd_density(occupancy: int, capacity: int) -> dict[str, Any]:
    """Capacity utilisation state + crowd risk indicator (0..100)."""
    ratio = occupancy / max(1, capacity)
    if ratio >= 1.0:
        state, label = "OVERLOADED", "Overloaded"
    elif ratio >= 0.8:
        state, label = "WARNING", "Warning"
    else:
        state, label = "SAFE", "Safe"
    risk = min(100.0, max(0.0, (ratio - 0.7)) * 140.0) if ratio > 0.7 else min(30.0, ratio * 30.0)
    return {"ratio": round(ratio, 3), "state": state, "label": label, "risk": round(risk, 1)}


def crowd_occupancy_multiplier(increase_pct: float, elapsed: float, duration: float) -> float:
    """Ramped occupancy multiplier: +X% fully applied by 40% of the run."""
    increase = float(increase_pct) / 100.0
    ramp = min(1.0, elapsed / max(30.0, duration * 0.4))
    return 1.0 + increase * ramp
