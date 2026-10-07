"""Occupancy prediction model (Phase 5).

Versioned as `occupancy-rf-v1`: RandomForest over chronological occupancy
series with a deterministic seasonal-baseline fallback. Bounds clamp the
forecast to physical occupancy limits (0..capacity).
"""

from __future__ import annotations

from typing import Any

from ai.prediction.prediction_service import forecast

VERSION = "occupancy-rf-v1"


def predict_occupancy(entity_id: str, entity_name: str,
                      hours: list[float], values: list[float], *,
                      capacity: float = 100.0,
                      horizons: tuple[int, ...] = (15, 30, 60),
                      occupancy_ratio: list[float] | None = None,
                      **kwargs: Any) -> list[dict[str, Any]]:
    return forecast(
        entity_id, "occupancy", entity_name, hours, values,
        horizons=horizons, lower_bound=0.0, upper_bound=float(capacity),
        sibling=occupancy_ratio, entity_type="building", **kwargs,
    )
