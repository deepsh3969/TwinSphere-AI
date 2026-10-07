"""Phase 8 — analyst orchestration (§7/§26/§28/§39/§44).

Single entry point for one analysis run: evidence → confidence →
deterministic recommendations → narrative (LLM or fallback, semantically
validated) → strict ``AnalystResult``. Severity, priority and recommendations
are system-owned; the provider only shapes wording.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import fallback, recommendations
from .confidence import compute_confidence
from .evidence import extract_evidence
from .providers import (
    AnalystProvider, DeterministicProvider, LLMConfig, LLMProvider,
)
from .schemas import (
    AnalystResult, ChangeItem, ConfidenceBlock, PredictedEffect,
    RouteAssessment, Situation, WhyFactor,
)


def new_analysis_id() -> str:
    return f"anl_{uuid.uuid4().hex[:12]}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def route_assessment_for(ctx: dict) -> RouteAssessment:
    """§7 — copy the route engine verdict; never recompute a route here."""
    routes = ctx.get("routes", {}) or {}
    rec = routes.get("recommended")
    exit_options = routes.get("exit_options") or []
    usable = [e for e in exit_options if e.get("status") not in ("BLOCKED", "")]

    if rec:
        destination = str(rec.get("destination_label") or rec.get("destination") or "")
        alternatives = [e["exit"] for e in usable
                        if e.get("exit") and e["exit"] != destination][:3]
        return RouteAssessment(
            recommended_route=destination,
            route_id=str(rec.get("route_id", "")),
            origin=str(rec.get("origin_label") or rec.get("origin") or ""),
            destination=str(rec.get("destination") or ""),
            mode=str(rec.get("mode", "")),
            reason=str(rec.get("reason", "")),
            risk=float(rec.get("risk_score", 0.0) or 0.0),
            estimated_time=float(rec.get("estimated_time", 0.0) or 0.0),
            status=str(rec.get("status", "")),
            alternatives=alternatives,
        )
    if usable:
        safest = min(usable, key=lambda e: float(e.get("risk", 999)))
        alternatives = [e["exit"] for e in usable
                        if e.get("exit") != safest.get("exit")][:3]
        return RouteAssessment(
            recommended_route=str(safest.get("exit", "")),
            origin=str(safest.get("building", "")),
            destination=str(safest.get("exit", "")),
            reason=str(safest.get("reason", "")
                       or f"lowest-risk available exit (status {safest.get('status', '')})"),
            risk=float(safest.get("risk", 0.0) or 0.0),
            estimated_time=float(safest.get("evac_time_s", 0.0) or 0.0),
            status=str(safest.get("status", "")),
            alternatives=alternatives,
        )
    return RouteAssessment()


def what_changed_for(ctx: dict, previous: dict | None) -> list[ChangeItem]:
    """§28 — populated ONLY when the previous context confirms the change."""
    if not previous:
        return []
    changes: list[ChangeItem] = []

    prev_risk = previous.get("risk", {}) or {}
    cur_risk = ctx.get("risk", {}) or {}
    prev_level = str(prev_risk.get("level", "LOW"))
    cur_level = str(cur_risk.get("level", "LOW"))
    prev_score = float(prev_risk.get("score", 0) or 0)
    cur_score = float(cur_risk.get("score", 0) or 0)
    if prev_level != cur_level:
        changes.append(ChangeItem(
            kind="risk_change",
            message=f"Campus risk moved from {prev_level} ({prev_score:.0f}/100) "
                    f"to {cur_level} ({cur_score:.0f}/100).",
            previous=f"{prev_level} {prev_score:.0f}", current=f"{cur_level} {cur_score:.0f}",
        ))
    elif abs(cur_score - prev_score) >= 5:
        changes.append(ChangeItem(
            kind="risk_change",
            message=f"Campus risk moved {cur_score - prev_score:+.0f} points to "
                    f"{cur_score:.0f}/100 ({cur_level}).",
            previous=f"{prev_score:.0f}", current=f"{cur_score:.0f}",
        ))

    prev_rec = (previous.get("routes", {}) or {}).get("recommended") or {}
    cur_rec = (ctx.get("routes", {}) or {}).get("recommended") or {}
    if prev_rec and cur_rec:
        same = (prev_rec.get("route_id") == cur_rec.get("route_id")
                and prev_rec.get("status") == cur_rec.get("status")
                and prev_rec.get("route_version") == cur_rec.get("route_version"))
        if not same:
            changes.append(ChangeItem(
                kind="route_change",
                message=(f"Route changed from {prev_rec.get('origin', '?')}→"
                         f"{prev_rec.get('destination', '?')} "
                         f"({prev_rec.get('status', '?')}, v{prev_rec.get('route_version', 0)}) "
                         f"to {cur_rec.get('origin', '?')}→{cur_rec.get('destination', '?')} "
                         f"({cur_rec.get('status', '?')}, v{cur_rec.get('route_version', 0)})."),
                previous=f"{prev_rec.get('route_id', '')} v{prev_rec.get('route_version', 0)}",
                current=f"{cur_rec.get('route_id', '')} v{cur_rec.get('route_version', 0)}",
            ))
    elif bool(prev_rec) != bool(cur_rec):
        changes.append(ChangeItem(
            kind="route_change",
            message=("A new route plan is now active: "
                     f"{cur_rec.get('origin', '?')}→{cur_rec.get('destination', '?')} "
                     f"({cur_rec.get('status', '?')})." if cur_rec else
                     "The active route plan was cleared."),
            previous="plan" if prev_rec else "none",
            current="plan" if cur_rec else "none",
        ))

    prev_sim = previous.get("simulation", {}) or {}
    cur_sim = ctx.get("simulation", {}) or {}
    if (prev_sim.get("simulation_id") != cur_sim.get("simulation_id")
            or prev_sim.get("status") != cur_sim.get("status")):
        changes.append(ChangeItem(
            kind="simulation_change",
            message=(f"Simulation state changed from {prev_sim.get('status') or 'none'} "
                     f"to {cur_sim.get('status') or 'none'}"
                     + (f" ({cur_sim.get('type')})" if cur_sim.get("type") else "") + "."),
            previous=str(prev_sim.get("status") or "none"),
            current=str(cur_sim.get("status") or "none"),
        ))

    prev_evac = (previous.get("evacuation", {}) or {}).get("status", "IDLE")
    cur_evac = (ctx.get("evacuation", {}) or {}).get("status", "IDLE")
    if prev_evac != cur_evac:
        changes.append(ChangeItem(
            kind="evacuation_change",
            message=f"Evacuation status changed from {prev_evac} to {cur_evac}.",
            previous=str(prev_evac), current=str(cur_evac),
        ))

    prev_people = int(previous.get("people_at_risk", 0) or 0) // 10
    cur_people = int(ctx.get("people_at_risk", 0) or 0) // 10
    if prev_people != cur_people:
        changes.append(ChangeItem(
            kind="people_change",
            message=(f"People estimated at risk moved from "
                     f"{previous.get('people_at_risk', 0)} to "
                     f"{ctx.get('people_at_risk', 0)}."),
            previous=str(previous.get("people_at_risk", 0)),
            current=str(ctx.get("people_at_risk", 0)),
        ))
    return changes[:6]


async def run_analysis(
    ctx: dict,
    *,
    question: str = "",
    llm: LLMConfig | None = None,
    provider: AnalystProvider | None = None,
    previous: dict | None = None,
    analysis_id: str | None = None,
) -> AnalystResult:
    """One full analysis run over a normalized context (§26)."""
    started = time.perf_counter()
    question = str(question or ctx.get("question") or "")[:500]
    analysis_id = analysis_id or new_analysis_id()
    evidence = extract_evidence(ctx)
    conf = compute_confidence(ctx, evidence)
    recs = recommendations.generate(ctx, evidence, conf)
    for i, card in enumerate(recs):
        if not card.id:
            card.id = f"{analysis_id}_r{i + 1}"
    # analysis-scoped evidence ids — the persisted primary key is the payload
    # id itself, so GET /api/ai/evidence/{id} resolves straight from a result
    id_map = {ev.id: f"{analysis_id}:{ev.id}" for ev in evidence}
    for ev in evidence:
        ev.id = id_map[ev.id]
    for card in recs:
        card.evidence_ids = [id_map.get(e, e) for e in card.evidence_ids]
    baseline = fallback.system_narrative(ctx)

    if provider is None:
        provider = LLMProvider(llm) if (llm and llm.enabled) \
            else DeterministicProvider()
    outcome = await provider.analyze(ctx, baseline, question)
    narrative = outcome.narrative

    situation = Situation(
        title=str(narrative.get("title") or baseline["title"]),
        summary=str(narrative.get("summary") or baseline["summary"]),
        severity=baseline["severity"],          # system-owned (§35)
        priority=baseline["priority"],
        mode=str(ctx.get("mode", "CAMPUS")),
    )
    why = [WhyFactor.model_validate(w) for w in (narrative.get("why") or [])]
    effects = [PredictedEffect.model_validate(p)
               for p in (narrative.get("predicted_effects") or [])]
    route = route_assessment_for(ctx)
    changes = what_changed_for(ctx, previous)
    legacy = fallback.legacy_fields(narrative, recs, conf)

    query_answer = ""
    if question:
        merged = dict(narrative)
        merged["route_assessment"] = route.model_dump()
        query_answer = fallback.answer_question(question, ctx, merged, recs, conf)

    latency = int((time.perf_counter() - started) * 1000)
    return AnalystResult(
        analysis_id=analysis_id,
        timestamp=str(ctx.get("timestamp") or _iso_now()),
        mode=str(ctx.get("mode", "CAMPUS")),
        situation=situation,
        what_is_happening=[str(x)[:300] for x in
                           (narrative.get("what_is_happening") or [])][:8],
        why=why,
        affected_areas=[str(a)[:80] for a in (narrative.get("affected_areas") or [])][:6],
        predicted_effects=effects,
        recommendations=recs,
        route_assessment=route,
        confidence=ConfidenceBlock(
            overall=float(conf["overall"]), level=str(conf["level"]),
            components=list(conf["components"]), notes=list(conf["notes"]),
        ),
        human_decision_required=True,
        evidence=evidence,
        what_changed=changes,
        provider=outcome.provider,
        model=outcome.model,
        source=outcome.status,
        status="completed",
        latency_ms=latency,
        simulation_id=str((ctx.get("simulation") or {}).get("simulation_id", "")),
        question=str(question or "")[:500],
        query_answer=query_answer,
        note=outcome.error,
        **legacy,
        context_summary=ctx,
        generated_at=time.time(),
    )
