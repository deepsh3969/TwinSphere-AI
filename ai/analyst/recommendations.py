"""Phase 8 — deterministic recommendation engine (§21/§23/§24).

Recommendations are ALWAYS generated from system state — never from the LLM.
Each card carries action, reason, evidence strings (with real values),
confidence and `requires_human_approval: true`. The Analyst recommends; it
never executes (§24).
"""

from __future__ import annotations

from typing import Any

from .schemas import RecommendationCard

# category → sort rank (lower first)
_RANK = {
    "EVACUATION": 0, "RECOVERY": 0, "RESPONSE": 1, "ROUTE": 2,
    "MONITORING": 3, "PREDICTION": 4, "GENERAL": 5,
}

_BAND_ORDER = ["LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL"]


def _next_band(level: str) -> str:
    i = _BAND_ORDER.index(level.upper()) if level.upper() in _BAND_ORDER else 0
    return _BAND_ORDER[min(len(_BAND_ORDER) - 1, i + 1)]


def _ev_label(e: Any) -> str:
    return f"{e.label} — {e.detail}" if getattr(e, "detail", "") else e.label


def _evidence_ids(evidence: list[Any], metrics: tuple[str, ...]) -> list[str]:
    return [e.id for e in evidence if e.metric in metrics]


def generate(ctx: dict, evidence: list[Any], confidence: dict) -> list[RecommendationCard]:
    risk = ctx.get("risk", {}) or {}
    sim = ctx.get("simulation", {}) or {}
    routes = ctx.get("routes", {}) or {}
    evac = ctx.get("evacuation", {}) or {}
    rec = routes.get("recommended")
    exits = routes.get("exit_options") or []
    blocked = [e for e in exits if e.get("status") == "BLOCKED"]
    usable = [e for e in exits if e.get("status") not in ("BLOCKED", "")]
    safest = min(usable, key=lambda e: float(e.get("risk", 999))) if usable else None
    people = int(ctx.get("people_at_risk", 0) or 0)
    level = str(risk.get("level", "LOW"))
    score = float(risk.get("score", 0) or 0)
    base_conf = float(confidence.get("overall", 0.5) or 0.5)
    incident = bool(sim.get("active"))
    evac_active = str(evac.get("status", "IDLE")) in ("ACTIVE", "CRITICAL")

    cards: list[tuple[str, RecommendationCard]] = []
    risk_ev = _evidence_ids(evidence, ("risk_score", "risk_trend"))
    people_ev = _evidence_ids(evidence, ("people_at_risk",))

    # 1) evacuation through the safest available exit ------------------------
    if (incident or evac_active) and (safest or rec):
        dest = safest["exit"] if safest else (
            rec.get("destination_label") or rec.get("destination") or "the mapped exit")
        exit_risk = safest["risk"] if safest else float(rec.get("risk_score", 0) or 0)
        ev_strs = [f"Campus risk {score:.0f}/100 ({level})"]
        if people:
            ev_strs.append(f"{people} people estimated at risk")
        if blocked:
            ev_strs.append("Blocked exits: "
                           + ", ".join(f"{b['exit']} ({b['risk']:.0f})"
                                       if b.get("risk") is not None else b["exit"]
                                       for b in blocked[:3]))
        ev_strs.append(f"Safest available exit {dest} route risk {exit_risk:.0f}/100")
        if rec:
            ev_strs.append(f"Active plan {rec.get('origin', '')}→"
                           f"{rec.get('destination', '')} "
                           f"{rec.get('status', '')} (mode {rec.get('mode', '')})")
        reason = (f"The route optimizer rates {dest} as the lowest-risk available "
                  f"exit (risk {exit_risk:.0f}/100)"
                  + (f" while {', '.join(b['exit'] for b in blocked[:2])} "
                     f"is unavailable" if blocked else "")
                  + f". Campus risk is {score:.0f}/100 ({level}).")
        cards.append(("EVACUATION", RecommendationCard(
            priority=1,
            action=f"Prioritize evacuation through {dest}",
            reason=reason,
            evidence=ev_strs,
            confidence=min(0.95, base_conf + (0.03 if rec and rec.get("status") == "RECOMMENDED" else 0.0)),
            category="EVACUATION",
            evidence_ids=(risk_ev + people_ev +
                          _evidence_ids(evidence, ("exit_risk", "exit_status", "route_risk"))),
            focus={"exit": dest, "route_id": rec.get("route_id", "") if rec else ""},
        )))

    # 2) keep emergency corridors clear ---------------------------------------
    blocked_paths = ctx.get("blocked_paths") or []
    if incident and blocked_paths:
        names = ", ".join(b.get("name", b.get("id", "")) for b in blocked_paths[:2])
        cards.append(("RESPONSE", RecommendationCard(
            priority=1,
            action="Maintain access on remaining emergency corridors",
            reason=(f"{names} unavailable — response travel times rise on the "
                    f"remaining network, so keep gates and service roads clear."),
            evidence=[f"Blocked paths: {names}",
                      f"Campus risk {score:.0f}/100 ({level})"],
            confidence=min(0.95, base_conf + 0.02),
            category="RESPONSE",
            evidence_ids=_evidence_ids(evidence, ("blocked_path",)) or risk_ev,
            focus={},
        )))

    # 3) monitor degrading route / bottleneck ---------------------------------
    bottleneck = (ctx.get("bottlenecks") or [None])[0]
    not_recommended = rec and rec.get("status") in ("NOT_RECOMMENDED", "BLOCKED")
    if bottleneck or not_recommended or (blocked and not incident):
        where = (bottleneck.get("location") or bottleneck.get("location_id")
                 if bottleneck else (blocked[0]["exit"] if blocked else
                                     (rec.get("destination", "active route") if rec else "active route")))
        detail = (bottleneck.get("recommendation") if bottleneck else None) or (
            f"status {rec.get('status')}" if not_recommended else "exit unavailable")
        cards.append(("ROUTE", RecommendationCard(
            priority=1,
            action=f"Monitor {where} — route capacity under pressure",
            reason=(f"{detail}. Congestion/risk here degrades evacuation and "
                    f"response times if it worsens."),
            evidence=([f"Bottleneck: {bottleneck.get('location', '')} "
                       f"({bottleneck.get('severity', '')})"] if bottleneck else [])
            + [f"Campus risk {score:.0f}/100 ({level})"],
            confidence=min(0.9, base_conf),
            category="MONITORING",
            evidence_ids=_evidence_ids(evidence, ("congestion", "route_risk", "exit_status")),
            focus={},
        )))

    # 4) monitor the risk driver ----------------------------------------------
    watch_needed = level in ("MODERATE", "ELEVATED", "HIGH", "CRITICAL")
    if watch_needed and not (incident and not cards):
        factor = (risk.get("factors") or [{}])[0]
        label = factor.get("label") or "campus risk drivers"
        cards.append(("MONITORING", RecommendationCard(
            priority=1,
            action=f"Monitor {label} — risk at {score:.0f}/100 ({level})",
            reason=(f"Risk is {level} and may reach {_next_band(level)} if the "
                    f"top contributing factor keeps rising."),
            evidence=[f"Campus risk {score:.0f}/100 ({level})",
                      f"Top factor: {label} "
                      f"(contribution {factor.get('contribution', 0)})",
                      f"Trend: {risk.get('trend', 'STABLE')}"],
            confidence=min(0.9, base_conf),
            category="MONITORING",
            evidence_ids=risk_ev + _evidence_ids(evidence, ("risk_factor",)),
            focus={},
        )))

    # 5) prediction-driven preparation ----------------------------------------
    for p in (ctx.get("predictions") or [])[:4]:
        try:
            cur, predv = float(p.get("current") or 0), float(p.get("predicted") or 0)
        except (TypeError, ValueError):
            continue
        rise = predv - cur
        if p.get("metric") == "occupancy" and rise >= 15:
            cards.append(("PREDICTION", RecommendationCard(
                priority=1,
                action=(f"Prepare for occupancy increase at {p.get('location', '')} "
                        f"({cur:.0f} → {predv:.0f})"),
                reason=(f"The prediction engine forecasts +{rise:.0f} occupants "
                        f"within {p.get('horizon_minutes')} min if the trend "
                        f"continues — evacuation demand would rise with it."),
                evidence=[f"{p.get('metric')} {cur:.0f} → {predv:.0f} "
                          f"in {p.get('horizon_minutes')} min",
                          f"Model confidence {float(p.get('confidence') or 0):.2f} "
                          f"({p.get('model', '')})"],
                confidence=min(0.9, 0.5 + float(p.get("confidence") or 0.5) / 2),
                category="PREDICTION",
                evidence_ids=_evidence_ids(evidence, ("prediction", )) or
                             _evidence_ids(evidence, ("risk_score",)),
                focus={},
            )))
            break

    # 6) recovery posture -------------------------------------------------------
    if ctx.get("mode") == "RECOVERY" or ctx.get("recovery", {}).get("active"):
        cards.append(("RECOVERY", RecommendationCard(
            priority=1,
            action="Confirm recovery posture before standing down",
            reason=(f"Conditions are improving (recovery "
                    f"{ctx.get('recovery', {}).get('progress', 0):.0f}%, risk trend "
                    f"{risk.get('trend', 'STABLE')}) — verify restricted routes "
                    f"have reopened before lifting emergency measures."),
            evidence=[f"Risk trend: {risk.get('trend', 'STABLE')}",
                      f"Campus risk {score:.0f}/100 ({level})",
                      f"Recovery progress {ctx.get('recovery', {}).get('progress', 0):.0f}%"],
            confidence=min(0.95, base_conf + 0.02),
            category="RECOVERY",
            evidence_ids=risk_ev,
            focus={},
        )))

    # 7) quiet campus -----------------------------------------------------------
    if not cards:
        cards.append(("GENERAL", RecommendationCard(
            priority=1,
            action="Continue routine monitoring",
            reason=(f"Campus conditions are stable — risk {score:.0f}/100 ({level}), "
                    f"no active emergency simulation requires intervention."),
            evidence=[f"Campus risk {score:.0f}/100 ({level})",
                      f"Active incidents: {ctx.get('campus', {}).get('active_incidents', 0)}",
                      f"Anomalies tracked: {len(ctx.get('anomalies') or [])}"],
            confidence=min(0.95, base_conf + 0.05),
            category="GENERAL",
            evidence_ids=risk_ev,
            focus={},
        )))

    cards.sort(key=lambda t: (_RANK.get(t[0], 9), -t[1].confidence))
    out: list[RecommendationCard] = []
    for i, (_, card) in enumerate(cards[:5]):
        card.priority = i + 1
        out.append(card)
    return out
