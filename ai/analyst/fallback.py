"""Phase 8 — deterministic analyst narrative & fallback (§12/§17/§18/§20/§22).

Produces the complete analysis from the normalized context when no LLM is
configured or when the LLM path fails validation. Uses the project's real
risk bands (state.risk_level vocabulary), never invents data, distinguishes
OBSERVED from PREDICTED, and always yields actionable recommendations.

Severity ladder (§22): risk bands drive it; an active incident is at least
HIGH; an ACTIVE/CRITICAL evacuation or risk ≥ 80 is CRITICAL.
"""

from __future__ import annotations

import re
from typing import Any

from .schemas import (
    ChangeItem, PredictedEffect, SEVERITIES, Situation, WhyFactor,
    max_severity, priority_for,
)

_SCENARIO_LABEL = {
    "fire": "Fire", "crowd": "Crowd surge", "power": "Power failure",
    "road": "Road closure", "temperature": "Extreme temperature",
}

_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def severity_of(ctx: dict) -> str:
    risk = ctx.get("risk", {}) or {}
    level = str(risk.get("level", "LOW")).upper()
    if level not in _RANK:
        level = "LOW"
    severity = level
    sim = ctx.get("simulation", {}) or {}
    evac = ctx.get("evacuation", {}) or {}
    if sim.get("active"):
        severity = max_severity(severity, "HIGH")
    if str(evac.get("status", "IDLE")) == "CRITICAL":
        severity = max_severity(severity, "CRITICAL")
    if str(evac.get("status", "IDLE")) == "ACTIVE":
        severity = max_severity(severity, "HIGH")
    try:
        if float(risk.get("score", 0) or 0) >= 80:
            severity = max_severity(severity, "CRITICAL")
    except (TypeError, ValueError):
        pass
    return severity


def _scenario(ctx: dict) -> tuple[dict, str]:
    sim = ctx.get("simulation", {}) or {}
    return sim, _SCENARIO_LABEL.get(str(sim.get("type")), str(sim.get("type") or ""))


def _safest_exit(ctx: dict) -> dict | None:
    exits = (ctx.get("routes") or {}).get("exit_options") or []
    usable = [e for e in exits if e.get("status") not in ("BLOCKED", "")]
    if not usable:
        return None
    return min(usable, key=lambda e: float(e.get("risk", 999)))


def title_for(ctx: dict, severity: str) -> str:
    mode = ctx.get("mode", "CAMPUS")
    sim, label = _scenario(ctx)
    target = sim.get("target_name") or "Campus"
    trend = str((ctx.get("risk") or {}).get("trend", "STABLE"))
    if mode == "RECOVERY" or ctx.get("recovery", {}).get("active"):
        return "Campus Recovery In Progress"
    if mode == "ROUTE":
        rec = (ctx.get("routes") or {}).get("recommended")
        if rec:
            return (f"Route Assessment — {rec.get('origin', '?')} to "
                    f"{rec.get('destination', '?')}")
        return "Evacuation Route Assessment"
    if mode == "BUILDING":
        name = next((b.get("building_name") for b in
                     (ctx.get("evacuation", {}).get("buildings") or [])
                     if b.get("status") in ("ACTIVE", "EVACUATION_CRITICAL")),
                    target)
        return f"{name} Situation Review"
    if mode == "SIMULATION":
        return f"{label or 'Campus'} Simulation — Likely Consequences"
    if sim.get("active"):
        word = "Escalation" if trend == "INCREASING" or severity in ("HIGH", "CRITICAL") \
            else "Response"
        return f"{target} {label or 'Incident'} {word}"
    if severity in ("LOW", "MODERATE"):
        return "Campus Operations Stable"
    return f"Campus Risk {severity}"


def summary_for(ctx: dict, severity: str) -> str:
    risk = ctx.get("risk", {}) or {}
    sim, label = _scenario(ctx)
    score = float(risk.get("score", 0) or 0)
    level = str(risk.get("level", "LOW"))
    trend = str(risk.get("trend", "STABLE")).lower()
    people = int(ctx.get("people_at_risk", 0) or 0)
    sentences: list[str] = []

    if sim.get("active"):
        sentences.append(
            f"{sim.get('target_name') or 'The campus'} is experiencing a simulated "
            f"{(label or str(sim.get('type'))).lower()} emergency.")
    elif ctx.get("recovery", {}).get("active"):
        sentences.append(
            f"The campus is transitioning toward recovery "
            f"({ctx['recovery'].get('progress', 0):.0f}% complete).")
    else:
        sentences.append("Campus conditions are currently stable.")

    sentences.append(
        f"Risk is {level} at {score:.0f}/100 and {trend.replace('_', ' ')}.")
    if people:
        sentences.append(
            f"Approximately {people} people are estimated to be at risk.")
    blocked = [e for e in ((ctx.get("routes") or {}).get("exit_options") or [])
               if e.get("status") == "BLOCKED"]
    safest = _safest_exit(ctx)
    if blocked or safest:
        parts = []
        if blocked:
            parts.append(f"the {blocked[0]['exit']} evacuation path is unavailable")
        if safest:
            parts.append(f"the routing engine identifies {safest['exit']} as the "
                         f"safest available exit (risk {float(safest['risk']):.0f}/100)")
        sentences.append(" ".join(parts).capitalize() + ".")
    if len(sentences) < 4:
        anomalies = ctx.get("anomalies") or []
        if anomalies:
            a = anomalies[0]
            sentences.append(
                f"{len(anomalies)} anomaly/anomalies tracked — top: {a['metric']} "
                f"at {a['location']} (score {a['score']:.0f}).")
        else:
            sentences.append(
                "No high-severity anomalies or active emergency simulations "
                "require immediate intervention.")
    return " ".join(sentences[:5])


def what_is_happening_for(ctx: dict) -> list[str]:
    risk = ctx.get("risk", {}) or {}
    sim, label = _scenario(ctx)
    score = float(risk.get("score", 0) or 0)
    level = str(risk.get("level", "LOW"))
    trend = str(risk.get("trend", "STABLE"))
    people = int(ctx.get("people_at_risk", 0) or 0)
    lines: list[str] = []

    if sim.get("active"):
        lines.append(
            f"{label or 'Emergency'} simulation is active in "
            f"{sim.get('target_name') or 'the campus'} "
            f"(T+{sim.get('elapsed_time', 0):.0f}s, phase {sim.get('phase', 'idle')}).")
    delta = float(risk.get("delta", 0) or 0)
    if abs(delta) >= 1:
        lines.append(
            f"Campus risk has moved {delta:+.0f} points to {score:.0f}/100 "
            f"({level}), trend {trend}.")
    else:
        lines.append(f"Campus risk is {score:.0f}/100 ({level}), trend {trend}.")
    if people:
        lines.append(f"{people} people are currently estimated to be at risk.")
    for b in [e for e in ((ctx.get("routes") or {}).get("exit_options") or [])
              if e.get("status") == "BLOCKED"][:2]:
        lines.append(f"The {b['exit']} evacuation path from {b['building']} is "
                     f"unavailable.")
    rec = (ctx.get("routes") or {}).get("recommended")
    if rec and rec.get("status") == "RECOMMENDED":
        lines.append(
            f"The routing engine recommends {rec.get('destination', 'the exit')} "
            f"via {rec.get('origin', 'the origin')} "
            f"(risk {float(rec.get('risk_score', 0) or 0):.0f}/100, "
            f"mode {rec.get('mode', '')}).")
    evac = ctx.get("evacuation", {}) or {}
    if str(evac.get("status", "IDLE")) != "IDLE":
        lines.append(f"Campus evacuation plan is {evac.get('status')} "
                     f"({evac.get('people_at_risk', 0)} people assigned).")
    anomalies = ctx.get("anomalies") or []
    if anomalies:
        a = anomalies[0]
        lines.append(
            f"{len(anomalies)} active anomal{'y' if len(anomalies) == 1 else 'ies'} "
            f"— {a['metric']} at {a['location']} scoring {a['score']:.0f}/100.")
    if ctx.get("recovery", {}).get("active"):
        lines.append(
            f"Recovery is {ctx['recovery'].get('progress', 0):.0f}% complete — "
            f"conditions are improving.")
    if not lines:
        lines.append("All monitored indicators are within normal bounds.")
    return lines[:6]


def _impact(contribution: float) -> str:
    if contribution >= 12:
        return "HIGH"
    if contribution >= 4:
        return "MEDIUM"
    return "LOW"


def why_for(ctx: dict) -> list[WhyFactor]:
    risk = ctx.get("risk", {}) or {}
    factors: list[WhyFactor] = []
    score = float(risk.get("score", 0) or 0)
    for f in (risk.get("factors") or [])[:4]:
        c = float(f.get("contribution", 0) or 0)
        if c <= 0:
            continue
        factors.append(WhyFactor(
            factor=str(f.get("label", "contributing factor")),
            impact=_impact(c),
            evidence=f"{f.get('label')} contributes {c:.1f} points to the "
                     f"{score:.0f}/100 campus risk score "
                     f"({f.get('category', 'weighted')} factor).",
            source="risk_engine",
        ))
    sim, label = _scenario(ctx)
    if sim.get("active") and ctx.get("affected_zones"):
        zones = ctx["affected_zones"]
        factors.append(WhyFactor(
            factor=f"{label} progression",
            impact="HIGH",
            evidence=f"{len(zones)} zone(s) in "
                     f"{sim.get('target_name') or 'the target'} are "
                     f"{zones[0].get('status')} — simulated conditions are driving "
                     f"sensor readings and zone risk.",
            source="simulation_engine",
        ))
    blocked = [e for e in ((ctx.get("routes") or {}).get("exit_options") or [])
               if e.get("status") == "BLOCKED"]
    if blocked:
        factors.append(WhyFactor(
            factor="Unavailable evacuation path",
            impact="HIGH",
            evidence=f"{blocked[0]['exit']} from {blocked[0]['building']} is "
                     f"reported {blocked[0]['status']} by the routing engine"
                     + (f" ({blocked[0].get('reason')})" if blocked[0].get("reason") else "")
                     + ".",
            source="route_optimizer",
        ))
    bn = (ctx.get("bottlenecks") or [None])[0]
    if bn:
        factors.append(WhyFactor(
            factor="Congestion bottleneck",
            impact="HIGH" if str(bn.get("severity", "")).upper() == "HIGH" else "MEDIUM",
            evidence=f"{bn.get('location', bn.get('location_id', ''))} — "
                     f"{bn.get('kind', 'edge')} {bn.get('severity', '')}: "
                     f"{bn.get('recommendation', 'capacity under pressure')}",
            source="congestion_engine",
        ))
    if not factors:
        factors.append(WhyFactor(
            factor="All indicators within bounds",
            impact="LOW",
            evidence="No elevated risk factors, anomalies or blocked routes in "
                     "the current context.",
            source="risk_engine",
        ))
    return factors[:5]


def affected_areas_for(ctx: dict) -> list[str]:
    out: list[str] = []
    sim = ctx.get("simulation", {}) or {}
    if sim.get("target_name"):
        out.append(str(sim["target_name"]))
    for b in (ctx.get("evacuation", {}) or {}).get("buildings", []):
        if b.get("status") in ("ACTIVE", "EVACUATION_CRITICAL") and b.get("building_name"):
            out.append(str(b["building_name"]))
    for z in ctx.get("affected_zones", []):
        # zone → building name via _state_names lookup is unnecessary: the
        # building id is mapped by the service; keep zone names visible.
        out.append(str(z.get("name", "")))
    for a in (ctx.get("anomalies") or [])[:3]:
        if a.get("location"):
            out.append(str(a["location"]))
    seen: list[str] = []
    for name in out:
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return ["Campus-wide (no localised impact)"]
    return seen[:5]


def predicted_effects_for(ctx: dict) -> list[PredictedEffect]:
    effects: list[PredictedEffect] = []
    for p in (ctx.get("predictions") or [])[:3]:
        try:
            cur, predv = float(p.get("current") or 0), float(p.get("predicted") or 0)
        except (TypeError, ValueError):
            continue
        direction = "rise" if predv >= cur else "fall"
        delta = abs(predv - cur)
        if delta < 1:
            continue
        conf = float(p.get("confidence") or 0.0)
        effects.append(PredictedEffect(
            effect=(f"{str(p.get('metric', '')).capitalize()} at "
                    f"{p.get('location', '')} may {direction} {cur:.0f} → "
                    f"{predv:.0f} over the next {p.get('horizon_minutes')} minutes."),
            likelihood="HIGH" if conf >= 0.75 else ("MEDIUM" if conf >= 0.5 else "LOW"),
            time_horizon=f"{p.get('horizon_minutes')} minutes",
            kind="PREDICTED",
            source=f"prediction_engine:{p.get('model', '')}",
            metric=str(p.get("metric", "")),
        ))
    sim = ctx.get("simulation", {}) or {}
    risk = ctx.get("risk", {}) or {}
    score = float(risk.get("score", 0) or 0)
    if sim.get("active"):
        likelihood = "HIGH" if score >= 60 or str(risk.get("trend")) == "INCREASING" \
            else "MEDIUM"
        effects.append(PredictedEffect(
            effect=("Evacuation demand and route pressure may increase if the "
                    "simulation continues."),
            likelihood=likelihood, time_horizon="5-10 minutes", kind="PREDICTED",
            source="simulation_engine", metric="people_at_risk",
        ))
    bn = (ctx.get("bottlenecks") or [None])[0]
    if bn:
        effects.append(PredictedEffect(
            effect=(f"Congestion at {bn.get('location', bn.get('location_id', ''))} "
                    f"may worsen under evacuation load."),
            likelihood="MEDIUM", time_horizon="10-15 minutes", kind="PREDICTED",
            source="congestion_engine", metric="congestion",
        ))
    if ctx.get("recovery", {}).get("active") or ctx.get("mode") == "RECOVERY":
        effects.append(PredictedEffect(
            effect=("Previously restricted routes are expected to reopen as risk "
                    "decays and recovery completes."),
            likelihood="HIGH",
            time_horizon=f"within {max(1, round(100 - ctx.get('recovery', {}).get('progress', 100))):.0f}%",
            kind="PREDICTED", source="recovery_engine", metric="risk_score",
        ))
    if not effects:
        effects.append(PredictedEffect(
            effect="Conditions are expected to remain stable over the next 20 minutes.",
            likelihood="LOW", time_horizon="20 minutes", kind="PREDICTED",
            source="risk_engine", metric="risk_score",
        ))
    return effects[:4]


def situation_for(ctx: dict) -> Situation:
    severity = severity_of(ctx)
    mode = str(ctx.get("mode", "CAMPUS")).upper()
    return Situation(
        title=title_for(ctx, severity),
        summary=summary_for(ctx, severity),
        severity=severity,
        priority=priority_for(severity),
        mode=mode if mode in ("INCIDENT", "CAMPUS", "BUILDING", "ROUTE",
                              "SIMULATION", "RECOVERY") else "CAMPUS",
    )


def system_narrative(ctx: dict) -> dict:
    """The complete deterministic narrative — used as fallback AND as the
    baseline the LLM may rephrase (facts stay system-owned)."""
    situation = situation_for(ctx)
    return {
        "title": situation.title,
        "summary": situation.summary,
        "severity": situation.severity,
        "priority": situation.priority,
        "what_is_happening": what_is_happening_for(ctx),
        "why": [w.model_dump() for w in why_for(ctx)],
        "affected_areas": affected_areas_for(ctx),
        "predicted_effects": [p.model_dump() for p in predicted_effects_for(ctx)],
    }


def legacy_fields(narrative: dict, recommendations: list[Any],
                  confidence: dict) -> dict:
    """§7 back-compat — Phase 5 flat keys derived from the structured result."""
    what = " ".join(narrative.get("what_is_happening", [])[:3]) or narrative.get("summary", "")
    why_list = narrative.get("why") or []
    why = (f"{narrative.get('title')} — " + " ".join(
        f.get("evidence", f.get("factor", "")) for f in why_list[:2])
        if why_list else narrative.get("summary", ""))
    likely_list = narrative.get("predicted_effects") or []
    likely = likely_list[0].get("effect", "") if likely_list else \
        "No escalation expected in the near term."
    if recommendations:
        top = recommendations[0]
        action = f"{top.action}. {top.reason}"
    else:
        action = "Continue routine monitoring."
    return {
        "what_happened": what,
        "why_it_matters": why,
        "likely_next": likely,
        "recommended_action": action,
    }


def answer_question(question: str, ctx: dict, narrative: dict,
                    recommendations: list[Any], confidence: dict) -> str:
    """§54 — lightweight operator queries answered ONLY from structured data."""
    q = str(question or "").strip().lower()
    if not q:
        return ""
    risk = ctx.get("risk", {}) or {}
    score = float(risk.get("score", 0) or 0)
    level = str(risk.get("level", "LOW"))
    rec = (ctx.get("routes") or {}).get("recommended")

    route_change = next((c.message for c in _change_items(ctx)
                         if c.kind.startswith("route")), "")
    if "route" in q and ("change" in q or "why" in q):
        if route_change:
            return route_change
        if rec:
            return (f"The active route is {rec.get('origin', '?')} to "
                    f"{rec.get('destination', '?')} — status {rec.get('status', '?')}, "
                    f"risk {float(rec.get('risk_score', 0) or 0):.0f}/100, "
                    f"mode {rec.get('mode', '')} "
                    f"(plan {rec.get('route_id', '')}, version "
                    f"{rec.get('route_version', '')}).")
        return "No active route plan is currently stored."
    if "why" in q and "risk" in q:
        factors = narrative.get("why") or []
        top = "; ".join(f.get("evidence", f.get("factor", "")) for f in factors[:3])
        return (f"Risk is {level} at {score:.0f}/100 because: {top} "
                f"Trend: {risk.get('trend', 'STABLE')}.")
    if "confidence" in q:
        notes = " ".join(confidence.get("notes", [])) or "All evidence streams fresh."
        return (f"Confidence is {confidence.get('level')} "
                f"({float(confidence.get('overall', 0)) * 100:.0f}%). {notes}")
    if "people" in q or "at risk" in q:
        return (f"{ctx.get('people_at_risk', 0)} people are estimated at risk. "
                f"Affected: {', '.join(narrative.get('affected_areas', []))}.")
    if "route" in q or "exit" in q or "gate" in q or "safe" in q:
        ra = narrative.get("route_assessment") or {}
        if ra.get("recommended_route"):
            return (f"The recommended exit is {ra['recommended_route']} "
                    f"(risk {ra.get('risk', 0):.0f}/100, "
                    f"{ra.get('estimated_time', 0):.0f}s) — {ra.get('reason', '')}")
        return "No route plan is active — request a route calculation first."
    if "should" in q or "recommend" in q or "do now" in q:
        if recommendations:
            top = recommendations[0]
            return f"{top.action}. {top.reason}"
        return narrative.get("summary", "")
    return narrative.get("summary", "")


def _change_items(ctx: dict) -> list[ChangeItem]:
    return [ChangeItem(kind=k, message=m, previous=p, current=c)
            for k, m, p, c in (ctx.get("_changes") or [])]


_NUMBERS = re.compile(r"\d+")
