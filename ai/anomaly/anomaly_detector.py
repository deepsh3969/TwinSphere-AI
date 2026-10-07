"""Layered anomaly detector (Phase 5).

L1 — hard domain thresholds (always available, deterministic).
L2 — rolling statistics: z-score, rate-of-change, sustained pattern shift.
L3 — Isolation Forest (scikit-learn) on the shared feature matrix, only when
     enough samples exist.

Every detection produces a 0-100 anomaly score with a band
(0-20 NORMAL, 21-40 LOW, 41-60 MODERATE, 61-80 HIGH, 81-100 CRITICAL),
a detector label, a machine reason and a human explanation. Nothing here
touches backend state — inputs are plain history/meta dicts.
"""

from __future__ import annotations

import statistics
from typing import Any

from ai.anomaly.feature_engineering import (
    baseline_adopt,
    baseline_key,
    baseline_lookup,
    build_feature_matrix,
    rate_of_change_pct,
    rolling_stats,
    rolling_zscore,
    sustained_deviation_z,
)

try:  # optional dependency
    from sklearn.ensemble import IsolationForest
    _HAS_SKLEARN = True
except Exception:  # pragma: no cover
    IsolationForest = None
    _HAS_SKLEARN = False

# warning / critical thresholds per metric (upper side, as Phase 1 semantics)
THRESHOLDS: dict[str, tuple[float, float]] = {
    "smoke": (10.0, 40.0),
    "temperature": (33.0, 45.0),
    "air_quality": (120.0, 200.0),
    "energy": (1.0, 1.0),      # kept for reference; L1 skips energy (phase-1 rule)
    "occupancy": (95.0, 100.0),
}

BANDS: list[tuple[int, str]] = [
    (20, "NORMAL"), (40, "LOW"), (60, "MODERATE"), (80, "HIGH"), (101, "CRITICAL"),
]

# legacy severity labels (Phase 1-4 consumers) mapped from the new bands
BAND_SEVERITY = {"NORMAL": "LOW", "LOW": "LOW", "MODERATE": "MEDIUM", "HIGH": "HIGH", "CRITICAL": "CRITICAL"}

Z_SCORE_SCALE = 15.0        # score = |z| * 15  (z=4 -> 60, z=6.7 -> 100)
Z_RAISE_FLOOR = 4.0         # rolling layer only raises at |z| >= 4 in production
PATTERN_Z = 2.0             # sustained-shift recognition floor


def score_band(score: float) -> str:
    score = max(0.0, min(100.0, score))
    for limit, name in BANDS:
        if score <= limit:
            return name
    return "CRITICAL"


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# --------------------------------------------------------------------- L1
def threshold_layer(current: float, stype: str) -> dict[str, Any] | None:
    """Hard domain thresholds. Independent of history length (cold start safe)."""
    if stype == "energy":
        return None  # Phase 1 rule: energy has no meaningful absolute cap
    thr = THRESHOLDS.get(stype)
    if not thr:
        return None
    lo, hi = thr
    if current >= hi:
        overshoot = current - hi
        span = max(hi - lo, 1e-6)
        score = _clamp(75.0 + 25.0 * min(1.0, overshoot / span))
        return {"score": score, "level": "critical",
                "reason": f"value {current:.1f} at/above critical threshold {hi:.0f}"}
    if current >= lo:
        ramp = (current - lo) / max(hi - lo, 1e-6)
        score = _clamp(60.0 + 15.0 * ramp)
        return {"score": score, "level": "warning",
                "reason": f"value {current:.1f} above warning threshold {lo:.0f}"}
    return None


# --------------------------------------------------------------------- L2
def rolling_layer(values: list[float], *, z_threshold: float = Z_RAISE_FLOOR) -> dict[str, Any] | None:
    """Rolling z-score + rate-of-change + sustained-pattern classification."""
    if len(values) < 6:
        return None
    z, mean, std = rolling_zscore(values)
    if abs(z) < z_threshold:
        return None
    score = _clamp(abs(z) * Z_SCORE_SCALE)
    rc = rate_of_change_pct(values)
    sustained = sustained_deviation_z(values)

    if abs(rc) >= 50.0 and abs(z) >= z_threshold:
        atype, reason = "RATE_OF_CHANGE", f"{abs(rc):.0f}% change vs recent mean in one step"
    elif abs(sustained) >= PATTERN_Z + 1.5:
        atype, reason = "UNUSUAL_PATTERN", f"sustained shift z={sustained:.1f} over last 3 samples"
    elif z > 0:
        atype, reason = "SUDDEN_SPIKE", f"z={z:.1f} above rolling mean"
    else:
        atype, reason = "SUDDEN_DROP", f"z={z:.1f} below rolling mean"
    return {"score": score, "z": z, "mean": mean, "std": std, "rc_pct": rc,
            "type": atype, "reason": reason}


# --------------------------------------------------------------------- L3
def isolation_layer(histories: dict[str, list[float]]) -> dict[str, dict[str, Any]]:
    """Isolation Forest over the shared feature matrix (needs sample depth)."""
    out: dict[str, dict[str, Any]] = {}
    if not _HAS_SKLEARN or len(histories) < 6:
        return out
    rows = build_feature_matrix(histories)
    if len(rows) < 12:
        return out
    try:
        matrix = [r[1] for r in rows]
        forest = IsolationForest(n_estimators=60, contamination=0.12, random_state=42)
        labels = forest.fit_predict(matrix)
        raw = forest.decision_function(matrix)
        for (sid, _), label, sc in zip(rows, labels, raw):
            if label == -1:
                magnitude = _clamp(-sc, 0.0, 1.0)
                out[sid] = {
                    "score": _clamp(50.0 + 40.0 * magnitude),
                    "reason": "statistically unusual feature vector vs recent telemetry",
                    "type": "UNUSUAL_PATTERN",
                }
    except Exception:
        return {}
    return out


# ---------------------------------------------------------- multivariate
def multivariate_layer(histories: dict[str, list[float]],
                       meta: dict[str, dict]) -> list[dict[str, Any]]:
    """Cross-metric relations inside one building.

    Documented relations (deterministic):
      occupancy falling while energy rises sharply  -> demand/efficiency fault
      temperature rising while humidity drops       -> HVAC / sensor fault
    """
    by_building: dict[str, dict[str, str]] = {}
    for sid, m in meta.items():
        bid = m.get("building_id")
        if bid and sid in histories and len(histories[sid]) >= 6:
            by_building.setdefault(bid, {})[m.get("type", "")] = sid

    relations = [
        ("occupancy", "energy", -2.0, 2.0,
         "occupancy falling while energy demand rises sharply"),
        ("temperature", "humidity", 2.0, -2.0,
         "temperature rising while humidity drops sharply"),
    ]
    results: list[dict[str, Any]] = []
    for bid, sensors in by_building.items():
        for type_a, type_b, need_a, need_b, text in relations:
            sid_a, sid_b = sensors.get(type_a), sensors.get(type_b)
            if not sid_a or not sid_b:
                continue
            za, _, _ = rolling_zscore(histories[sid_a])
            zb, _, _ = rolling_zscore(histories[sid_b])
            if (za - need_a) * (1 if need_a > 0 else -1) >= 0 and \
               (zb - need_b) * (1 if need_b > 0 else -1) >= 0:
                score = _clamp(60.0 + 5.0 * (abs(za) + abs(zb) - 4.0))
                results.append({
                    "sensor_id": sid_b, "metric": type_b, "building_id": bid,
                    "score": score, "type": "MULTIVARIATE_ANOMALY",
                    "detector": "multivariate",
                    "reason": text, "z_a": round(za, 2), "z_b": round(zb, 2),
                })
    return results


# ------------------------------------------------------------------- main
def detect(sensor_history: dict[str, list[float]],
           sensor_meta: dict[str, dict],
           *,
           clock_hour: float = 0.0,
           z_threshold: float = Z_RAISE_FLOOR,
           score_threshold: float = 60.0,
           min_samples: int = 6,
           use_isolation_forest: bool = True,
           baselines: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    """Run all layers. Returns {anomalies, insufficient}.

    `baselines` is an optional mutable registry (time-of-day baselines);
    when omitted a rolling-window baseline is used for every detection.
    """
    registry = baselines if baselines is not None else {}
    results: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    iso = isolation_layer(sensor_history) if use_isolation_forest else {}

    for sid, values in sensor_history.items():
        if not values:
            continue
        m = sensor_meta.get(sid, {})
        stype = m.get("type", "")
        current = values[-1]
        available = len(values)

        if available < min_samples:
            insufficient.append({"sensor_id": sid, "available_samples": available,
                                 "minimum_required": min_samples})

        # baseline: time-of-day (if registry has adoption) else rolling window
        z, mean, std = rolling_zscore(values)
        if len(values) >= 2 and mean == 0.0 and std == 0.0:
            # rolling_zscore needs >=5 samples; derive a basic baseline for
            # short (cold-start) series so explanations never show expected 0
            prior = values[:-1]
            mean = statistics.fmean(prior) if prior else values[-1]
            std = statistics.pstdev(prior) if len(prior) >= 2 else 0.0
        key = baseline_key(m.get("building_id"), m.get("zone_id"), stype, clock_hour)
        b_mean, b_std, b_source = baseline_lookup(registry, key, (mean, std))
        pct = ((current - b_mean) / abs(b_mean) * 100.0) if abs(b_mean) > 1e-6 else (
            100.0 if current else 0.0
        )

        # L1 hard thresholds run on any history depth (cold-start safe)
        candidates: list[dict[str, Any]] = []
        l1 = threshold_layer(current, stype)
        if l1:
            candidates.append({
                "score": l1["score"], "detector": "threshold",
                "type": "THRESHOLD_BREACH", "reason": l1["reason"], "detail": l1,
            })

        # L2/L3 need sample depth
        if available >= 6:
            l2 = rolling_layer(values, z_threshold=z_threshold)
            if l2:
                candidates.append({
                    "score": l2["score"], "detector": "rolling_zscore",
                    "type": l2["type"], "reason": l2["reason"], "detail": l2,
                })
            # slow time-of-day baseline: survives rolling-window absorption of
            # a sustained shift, giving the tracker a real 2nd observation
            if b_source == "time_of_day":
                std_tod = max(b_std, abs(b_mean) * 0.02, 0.5)
                z_tod = (current - b_mean) / std_tod
                if abs(z_tod) >= z_threshold:
                    candidates.append({
                        "score": _clamp(abs(z_tod) * Z_SCORE_SCALE),
                        "detector": "time_of_day_baseline",
                        "type": "SUDDEN_SPIKE" if z_tod > 0 else "SUDDEN_DROP",
                        "reason": (f"outside time-of-day baseline "
                                   f"(z={z_tod:.1f} vs same-hour expectation)"),
                        "detail": {},
                    })
            if sid in iso:
                candidates.append({
                    "score": iso[sid]["score"], "detector": "isolation_forest",
                    "type": iso[sid]["type"], "reason": iso[sid]["reason"], "detail": {},
                })

        if not candidates:
            if available >= min_samples:
                baseline_adopt(registry, key, mean, std)
            continue

        best = max(candidates, key=lambda c: c["score"])
        detectors = sorted({c["detector"] for c in candidates})
        score = best["score"]

        # false-positive control: statistical detections must clear the raise
        # floor; a hard threshold breach always raises (cold-start safe)
        hard = any(c["detector"] == "threshold" for c in candidates)
        if not hard and score < score_threshold:
            if available >= min_samples:
                baseline_adopt(registry, key, mean, std)
            continue

        direction = "above" if current >= b_mean else "below"
        stype_label = m.get("label", stype.title())
        location = m.get("building_name") or m.get("name") or "Campus"
        band = score_band(score)
        confidence: float | None
        if available < min_samples:
            confidence = None  # not meaningful yet
        else:
            confidence = round(_clamp(0.4 + 0.05 * abs(z) + min(0.3, available / 300.0), 0.0, 0.9), 2)

        results.append({
            "id": f"anom:{sid}:{stype}",
            "sensor_id": sid,
            "metric": stype,
            "location": location,
            "building_id": m.get("building_id"),
            "zone_id": m.get("zone_id"),
            "value": round(current, 2),
            "expected": round(b_mean, 2),
            "deviation_pct": round(pct, 1),
            "z_score": round(z, 2),
            "score": round(score),
            "band": band,
            "severity": BAND_SEVERITY[band],
            "anomaly_type": best["type"],
            "detector": "+".join(detectors),
            "reason": best["reason"],
            "explanation": (
                f"{stype_label} in {location} is {abs(pct):.0f}% {direction} its expected "
                f"pattern ({current:.1f}{m.get('unit', '')} vs expected {b_mean:.1f}, z={z:.1f}; "
                f"{best['reason']}; detector: {best['detector']}; baseline: {b_source})."
            ),
            "method": "+".join(detectors),
            "confidence": confidence,
            "baseline": b_source,
            "data_quality": "OK" if available >= min_samples else "INSUFFICIENT_DATA",
            "available_samples": available,
            "minimum_required": min_samples,
            "status": "ACTIVE",
            "score_raw": round(score, 1),
            "rate_of_change_pct": round(rate_of_change_pct(values), 1),
        })

        if available >= min_samples:
            baseline_adopt(registry, key, mean, std)

    for mv in multivariate_layer(sensor_history, sensor_meta):
        m = sensor_meta.get(mv["sensor_id"], {})
        score = mv["score"]
        if score < score_threshold:
            continue
        band = score_band(score)
        location = m.get("building_name") or m.get("name") or "Campus"
        results.append({
            "id": f"anom:mv:{mv['building_id']}:{mv['type']}",
            "sensor_id": mv["sensor_id"],
            "metric": mv["metric"],
            "location": location,
            "building_id": mv["building_id"],
            "zone_id": None,
            "value": round(sensor_history.get(mv["sensor_id"], [0.0])[-1], 2),
            "expected": 0.0,
            "deviation_pct": 0.0,
            "z_score": mv.get("z_b", 0.0),
            "score": round(score),
            "band": band,
            "severity": BAND_SEVERITY[band],
            "anomaly_type": "MULTIVARIATE_ANOMALY",
            "detector": "multivariate",
            "reason": mv["reason"],
            "explanation": (
                f"Cross-metric anomaly in {location}: {mv['reason']} "
                f"(z {mv['metric']}={mv.get('z_b', 0):.1f}, correlation pair z={mv.get('z_a', 0):.1f}; "
                f"detector: multivariate)."
            ),
            "method": "multivariate",
            "confidence": 0.75,
            "baseline": "rolling_window",
            "data_quality": "OK",
            "available_samples": len(sensor_history.get(mv["sensor_id"], [])),
            "minimum_required": min_samples,
            "status": "ACTIVE",
            "score_raw": round(score, 1),
            "rate_of_change_pct": 0.0,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return {"anomalies": results, "insufficient": insufficient}


def backend_name() -> str:
    return ("scikit-learn IsolationForest + rolling z-score + domain thresholds"
            if _HAS_SKLEARN else "rolling z-score + domain thresholds (sklearn unavailable)")
