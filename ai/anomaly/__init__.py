"""Anomaly detection over simulated sensor telemetry.

Phase 5 layered architecture (spec §55):
  L1 domain thresholds -> L2 rolling statistics (z-score / rate-of-change) ->
  L3 Isolation Forest (optional, sample-gated), plus cross-metric
  (multivariate) relation checks.

`detect_anomalies` keeps the Phase 1-3 contract for existing callers; new
code should use `detect` (all layers + cold-start status) or `AnomalyTracker`
(stateful persistence / decay for the AI scheduler).
"""

from __future__ import annotations

from typing import Any

from ai.anomaly.anomaly_detector import (
    BANDS,
    BAND_SEVERITY,
    THRESHOLDS,
    backend_name,
    detect,
    score_band,
    threshold_layer,
)
from ai.anomaly.anomaly_service import AnomalyTracker, filtered
from ai.anomaly.feature_engineering import (
    baseline_key,
    rate_of_change_pct,
    rolling_stats,
    rolling_zscore,
)

__all__ = [
    "BANDS", "BAND_SEVERITY", "THRESHOLDS", "AnomalyTracker",
    "backend_name", "baseline_key", "detect", "detect_anomalies",
    "filtered", "rate_of_change_pct", "rolling_stats", "rolling_zscore",
    "score_band", "threshold_layer",
]


def detect_anomalies(sensor_history: dict[str, list[float]],
                     sensor_meta: dict[str, dict],
                     z_threshold: float = 2.5,
                     use_isolation_forest: bool = True) -> list[dict[str, Any]]:
    """Phase 1-3 compatible entry point (single-shot, no tracker state).

    Uses the full layered detector with the legacy statistical gate so
    existing integrations and tests keep their semantics.
    """
    result = detect(
        sensor_history, sensor_meta,
        z_threshold=z_threshold,
        score_threshold=min(35.0, abs(z_threshold) * 14.0),
        min_samples=6,
        use_isolation_forest=use_isolation_forest,
    )
    return result["anomalies"]
