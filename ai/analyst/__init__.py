"""AI Analyst — evidence-grounded decision support (Phase 8, §1–§66).

Public surface::

    from ai.analyst import analyze, run_analysis, build_context, LLMConfig

* ``build_context(state, ...)`` — normalized context (§5) from live state.
* ``run_analysis(ctx, ...)`` — full structured ``AnalystResult`` run (§26).
* ``analyze(context, api_key, model, base_url)`` — back-compatible entry: the
  Phase-8 context gets the full pipeline, a legacy Phase-5 context gets the
  original flat explanation (both end in a deterministic fallback when no LLM
  is configured or the call fails — the platform never blocks on the LLM).

The LLM (when configured) only rephrases narrative wording; numerical
decisions, severity, confidence and recommendations always come from the
deterministic engines.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .analyst import new_analysis_id, route_assessment_for, run_analysis, what_changed_for
from .confidence import compute_confidence
from .context import MODES, build_context, context_signature, detect_mode, scrub
from .evidence import extract_evidence, grounding, ungrounded_numbers
from .fallback import answer_question, system_narrative
from .prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_json
from .providers import (
    AnalystProvider, DeterministicProvider, LLMConfig, LLMProvider, Narrative,
    semantic_validate, ungrounded_entities,
)
from .recommendations import generate as generate_recommendations
from .schemas import (
    AnalystResult, ChangeItem, ConfidenceBlock, EvidenceItem, PredictedEffect,
    RecommendationCard, RouteAssessment, Situation, WhyFactor,
)

log = logging.getLogger("twinsphere.analyst")

__all__ = [
    "analyze", "run_analysis", "build_context", "detect_mode", "scrub",
    "context_signature", "SYSTEM_PROMPT", "LLMConfig", "AnalystResult",
    "EvidenceItem", "RecommendationCard", "RouteAssessment", "ConfidenceBlock",
    "Situation", "ChangeItem", "WhyFactor", "PredictedEffect",
    "AnalystProvider", "DeterministicProvider", "LLMProvider", "Narrative",
    "extract_evidence", "compute_confidence", "generate_recommendations",
    "system_narrative", "answer_question", "semantic_validate",
    "ungrounded_entities", "ungrounded_numbers", "grounding",
    "build_user_prompt", "parse_llm_json", "route_assessment_for",
    "what_changed_for", "new_analysis_id", "MODES",
]


def _is_phase8_context(context: dict[str, Any]) -> bool:
    return ("mode" in context and "risk" in context
            and ("signature" in context or "campus" in context))


async def analyze(context: dict[str, Any], api_key: str = "", model: str = "",
                  base_url: str = "") -> dict[str, Any]:
    """Back-compatible entry point (Phase 5 contract kept intact)."""
    if _is_phase8_context(context):
        result = await run_analysis(
            context,
            question=str(context.get("question") or ""),
            llm=LLMConfig(api_key=api_key, model=model or "gpt-4o-mini",
                          base_url=base_url or "https://api.openai.com/v1"),
        )
        return result.legacy_dict()
    if not api_key:
        return _legacy_fallback(context)
    try:
        import httpx

        payload = {
            "model": model or "gpt-4o-mini",
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context, default=str)},
            ],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        parsed["source"] = "llm"
        parsed["model"] = model or "gpt-4o-mini"
        return parsed
    except Exception as exc:  # pragma: no cover - network dependent
        log.warning("LLM analyst unavailable (%s); using local fallback", exc)
        out = _legacy_fallback(context)
        out["source"] = "local_fallback"
        out["note"] = f"LLM unavailable ({type(exc).__name__}) — local fallback active."
        return out


def _legacy_fallback(context: dict[str, Any]) -> dict[str, Any]:
    """Original Phase-5 flat explanation for legacy-shaped contexts."""
    risk = context.get("risk", {}) or {}
    score = risk.get("score", 0)
    level = risk.get("level", "LOW")
    sim = context.get("active_sim") or {}
    scenario = sim.get("scenario")
    target = sim.get("target_id") or context.get("target_id")
    target_name = context.get("target_name") or target or "campus"
    routes = context.get("routes") or []
    safe = [r for r in routes if r.get("status") == "SAFE"]
    factors = [f.get("label") for f in (risk.get("factors") or []) if f.get("label")]
    metrics = context.get("metrics") or {}
    people = sim.get("people_at_risk") or metrics.get("people_at_risk") or 0

    if scenario == "fire" and sim:
        what = (
            f"A fire emergency is active in {target_name} (sim time T+{sim.get('t', 0):.0f}s). "
            f"Campus risk is {score}/100 ({level}). {people} people are currently in affected zones."
        )
        why = (
            "Occupied zones near the ignition are losing safe exit capacity as smoke spreads; "
            "delayed evacuation would push risk into the CRITICAL band."
        )
        likely = (
            f"Without intervention, spread continues downwind and risk is projected to reach "
            f"{min(100, score + 18):.0f}/100 within 10 minutes."
        )
        if safe:
            best = sorted(safe, key=lambda r: (r.get("risk", 0), r.get("eta_s", 999)))[0]
            action = (
                f"Evacuate {target_name} via {best.get('exit_name', best.get('exit_id'))} "
                f"(ETA {best.get('eta_s', 0):.0f}s, route risk {best.get('risk', 0):.0f}). "
                f"Keep responders on the incident side and shut the nearest internal road."
            )
        else:
            action = "No safe route available — hold occupants in place and deploy response teams to clear a path."
    elif scenario == "power":
        what = f"Power failure simulated in {target_name}. Campus risk is {score}/100 ({level})."
        why = "Backup capacity determines which life-safety services stay online."
        likely = "Non-backup floors lose HVAC and elevators; temperature will climb within 15 minutes."
        action = "Activate backup supply and prioritise clinic + emergency systems."
    elif scenario == "crowd":
        what = f"Crowd surge in {target_name}: occupancy {metrics.get('occupancy')} ({metrics.get('occupancy_pct')}%)."
        why = "Density above 85% of capacity sharply increases crush and evacuation-time risk."
        likely = "Peak density expected in ~10 minutes unless flow is throttled."
        action = "Open adjacent buildings as overflow, throttle entry, and stage stewards at the nearest junction."
    elif scenario == "road":
        what = f"Road closure active ({context.get('closed_road', 'selected road')}). Campus risk {score}/100 ({level})."
        why = "Emergency response travel times increase on remaining corridors."
        likely = "Response ETA degrades further if a second corridor is lost."
        action = "Reroute service traffic via the ring road and keep both emergency gates clear."
    elif scenario == "temperature":
        what = f"Extreme temperature event: ambient {metrics.get('temperature')}°C. Risk {score}/100 ({level})."
        why = "Heat stress risk rises for crowded buildings with degraded cooling."
        likely = "Clinic demand and energy draw will peak together."
        action = "Pre-cool high-occupancy buildings, stage water at the canteen, and move clinic to standby capacity."
    elif level in ("HIGH", "CRITICAL"):
        what = f"Campus risk is elevated to {score}/100 ({level})."
        why = "; ".join(factors[:3]) or "Multiple indicators outside normal bounds."
        likely = "Conditions will worsen if the primary driver is not addressed."
        action = "Review the top contributing factors and apply the highest-priority recommendation."
    else:
        what = f"Campus operating normally. Risk {score}/100 ({level})."
        why = "All monitored indicators are within normal bounds."
        likely = "No escalation expected in the next 20 minutes."
        action = "Continue routine monitoring."

    return {
        "source": "local_fallback",
        "model": "deterministic-analyst-v1",
        "what_happened": what,
        "why_it_matters": why,
        "likely_next": likely,
        "recommended_action": action,
    }
