"""Energy prediction model (Phase 5).

Versioned as `energy-rf-v1`: RandomForest over chronological energy series
with a deterministic seasonal-baseline fallback. The occupancy-ratio sibling
feature supplies cross-metric context when available.
"""

from __future__ import annotations

from typing import Any

from ai.prediction.prediction_service import forecast

VERSION = "energy-rf-v1"


def predict_energy(entity_id: str, entity_name: str,
                   hours: list[float], values: list[float], *,
                   upper_bound: float = 100.0,
                   horizons: tuple[int, ...] = (15, 30, 60),
                   occupancy_ratio: list[float] | None = None,
                   **kwargs: Any) -> list[dict[str, Any]]:
    return forecast(
        entity_id, "energy", entity_name, hours, values,
        horizons=horizons, lower_bound=0.0, upper_bound=float(upper_bound),
        sibling=occupancy_ratio, entity_type="building", **kwargs,
    )
