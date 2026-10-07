"""Prediction service (Phase 5): training pipeline + forecasting.

Pipeline (separated from routes, spec §64):
  load_data -> prepare_features -> split_data (chronological, no shuffle)
  -> train -> evaluate (MAE / RMSE / R², MAPE only when safe)
  -> save_model (joblib, MODEL_DIR) -> load_model -> predict

RandomForest when enough samples + sklearn; otherwise a deterministic
seasonal baseline labelled model=BASELINE. Confidence is derived from
measured hold-out error and never overstated.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.prediction.feature_engineering import (
    FEATURE_NAMES,
    MIN_FEATURE_ROWS,
    build_matrix,
    chronological_split,
    regression_metrics,
)

try:
    from sklearn.ensemble import RandomForestRegressor
    _HAS_SKLEARN = True
except Exception:  # pragma: no cover
    RandomForestRegressor = None
    _HAS_SKLEARN = False

try:
    import joblib as _joblib
    _HAS_JOBLIB = True
except Exception:  # pragma: no cover
    _joblib = None
    _HAS_JOBLIB = False

MODEL_VERSIONS = {"occupancy": "occupancy-rf-v1", "energy": "energy-rf-v1"}
DEFAULT_MODEL_DIR = "ai/models"


def confidence_label(confidence: float | None, status: str) -> str:
    if status == "INSUFFICIENT_DATA" or confidence is None:
        return "N/A"
    if confidence >= 0.75:
        return "HIGH"
    if confidence >= 0.5:
        return "MEDIUM"
    return "LOW"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class ModelBundle:
    """Trained artefact + honest training metadata."""
    version: str
    kind: str                     # "rf" | "baseline"
    entity_id: str
    metric: str
    features: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    trained_at: str = ""
    samples: int = 0
    model: Any = None             # None for baseline (stateless)


# ------------------------------------------------------------------ baseline
def baseline_forecast(hours: list[float], values: list[float], horizon_h: float) -> float:
    """Seasonal hour-of-day baseline blended with recent linear trend."""
    if not values:
        return 0.0
    target_h = (hours[-1] + horizon_h) % 24
    bucket_values = [v for h, v in zip(hours, values)
                     if abs(((h - target_h + 12) % 24) - 12) <= 1.5]
    seasonal = statistics.fmean(bucket_values) if bucket_values else statistics.fmean(values[-8:])
    k = min(8, len(values))
    recent = values[-k:]
    x_mean = (k - 1) / 2
    y_mean = statistics.fmean(recent)
    denom = sum((i - x_mean) ** 2 for i in range(k)) or 1.0
    slope = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent)) / denom
    steps = max(1, int(round(horizon_h * 60 / 15)))
    trended = y_mean + slope * (steps - x_mean)
    return 0.6 * seasonal + 0.4 * trended


def baseline_walkforward_error(hours: list[float], values: list[float]) -> float:
    """Normalised one-step walk-forward error of the baseline (0..1+)."""
    if len(values) < 8:
        return 0.5
    residuals = []
    for i in range(max(4, len(values) - 12), len(values)):
        pred = baseline_forecast(hours[:i], values[:i], hours[i] - hours[i - 1])
        residuals.append(abs(values[i] - pred))
    denom = max(1.0, statistics.fmean(abs(v) for v in values[-12:]))
    return statistics.fmean(residuals) / denom if residuals else 0.5


# --------------------------------------------------------------------- train
def train_bundle(hours: list[float], values: list[float], *,
                 metric: str, entity_id: str,
                 sibling: list[float] | None = None) -> ModelBundle | None:
    """Chronological train/evaluate. Returns None when data is too thin."""
    version = MODEL_VERSIONS.get(metric, f"{metric}-rf-v1")
    X, y = build_matrix(hours, values, sibling)
    if len(y) < MIN_FEATURE_ROWS or not _HAS_SKLEARN:
        return None
    X_train, y_train, X_test, y_test = chronological_split(X, y, test_fraction=0.2)
    if len(y_train) < MIN_FEATURE_ROWS:
        return None
    try:
        model = RandomForestRegressor(n_estimators=80, max_depth=6, random_state=42)
        model.fit(X_train, y_train)
    except Exception:
        return None
    if X_test:
        preds = list(model.predict(X_test))
        metrics = regression_metrics(y_test, preds)
    else:
        preds = list(model.predict(X_train))
        metrics = regression_metrics(y_train, preds)
        metrics["holdout"] = False
    return ModelBundle(
        version=version, kind="rf", entity_id=entity_id, metric=metric,
        features=list(FEATURE_NAMES), metrics=metrics,
        trained_at=datetime.now(timezone.utc).isoformat(),
        samples=len(y), model=model,
    )


def _artifact_path(model_dir: str, bundle: ModelBundle) -> Path:
    return Path(model_dir) / f"{bundle.metric}_{bundle.entity_id}_{bundle.version}.joblib"


def save_model(bundle: ModelBundle, model_dir: str) -> None:
    if not _HAS_JOBLIB or bundle.model is None:
        return
    try:
        path = _artifact_path(model_dir, bundle)
        path.parent.mkdir(parents=True, exist_ok=True)
        _joblib.dump({
            "model": bundle.model,
            "meta": {
                "version": bundle.version, "metric": bundle.metric,
                "entity_id": bundle.entity_id, "features": bundle.features,
                "metrics": bundle.metrics, "trained_at": bundle.trained_at,
                "samples": bundle.samples,
            },
        }, path)
    except Exception:
        pass  # persistence is best-effort — predictions never fail on I/O


def load_model(model_dir: str, metric: str, entity_id: str) -> ModelBundle | None:
    if not _HAS_JOBLIB:
        return None
    version = MODEL_VERSIONS.get(metric, f"{metric}-rf-v1")
    path = Path(model_dir) / f"{metric}_{entity_id}_{version}.joblib"
    if not path.exists():
        return None
    try:
        payload = _joblib.load(path)
        meta = payload.get("meta", {})
        return ModelBundle(
            version=meta.get("version", version), kind="rf",
            entity_id=entity_id, metric=metric,
            features=meta.get("features", list(FEATURE_NAMES)),
            metrics=meta.get("metrics", {}),
            trained_at=meta.get("trained_at", ""),
            samples=int(meta.get("samples", 0)), model=payload.get("model"),
        )
    except Exception:
        return None


# ------------------------------------------------------------------- cache
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def get_bundle(metric: str, entity_id: str, hours: list[float], values: list[float],
               *, sibling: list[float] | None = None,
               min_samples: int = 100, retrain_seconds: float = 600.0,
               model_dir: str = DEFAULT_MODEL_DIR) -> ModelBundle | None:
    """Train/retrain with an in-memory cache (bounded per entity+metric)."""
    key = (metric, entity_id)
    entry = _CACHE.get(key)
    now = time.monotonic()
    samples = len(values)
    if samples < min_samples:
        return None  # caller falls back to BASELINE
    stale = (
        entry is None
        or now - entry["trained_at"] >= retrain_seconds
        or samples - entry["samples"] >= 20
    )
    if stale:
        bundle = train_bundle(hours, values, metric=metric, entity_id=entity_id,
                              sibling=sibling)
        if bundle is None:
            # try a previously persisted artefact before giving up
            bundle = load_model(model_dir, metric, entity_id)
            if bundle is None:
                return None
        else:
            save_model(bundle, model_dir)
        if len(_CACHE) > 128:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = {"bundle": bundle, "trained_at": now, "samples": samples}
        return bundle
    return entry["bundle"]


def clear_cache() -> None:
    _CACHE.clear()


# ------------------------------------------------------------------ predict
def predict_bundle(bundle: ModelBundle | None, hours: list[float], values: list[float],
                   *, horizon_min: int, sibling: list[float] | None = None) -> float:
    horizon_h = horizon_min / 60.0
    if bundle is not None and bundle.model is not None and len(values) >= 4:
        from ai.prediction.feature_engineering import build_features
        fut_hours = hours + [(hours[-1] + horizon_h) % 24]
        fut_values = values + [values[-1]]
        feats = build_features(fut_hours, fut_values, len(values), sibling)
        try:
            return float(bundle.model.predict([feats])[0])
        except Exception:
            return baseline_forecast(hours, values, horizon_h)
    return baseline_forecast(hours, values, horizon_h)


def forecast(entity_id: str, metric: str, entity_name: str,
             hours: list[float], values: list[float], *,
             horizons: tuple[int, ...] = (15, 30, 60),
             lower_bound: float = 0.0, upper_bound: float = 100.0,
             sibling: list[float] | None = None,
             min_samples: int = 100, retrain_seconds: float = 600.0,
             model_dir: str = DEFAULT_MODEL_DIR,
             entity_type: str = "building") -> list[dict[str, Any]]:
    """Produce one prediction record per configured horizon."""
    name = entity_name or entity_id or "entity"
    if len(values) < 6:
        return [{
            "entity_id": entity_id, "entity_type": entity_type, "metric": metric,
            "current_value": values[-1] if values else 0.0,
            "predicted_value": round(values[-1], 1) if values else 0.0,
            "horizon_min": h, "confidence": 0.0, "confidence_label": "N/A",
            "model_name": "insufficient_data", "model_version": "",
            "status": "INSUFFICIENT_DATA", "mae": None, "rmse": None, "r2": None,
            "summary": "Not enough history to produce a reliable prediction.",
            "samples": len(values), "trained_at": None,
        } for h in horizons]

    current = values[-1]
    bundle = get_bundle(metric, entity_id, hours, values, sibling=sibling,
                        min_samples=min_samples, retrain_seconds=retrain_seconds,
                        model_dir=model_dir)

    if bundle is not None:
        model_name = bundle.version
        model_version = bundle.version
        status = "OK"
        mae = bundle.metrics.get("mae")
        rmse = bundle.metrics.get("rmse")
        r2 = bundle.metrics.get("r2")
        mape = bundle.metrics.get("mape")
        mean_abs = statistics.fmean(abs(v) for v in values[-24:]) or 1.0
        err = (mae if isinstance(mae, (int, float)) else baseline_walkforward_error(hours, values) * mean_abs)
        confidence = _clamp(1.0 - err / mean_abs, 0.30, 0.95)
        if isinstance(r2, (int, float)) and r2 < 0.3:
            status = "LOW_CONFIDENCE"
            confidence = min(confidence, 0.5)
        samples = bundle.samples
        trained_at = bundle.trained_at
    else:
        model_name = "BASELINE"
        model_version = f"{MODEL_VERSIONS.get(metric, metric)}-baseline"
        status = "BASELINE"
        err_ratio = baseline_walkforward_error(hours, values)
        confidence = _clamp(1.0 - err_ratio, 0.30, 0.85)
        mae = round(err_ratio * (statistics.fmean(abs(v) for v in values) or 1.0), 2)
        rmse = None
        r2 = None
        mape = None
        samples = len(values)
        trained_at = None
        if confidence < 0.5:
            status = "LOW_CONFIDENCE"

    conf_label = confidence_label(confidence, status)
    records: list[dict[str, Any]] = []
    for h in horizons:
        predicted = _clamp(predict_bundle(bundle, hours, values, horizon_min=h,
                                          sibling=sibling), lower_bound, upper_bound)
        delta = predicted - current
        direction = "rise" if delta >= 0 else "fall"
        metric_err = f" ±{mae:.1f}" if isinstance(mae, (int, float)) else ""
        summary = (
            f"{metric.title()} for {name} is {current:.0f} and is predicted to {direction} to "
            f"{predicted:.0f} within {h} minutes (Model confidence: {conf_label}, "
            f"{model_name}{metric_err})."
        )
        records.append({
            "entity_id": entity_id, "entity_type": entity_type, "metric": metric,
            "current_value": round(current, 2), "predicted_value": round(predicted, 2),
            "horizon_min": h, "confidence": round(confidence, 2),
            "confidence_label": conf_label, "model_name": model_name,
            "model_version": model_version, "status": status,
            "mae": mae, "rmse": rmse, "r2": r2, "mape": mape,
            "summary": summary, "samples": samples, "trained_at": trained_at,
        })
    return records


def backend_name() -> str:
    if _HAS_SKLEARN and _HAS_JOBLIB:
        return "sklearn RandomForestRegressor + seasonal baseline fallback (joblib persisted)"
    if _HAS_SKLEARN:
        return "sklearn RandomForestRegressor + seasonal baseline fallback"
    return "statistical seasonal baseline (sklearn unavailable)"
