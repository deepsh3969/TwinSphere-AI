"""Deterministic campus risk engine (Phase 5 architecture).

Risk score 0-100. Levels: LOW(0-20) MODERATE(21-40) ELEVATED(41-60)
HIGH(61-80) CRITICAL(81-100). Weighted factors with documented weights
(`risk_factors`), entity hierarchy (`hierarchy_risk`) and publication
stability (`RiskStability` smoothing + hysteresis).

Risk is a weighted operational indicator — NOT a probability of disaster.
"""

from __future__ import annotations

from ai.risk.risk_engine import (
    BUILDING_WEIGHTS,
    CAMPUS_WEIGHTS,
    LEVELS,
    building_risk,
    campus_risk,
    hierarchy_risk,
    risk_level,
)
from ai.risk.risk_factors import building_factors, campus_factors, sensor_risk
from ai.risk.risk_service import RiskStability

__all__ = [
    "BUILDING_WEIGHTS", "CAMPUS_WEIGHTS", "LEVELS", "RiskStability",
    "building_factors", "building_risk", "campus_factors", "campus_risk",
    "hierarchy_risk", "risk_level", "sensor_risk",
]
