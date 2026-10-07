"""Anomaly service (Phase 5): stateful tracking around the pure detector.

Owns the false-positive controls the detector intentionally keeps stateless:
observation persistence for statistical detections, score decay with release
hysteresis (raise >= threshold, release < 25), bounded tracking and per-sensor
AI status (INSUFFICIENT_DATA / NORMAL / band) for the UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai.anomaly.anomaly_detector import BAND_SEVERITY, backend_name, detect, score_band

RELEASE_SCORE = 25.0     # tracked anomaly drops below this -> removed
DECAY_PER_CYCLE = 18.0   # score bleed per cycle when the detector stops firing
STRONG_BONUS = 15.0      # score above threshold that skips persistence wait


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnomalyTracker:
    """One per twin state. All memory bounded."""

    def __init__(self, *, min_samples: int = 30, score_threshold: float = 60.0,
                 max_tracked: int = 50) -> None:
        self.min_samples = min_samples
        self.score_threshold = score_threshold
        self.max_tracked = max_tracked
        self.tracked: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, int] = {}
        self.baselines: dict[str, dict[str, float]] = {}
        self.cycle = 0
        self.last_result: dict[str, Any] = {}

    # ------------------------------------------------------------------
    def update(self, histories: dict[str, list[float]], meta: dict[str, dict],
               *, clock_hour: float,
               use_isolation_forest: bool = True) -> dict[str, Any]:
        self.cycle += 1
        now = _now()
        detected = detect(
            histories, meta,
            clock_hour=clock_hour,
            score_threshold=self.score_threshold,
            min_samples=self.min_samples,
            use_isolation_forest=use_isolation_forest,
            baselines=self.baselines,
        )
        candidates: list[dict[str, Any]] = detected["anomalies"]
        insufficient: list[dict[str, Any]] = detected["insufficient"]

        active_ids: set[str] = set()
        for cand in candidates:
            sid = cand["sensor_id"]
            hard = (
                "threshold" in (cand.get("detector") or "")
                or cand["anomaly_type"] == "MULTIVARIATE_ANOMALY"
            )
            strong = cand["score"] >= self.score_threshold + STRONG_BONUS
            if not hard and not strong:
                self.pending[sid] = self.pending.get(sid, 0) + 1
                if self.pending[sid] < 2:
                    continue  # persistence: second consecutive observation required
            self.pending[sid] = 0

            existing = self.tracked.get(cand["id"])
            if existing:
                cand["first_seen"] = existing.get("first_seen", now)
                cand["observations"] = int(existing.get("observations", 0)) + 1
                cand["status"] = "ACTIVE"
            else:
                cand["first_seen"] = now
                cand["observations"] = 1
                cand["status"] = "NEW"
            cand["last_seen"] = now
            self.tracked[cand["id"]] = cand
            active_ids.add(cand["id"])

        # decay anomalies the detector no longer sees (release hysteresis)
        for aid in list(self.tracked):
            if aid in active_ids:
                continue
            item = self.tracked[aid]
            item["score"] = round(max(0.0, float(item.get("score", 0)) - DECAY_PER_CYCLE))
            item["status"] = "DECAYING"
            item["last_seen"] = item.get("last_seen", now)
            band = score_band(item["score"])
            item["band"] = band
            item["severity"] = BAND_SEVERITY[band]
            if item["score"] < RELEASE_SCORE:
                del self.tracked[aid]
                self.pending.pop(item.get("sensor_id", ""), None)

        # bounded tracking: strongest first
        ranked = sorted(self.tracked.values(), key=lambda a: a["score"], reverse=True)
        if len(ranked) > self.max_tracked:
            keep = ranked[: self.max_tracked]
            drop = ranked[self.max_tracked:]
            for item in drop:
                self.tracked.pop(item["id"], None)
            ranked = keep

        # per-sensor AI status for inspectors / data-quality reporting
        sensor_status: dict[str, dict[str, Any]] = {}
        anomalous = {a["sensor_id"]: a for a in ranked}
        insufficient_ids = {s["sensor_id"] for s in insufficient}
        for sid, values in histories.items():
            a = anomalous.get(sid)
            if a:
                sensor_status[sid] = {
                    "status": a["band"], "score": a["score"],
                    "type": a["anomaly_type"], "detector": a["detector"],
                    "anomaly_id": a["id"], "available_samples": len(values),
                    "minimum_required": self.min_samples,
                }
            elif sid in insufficient_ids or len(values) < self.min_samples:
                sensor_status[sid] = {
                    "status": "INSUFFICIENT_DATA", "score": None, "type": None,
                    "detector": None, "anomaly_id": None,
                    "available_samples": len(values), "minimum_required": self.min_samples,
                }
            else:
                sensor_status[sid] = {
                    "status": "NORMAL", "score": 0, "type": None, "detector": None,
                    "anomaly_id": None, "available_samples": len(values),
                    "minimum_required": self.min_samples,
                }

        insufficient_total = len(insufficient_ids)
        if not histories:
            quality = "INSUFFICIENT"
        elif insufficient_total >= max(1, len(histories)):
            quality = "INSUFFICIENT"
        elif insufficient_total > 0:
            quality = "LIMITED"
        else:
            quality = "OK"

        result = {
            "anomalies": ranked,
            "sensor_status": sensor_status,
            "insufficient": insufficient,
            "data_quality": quality,
            "engine": backend_name(),
            "cycle": self.cycle,
            "score_threshold": self.score_threshold,
            "min_samples": self.min_samples,
            "generated_at": now,
        }
        self.last_result = result
        return result


def filtered(anomalies: list[dict[str, Any]], *, severity: str | None = None,
             building_id: str | None = None, sensor_id: str | None = None,
             metric: str | None = None, start: str | None = None,
             end: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Shared list filter for the REST layer (Phase 5 spec filters)."""
    out = anomalies
    if severity:
        wanted = severity.upper()
        out = [a for a in out if a.get("band") == wanted
               or a.get("severity") == wanted
               or (wanted == "MEDIUM" and a.get("band") == "MODERATE")]
    if building_id:
        out = [a for a in out if a.get("building_id") == building_id]
    if sensor_id:
        out = [a for a in out if a.get("sensor_id") == sensor_id]
    if metric:
        out = [a for a in out if a.get("metric") == metric]
    if start:
        out = [a for a in out if (a.get("last_seen") or a.get("first_seen") or "") >= start]
    if end:
        out = [a for a in out if (a.get("first_seen") or a.get("last_seen") or "") <= end]
    return out[: max(1, min(limit, 200))]
