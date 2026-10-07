"""Feature engineering for anomaly detection (Phase 5).

Pure, deterministic helpers: rolling statistics, rate-of-change, time-of-day
baseline keys and the feature matrix consumed by the Isolation Forest layer.
"""

from __future__ import annotations

import statistics
from typing import Any

DEFAULT_WINDOW = 24

# time-of-day buckets (2h wide) used for per-time-of-day baselines
BUCKET_HOURS = 2


def rolling_stats(values: list[float], window: int = DEFAULT_WINDOW) -> tuple[float, float]:
    """(mean, population std) of the `window` samples preceding the last one."""
    if len(values) < 3:
        v = values[:-1] or values
        return (statistics.fmean(v) if v else 0.0), 0.0
    prior = values[-(window + 1):-1]
    if len(prior) < 3:
        prior = values[:-1]
    return statistics.fmean(prior), statistics.pstdev(prior)


def rolling_zscore(values: list[float], window: int = DEFAULT_WINDOW) -> tuple[float, float, float]:
    """Return (z, mean, std) for the last value against the preceding window."""
    if len(values) < 5:
        return 0.0, 0.0, 0.0
    mean, std = rolling_stats(values, window)
    if std < 1e-6:
        std = max(abs(mean) * 0.02, 0.5)
    z = (values[-1] - mean) / std
    return z, mean, std


def rate_of_change_pct(values: list[float], window: int = DEFAULT_WINDOW) -> float:
    """Percent change of the last sample versus the preceding window mean."""
    if len(values) < 5:
        return 0.0
    mean, _ = rolling_stats(values, window)
    if abs(mean) < 1e-6:
        return 0.0 if abs(values[-1]) < 1e-6 else 100.0
    return (values[-1] - mean) / abs(mean) * 100.0


def sustained_deviation_z(values: list[float], window: int = DEFAULT_WINDOW) -> float:
    """Mean z of the last 3 samples — distinguishes a sustained shift (pattern)
    from a single-sample spike."""
    if len(values) < 5:
        return 0.0
    mean, std = rolling_stats(values, window)
    if std < 1e-6:
        std = max(abs(mean) * 0.02, 0.5)
    tail = values[-3:]
    return statistics.fmean((v - mean) / std for v in tail)


def hour_bucket(hour: float) -> int:
    return int(hour % 24) // BUCKET_HOURS


def baseline_key(building_id: str | None, zone_id: str | None, stype: str, hour: float) -> str:
    """Baseline scope: building (or zone) x sensor type x time-of-day bucket."""
    scope = zone_id or building_id or "campus"
    return f"{scope}|{stype}|{hour_bucket(hour)}"


def feature_row(values: list[float], z: float, pct: float, mean: float, std: float) -> list[float]:
    """Per-sensor feature vector for the multivariate detector."""
    rc = rate_of_change_pct(values)
    return [values[-1], z, pct, mean, std, rc]


def build_feature_matrix(
    histories: dict[str, list[float]],
) -> list[tuple[str, list[float]]]:
    rows: list[tuple[str, list[float]]] = []
    for sid, values in histories.items():
        if len(values) < 6:
            continue
        z, mean, std = rolling_zscore(values)
        pct = ((values[-1] - mean) / abs(mean) * 100.0) if abs(mean) > 1e-6 else (
            100.0 if values[-1] else 0.0
        )
        rows.append((sid, feature_row(values, z, pct, mean, std)))
    return rows


def baseline_adopt(registry: dict[str, dict[str, float]], key: str, mean: float, std: float) -> None:
    """EWMA-adopt an observation into a baseline bucket (bounded registry)."""
    cur = registry.get(key)
    if cur is None:
        if len(registry) > 512:  # bounded memory — drop oldest-inserted bucket
            registry.pop(next(iter(registry)))
        registry[key] = {"mean": mean, "std": std, "n": 1.0}
        return
    a = 0.05
    cur["mean"] = (1 - a) * cur["mean"] + a * mean
    cur["std"] = (1 - a) * cur["std"] + a * std
    cur["n"] += 1.0


def baseline_lookup(registry: dict[str, dict[str, float]], key: str,
                    fallback: tuple[float, float]) -> tuple[float, float, str]:
    """Return (mean, std, source). Time-of-day baselines need enough adoption
    cycles; otherwise fall back to the rolling window estimate."""
    cur = registry.get(key)
    if cur is not None and cur.get("n", 0.0) >= 8.0:
        return cur["mean"], max(cur["std"], 1e-3), "time_of_day"
    return fallback[0], fallback[1], "rolling_window"
