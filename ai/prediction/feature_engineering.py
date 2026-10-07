"""Feature engineering for prediction models (Phase 5).

Chronological series only — features at index i use values at i-1, i-2, ...
never future samples (no leakage). Time features are cyclic hour encodings;
lags and rolling statistics capture recent dynamics; an optional sibling
series supplies cross-metric context (e.g. occupancy ratio for energy).
"""

from __future__ import annotations

import math
from typing import Any

FEATURE_NAMES = [
    "hour_sin", "hour_cos", "hour", "lag1", "lag2", "lag3",
    "trend", "roll_mean4", "roll_std4", "sibling",
]

MIN_FEATURE_ROWS = 6  # need at least this many labelled rows to train


def build_features(hours: list[float], values: list[float], i: int,
                   sibling: list[float] | None = None) -> list[float]:
    """Feature vector for index i (uses only data <= i)."""
    h = hours[i] % 24
    lag1 = values[i - 1] if i >= 1 else values[i]
    lag2 = values[i - 2] if i >= 2 else values[i]
    lag3 = values[i - 3] if i >= 3 else values[i]
    trend = (values[i] - values[i - 3]) if i >= 3 else 0.0
    window = values[max(0, i - 3): i + 1]
    roll_mean = sum(window) / len(window)
    roll_var = sum((v - roll_mean) ** 2 for v in window) / len(window)
    roll_std = math.sqrt(roll_var)
    sib = sibling[i] if sibling and i < len(sibling) else 0.0
    return [
        math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24), h,
        lag1, lag2, lag3, trend, roll_mean, roll_std, sib,
    ]


def build_matrix(hours: list[float], values: list[float],
                 sibling: list[float] | None = None) -> tuple[list[list[float]], list[float]]:
    """(X, y) rows for indices >= 3 — chronological order preserved."""
    X = [build_features(hours, values, i, sibling) for i in range(3, len(values))]
    y = list(values[3:])
    return X, y


def chronological_split(X: list[list[float]], y: list[float],
                        test_fraction: float = 0.2) -> tuple[
    list[list[float]], list[float], list[list[float]], list[float]]:
    """Time-ordered split: earliest rows train, latest rows validate.
    Never shuffled (spec: chronological splits only)."""
    n = len(y)
    split = max(1, int(n * (1.0 - test_fraction)))
    if split >= n:  # not enough rows for a hold-out
        split = n
        return X, y, [], []
    return X[:split], y[:split], X[split:], y[split:]


def regression_metrics(y_true: list[float], y_pred: list[float]) -> dict[str, Any]:
    """MAE / RMSE / R² — honest metrics; MAPE only when denominators are safe."""
    if not y_true:
        return {"mae": None, "rmse": None, "r2": None, "mape": None}
    n = len(y_true)
    errs = [t - p for t, p in zip(y_true, y_pred)]
    mae = sum(abs(e) for e in errs) / n
    rmse = math.sqrt(sum(e * e for e in errs) / n)
    mean_true = sum(y_true) / n
    sst = sum((t - mean_true) ** 2 for t in y_true)
    r2 = 1.0 - (sum(e * e for e in errs) / sst) if sst > 1e-9 else None
    mape = None
    pairs = [(t, p) for t, p in zip(y_true, y_pred) if abs(t) > 1e-6]
    if len(pairs) >= max(3, int(0.8 * n)) and mean_true > 1e-6:
        mape = sum(abs(t - p) / abs(t) for t, p in pairs) / len(pairs) * 100.0
    return {
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "r2": round(r2, 3) if r2 is not None else None,
        "mape": round(mape, 2) if mape is not None else None,
        "n": n,
    }
