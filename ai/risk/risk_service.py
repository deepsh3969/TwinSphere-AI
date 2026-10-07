"""Risk stability service (Phase 5): smoothing + hysteresis.

Raw weighted scores are noisy frame-to-frame; publishing them directly makes
risk levels flap at band edges. This service applies:

  * exponential moving average smoothing (RISK_SMOOTHING_ALPHA)
  * a minimum published change (RISK_MIN_DELTA points)
  * level hysteresis — downgrades need ~2.5x the movement of upgrades

so the campus/building risk a user sees is stable while still responsive.
Bounded per-entity history feeds the risk trend views.
"""

from __future__ import annotations

from ai.risk.risk_engine import risk_level

HISTORY_LIMIT = 60
DOWNGRADE_FACTOR = 2.5
RISE_ALPHA_FLOOR = 0.55   # risk increases must never lag the hazard
JUMP_DELTA = 25.0         # large jumps publish immediately (no smoothing)


class RiskStability:
    """One per twin state; all memory bounded by entity count."""

    def __init__(self, *, alpha: float = 0.35, min_delta: float = 1.0) -> None:
        self.alpha = max(0.0, min(1.0, alpha))
        self.min_delta = max(0.0, min_delta)
        self.smoothed: dict[str, float] = {}
        self.published: dict[str, dict] = {}
        self.history: dict[str, list[dict]] = {}
        self._order: list[str] = []

    def update(self, entity_id: str, raw_score: float, *,
               factors: list | None = None, explanation: str = "",
               level: str | None = None) -> dict:
        raw = max(0.0, min(100.0, float(raw_score)))
        prev_smooth = self.smoothed.get(entity_id)
        if prev_smooth is None:
            smooth = raw
        else:
            gap = raw - prev_smooth
            if abs(gap) >= JUMP_DELTA:
                alpha_eff = 1.0            # regime change: publish raw immediately
            elif gap > 0:
                alpha_eff = max(self.alpha, RISE_ALPHA_FLOOR)  # fast attack
            else:
                alpha_eff = self.alpha     # slow, hysteretic decay
            smooth = alpha_eff * raw + (1.0 - alpha_eff) * prev_smooth
        self.smoothed[entity_id] = smooth

        pub = self.published.get(entity_id)
        if pub is None:
            result = self._publish(entity_id, raw, smooth, factors, explanation, level)
            return result

        change = abs(smooth - pub["score"])
        new_level = level or risk_level(smooth)
        upgrading = self._rank(new_level) > self._rank(pub["level"])
        required = self.min_delta if upgrading else self.min_delta * DOWNGRADE_FACTOR
        if change >= required:
            return self._publish(entity_id, raw, smooth, factors, explanation, level)

        # hold the published value; expose the direction for trend UIs
        delta = smooth - pub["score"]
        return {
            "entity_id": entity_id, "score": pub["score"], "level": pub["level"],
            "raw_score": round(raw, 1), "smoothed": round(smooth, 1),
            "delta": round(pub.get("delta", 0.0), 1),
            "trend": round(delta, 2), "changed": False,
            "factors": pub.get("factors", factors or []),
            "explanation": pub.get("explanation", explanation),
        }

    def _publish(self, entity_id: str, raw: float, smooth: float,
                 factors: list | None, explanation: str, level: str | None) -> dict:
        prev = self.published.get(entity_id)
        score = round(smooth, 1)
        lvl = level or risk_level(smooth)
        delta = round(score - prev["score"], 1) if prev else 0.0
        entry = {
            "score": score, "level": lvl, "raw_score": round(raw, 1),
            "delta": delta, "factors": factors or [],
            "explanation": explanation, "changed": True,
        }
        self.published[entity_id] = entry

        hist = self.history.setdefault(entity_id, [])
        hist.append({"score": score, "level": lvl})
        if len(hist) > HISTORY_LIMIT:
            del hist[: len(hist) - HISTORY_LIMIT]

        return {"entity_id": entity_id, "smoothed": round(smooth, 1),
                "trend": 0.0, **entry}

    @staticmethod
    def _rank(level: str) -> int:
        order = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4}
        return order.get(level, 0)

    def trend(self, entity_id: str) -> list[dict]:
        return list(self.history.get(entity_id, []))
