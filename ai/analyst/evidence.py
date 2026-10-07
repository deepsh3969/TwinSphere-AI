"""Phase 8 — evidence extraction & grounding (§9/§40).

Every Analyst statement is backed by EvidenceItems pulled from the normalized
context — source component, metric, value, timestamp, severity, confidence.
The same module produces the grounding material used to reject hallucinated
LLM output (unknown entities, unsourced numbers).
"""

from __future__ import annotations

from typing import Any

from .schemas import EvidenceItem

_SEVERITY_BY_LEVEL = {"LOW": "LOW", "MODERATE": "MEDIUM", "ELEVATED": "MEDIUM",
                      "HIGH": "HIGH", "CRITICAL": "CRITICAL"}


def _sev_for_level(level: str) -> str:
    return _SEVERITY_BY_LEVEL.get(str(level).upper(), "INFO")


def _mk(items: list[EvidenceItem], *, label: str, source_type: str,
        metric: str = "", value: Any = None, unit: str = "",
        severity: str = "INFO", source_id: str = "", timestamp: str | None = None,
        age_seconds: float | None = None, confidence: float | None = None,
        detail: str = "") -> EvidenceItem:
    item = EvidenceItem(
        id=f"ev_{len(items) + 1}", label=label, source_type=source_type,
        source_id=source_id, metric=metric,
        value=(value if isinstance(value, (int, float, str)) or value is None
               else str(value)),
        unit=unit, severity=severity, timestamp=timestamp, age_seconds=age_seconds,
        confidence=confidence, detail=detail[:400],
    )
    items.append(item)
    return item


def extract_evidence(ctx: dict) -> list[EvidenceItem]:
    """§9 — structured evidence for one context. Deterministic order so the
    evidence panel and tests are stable."""
    items: list[EvidenceItem] = []
    risk = ctx.get("risk", {}) or {}
    sim = ctx.get("simulation", {}) or {}
    routes = ctx.get("routes", {}) or {}
    evac = ctx.get("evacuation", {}) or {}
    fresh = ctx.get("freshness", {}) or {}
    generated = fresh.get("generated_at")

    # --- risk -----------------------------------------------------------------
    _mk(items, label=f"Campus risk {risk.get('score', 0)}/100 ({risk.get('level', 'LOW')})",
        source_type="risk", metric="risk_score", value=risk.get("score", 0.0),
        severity=_sev_for_level(risk.get("level", "LOW")),
        confidence=0.9, timestamp=generated,
        detail=f"trend {risk.get('trend', 'STABLE')}"
               + (f" · delta {risk.get('delta')}" if risk.get("delta") else ""))
    if risk.get("trend") in ("INCREASING", "DECREASING"):
        _mk(items, label=f"Risk trend {risk['trend']}",
            source_type="risk", metric="risk_trend", value=risk.get("trend"),
            severity="HIGH" if risk["trend"] == "INCREASING" else "INFO",
            timestamp=generated, confidence=0.8,
            detail=f"published score moving {risk.get('delta', 0)} points")
    for f in (risk.get("factors") or [])[:3]:
        _mk(items, label=f"Risk factor · {f.get('label', '')}",
            source_type="risk", metric="risk_factor",
            value=f.get("contribution", 0.0), severity="INFO",
            timestamp=generated, confidence=0.75,
            detail=f"{f.get('label', '')} contributes {f.get('contribution', 0)} "
                   f"points ({f.get('category', '')})")

    # --- simulation -----------------------------------------------------------
    if sim.get("active") or sim.get("status"):
        _mk(items,
            label=f"Simulation {sim.get('type', '')} "
                  f"({'active' if sim.get('active') else sim.get('status', '')})",
            source_type="simulation", metric="scenario",
            value=sim.get("type") or "none",
            source_id=sim.get("simulation_id", ""),
            severity="HIGH" if sim.get("active") else "INFO",
            timestamp=generated, confidence=1.0,
            detail=f"{sim.get('target_name') or 'campus-wide'} · "
                   f"T+{sim.get('elapsed_time', 0)}s · phase {sim.get('phase', 'idle')}")
    if ctx.get("people_at_risk"):
        _mk(items, label=f"{ctx['people_at_risk']} people estimated at risk",
            source_type="simulation", metric="people_at_risk",
            value=int(ctx["people_at_risk"]), severity="HIGH",
            source_id=sim.get("simulation_id", ""),
            timestamp=generated, confidence=0.8,
            detail="aggregated occupancy in affected zones — no person-level data")

    # --- anomalies ------------------------------------------------------------
    for a in (ctx.get("anomalies") or [])[:3]:
        _mk(items,
            label=f"Anomaly {a.get('metric', '')} · {a.get('location', '')}",
            source_type="anomaly", metric=a.get("metric", ""),
            value=a.get("score", 0.0), unit="/100",
            source_id=a.get("id", ""),
            severity=_sev_for_level(a.get("severity", "LOW")),
            timestamp=generated, age_seconds=a.get("age_seconds"),
            confidence=0.7,
            detail=str(a.get("explanation") or a.get("band", ""))[:200])

    # --- predictions ----------------------------------------------------------
    for p in (ctx.get("predictions") or [])[:2]:
        _mk(items,
            label=f"Prediction {p.get('metric', '')} · {p.get('location', '')}",
            source_type="prediction", metric=p.get("metric", ""),
            value=p.get("predicted"),
            source_id=f"{p.get('entity_id', '')}:{p.get('horizon_minutes', '')}",
            severity="INFO", timestamp=generated,
            age_seconds=p.get("age_seconds"), confidence=p.get("confidence"),
            detail=f"{p.get('current')} → {p.get('predicted')} in "
                   f"{p.get('horizon_minutes')} min ({p.get('model', '')})")

    # --- routing --------------------------------------------------------------
    rec = routes.get("recommended")
    if rec:
        _mk(items,
            label=f"Route {rec.get('origin', '')} → {rec.get('destination', '')} "
                  f"({rec.get('status', '')})",
            source_type="route", metric="route_risk",
            value=rec.get("risk_score", 0.0), unit="/100",
            source_id=rec.get("route_id", ""),
            severity=_sev_for_level("HIGH" if rec.get("risk_score", 0) >= 55
                                    else "LOW"),
            timestamp=rec.get("created_at") or generated,
            age_seconds=fresh.get("route_age_s"), confidence=0.9,
            detail=f"mode {rec.get('mode', '')} · "
                   f"{rec.get('distance', 0)}m · {rec.get('estimated_time', 0)}s · "
                   f"{rec.get('reason', '')}")
    exits = routes.get("exit_options") or []
    blocked_exits = [e for e in exits if e.get("status") == "BLOCKED"]
    usable = [e for e in exits if e.get("status") not in ("BLOCKED", "")]
    safest = min(usable, key=lambda e: float(e.get("risk", 999))) if usable else None
    for e in blocked_exits[:3]:
        _mk(items, label=f"Exit {e.get('exit', '')} blocked",
            source_type="route", metric="exit_status", value="BLOCKED",
            source_id=e.get("exit", ""), severity="HIGH",
            timestamp=generated, confidence=0.95,
            detail=f"{e.get('building', '')} · {e.get('reason', '')}")
    if safest:
        _mk(items,
            label=f"Safest exit {safest.get('exit', '')} "
                  f"(risk {safest.get('risk', 0)})",
            source_type="route", metric="exit_risk",
            value=safest.get("risk", 0.0), unit="/100",
            source_id=safest.get("exit", ""),
            severity=_sev_for_level("HIGH" if float(safest.get("risk", 0)) >= 55
                                    else "LOW"),
            timestamp=generated, confidence=0.9,
            detail=f"status {safest.get('status', '')} · "
                   f"ETA {safest.get('evac_time_s', 0)}s · {safest.get('building', '')}")

    # --- congestion / bottlenecks -------------------------------------------
    for b in (ctx.get("bottlenecks") or [])[:2]:
        _mk(items, label=f"Bottleneck · {b.get('location', b.get('location_id', ''))}",
            source_type="bottleneck", metric="congestion",
            value=b.get("congestion"), source_id=b.get("location_id", ""),
            severity=_sev_for_level("HIGH" if str(b.get("severity", "")).upper() == "HIGH"
                                    else "MODERATE"),
            timestamp=generated, confidence=0.85,
            detail=f"{b.get('kind', '')} · {b.get('severity', '')} · "
                   f"{b.get('recommendation', '')}")
    for b in (ctx.get("blocked_paths") or [])[:3]:
        _mk(items, label=f"Blocked path · {b.get('name', b.get('id', ''))}",
            source_type="route", metric="blocked_path",
            value=b.get("id", ""), source_id=b.get("id", ""),
            severity="HIGH", timestamp=generated, confidence=0.95,
            detail=b.get("reason", ""))

    # --- evacuation / recovery ------------------------------------------------
    if evac.get("status") and evac.get("status") != "IDLE":
        _mk(items, label=f"Evacuation status {evac.get('status')}",
            source_type="evacuation", metric="evacuation_status",
            value=evac.get("status"), severity="HIGH"
            if evac.get("status") in ("ACTIVE", "CRITICAL") else "MEDIUM",
            timestamp=generated, confidence=0.9,
            detail=f"{evac.get('people_at_risk', 0)} people · mode "
                   f"{evac.get('mode', '')}")
    if ctx.get("recovery", {}).get("active"):
        _mk(items, label=f"Recovery in progress "
                         f"({ctx['recovery'].get('progress', 0)}%)",
            source_type="simulation", metric="recovery_progress",
            value=ctx["recovery"].get("progress", 0.0), unit="%",
            severity="INFO", timestamp=generated, confidence=0.95,
            detail="emergency state transitioning toward recovery")

    # --- freshness (§16) ------------------------------------------------------
    if fresh.get("sensor_oldest_s") is not None:
        _mk(items, label=f"Sensor data age {fresh['sensor_oldest_s']}s",
            source_type="sensor", metric="data_freshness",
            value=fresh["sensor_oldest_s"], unit="s",
            severity="MEDIUM" if fresh["sensor_oldest_s"] > 60 else "INFO",
            timestamp=generated, confidence=0.9,
            detail=f"oldest of {fresh.get('sensor_count', 0)} healthy sensors")

    # --- incidents ------------------------------------------------------------
    for inc in (ctx.get("incidents") or [])[:1]:
        _mk(items, label=f"Incident · {inc.get('title', '')}",
            source_type="incident", metric="incident",
            value=inc.get("severity", ""), source_id=inc.get("id", ""),
            severity=_sev_for_level(
                {"CRITICAL": "CRITICAL", "HIGH": "HIGH",
                 "MEDIUM": "MODERATE", "LOW": "LOW"}.get(
                     str(inc.get("severity", "")).upper(), "MODERATE")),
            timestamp=generated, confidence=1.0,
            detail=inc.get("kind", ""))

    return items


def grounding(ctx: dict) -> dict:
    """§40 — names/numbers the LLM is allowed to reference."""
    from .context import _names_and_numbers
    return _names_and_numbers(ctx)


def text_numbers(text: str) -> list[float]:
    """Standalone numbers in a narrative string (integers/decimals)."""
    out: list[float] = []
    token = ""
    seen_dot = False
    for ch in str(text) + " ":
        if ch.isdigit() or (ch == "." and token and not seen_dot):
            token += ch
            if ch == ".":
                seen_dot = True
        else:
            if token:
                try:
                    out.append(float(token.rstrip(".")))
                except ValueError:
                    pass
            token, seen_dot = "", False
    return out


def number_grounded(value: float, known: set[float], slack: float = 0.051) -> bool:
    if any(abs(value - n) <= slack for n in known):
        return True
    # integer/decimal presentation variants (275 vs 275.0)
    return any(abs(value - n) <= slack for n in known)


# Small benign integers that carry no factual claim (list ordinals, priorities,
# counts of sections). Anything >= 30 must be grounded in real context data
# (risk scores, people counts, distances, percentages…).
_BENIGN_MAX = 29.0


def ungrounded_numbers(text: str, known: set[float]) -> list[float]:
    return [n for n in text_numbers(text)
            if n > _BENIGN_MAX and not number_grounded(n, known)]
