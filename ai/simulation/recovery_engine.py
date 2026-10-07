"""Gradual recovery model (Phase 6 §36-§38).

Recovery must never teleport (45°C must pass 42, 39, 36 ... on its way to 27).
`glide` is the shared exponential tail used for scalar state; the fire model's
`suppress` handles zone fire/smoke/temperature linearly per tick.
"""

from __future__ import annotations

RECOVERY_TAU = 22.0  # seconds: ~63% of the remaining gap closed per tau


def glide(current: float, baseline: float, dt: float, tau: float = RECOVERY_TAU) -> float:
    """Move `current` a fraction of the way to `baseline` — continuous, no jumps."""
    if tau <= 0:
        return baseline
    return current + (baseline - current) * (1.0 - pow(2.718281828, -dt / tau))


def recovery_percent(elapsed: float, duration: float) -> float:
    """0..100 recovery progress from elapsed vs configured duration."""
    if duration <= 0:
        return 100.0
    return max(0.0, min(100.0, 100.0 * elapsed / duration))


def is_complete(elapsed: float, duration: float) -> bool:
    return recovery_percent(elapsed, duration) >= 100.0
