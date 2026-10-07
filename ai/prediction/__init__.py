"""Occupancy / energy prediction (Phase 5 architecture).

Pipeline: feature engineering -> chronological split -> RandomForest
(`occupancy-rf-v1` / `energy-rf-v1`, joblib-persisted) with a deterministic
seasonal-baseline fallback labelled model=BASELINE. Confidence is derived
from measured hold-out error — it is never overstated.

`predict_series` keeps the Phase 1-3 single-horizon contract for existing
callers; the scheduler uses `forecast` for all configured horizons.
"""

from __future__ import annotations

from typing import Any

from ai.prediction.energy_model import VERSION as ENERGY_VERSION, predict_energy
from ai.prediction.feature_engineering import (
    FEATURE_NAMES,
    build_features,
    build_matrix,
    chronological_split,
    regression_metrics,
)
from ai.prediction.occupancy_model import VERSION as OCCUPANCY_VERSION, predict_occupancy
from ai.prediction.prediction_service import (
    ModelBundle,
    backend_name,
    baseline_forecast,
    clear_cache,
    forecast,
    get_bundle,
    load_model,
    save_model,
    train_bundle,
)

__all__ = [
    "ENERGY_VERSION", "FEATURE_NAMES", "ModelBundle", "OCCUPANCY_VERSION",
    "backend_name", "baseline_forecast", "build_features", "build_matrix",
    "chronological_split", "clear_cache", "forecast", "get_bundle",
    "load_model", "predict_energy", "predict_occupancy", "predict_series",
    "regression_metrics", "save_model", "train_bundle",
]


def predict_series(hours: list[float], values: list[float], *,
                   horizon_min: int = 20, metric: str = "occupancy",
                   entity_id: str = "", entity_name: str = "",
                   lower_bound: float = 0.0, upper_bound: float = 100.0) -> dict[str, Any]:
    """Phase 1-3 compatible single-horizon forecast."""
    records = forecast(
        entity_id, metric, entity_name, hours, values,
        horizons=(horizon_min,), lower_bound=lower_bound, upper_bound=upper_bound,
    )
    return records[0]
