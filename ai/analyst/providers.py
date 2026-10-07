"""Phase 8 — analyst providers (§30/§32/§36/§39).

Two interchangeable providers behind one interface:

* ``DeterministicProvider`` — always available, produces the system narrative.
* ``LLMProvider`` — calls a configurable OpenAI-compatible endpoint and then
  SEMANTICALLY validates the response (entity grounding, number grounding,
  required structure). Any failure returns the deterministic narrative with
  ``status="local_fallback"`` — the operator never sees a broken analysis.

The LLM never sets severity, priority or recommendations; those stay
system-owned (§35).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from . import fallback
from .evidence import grounding, ungrounded_numbers
from .prompts import SYSTEM_PROMPT, build_user_prompt, parse_llm_json
from .schemas import PredictedEffect, WhyFactor

log = logging.getLogger("twinsphere.analyst.providers")

# Sentence scaffolding / operator-language words that are not entity claims.
_GENERIC = {
    "the", "a", "an", "this", "that", "these", "those", "current", "currently",
    "no", "not", "all", "both", "most", "many", "some", "and", "but", "if",
    "when", "while", "after", "before", "during", "per", "also", "however",
    "overall", "additionally", "note", "notes", "important", "key", "next",
    "prior", "latest", "recent", "recently", "ongoing", "continue",
    "monitored", "monitor", "monitoring", "should", "may", "would", "could",
    "will", "can", "must", "including", "include", "based", "given", "as",
    "in", "on", "at", "by", "for", "with", "without", "to", "from", "via",
    "campus", "twinsphere", "risk", "risks", "security", "emergency",
    "evacuation", "recovery", "situation", "status", "operations", "response",
    "route", "routes", "exit", "exits", "conditions", "summary", "predicted",
    "observed", "people", "person", "estimated", "conditions", "simulation",
    "incident", "incidents", "anomaly", "anomalies", "prediction",
    "predictions", "building", "buildings", "zone", "zones", "indicators",
    "normal", "bounds", "within", "active", "elevated", "stable", "review",
    "assessment", "brief", "operations", "action", "actions", "recommendation",
    "recommendations", "confidence", "engine", "system", "likely", "possible",
    "conditions", "capacity", "pressure", "level", "levels", "trend", "trends",
}

_RUN = re.compile(r"\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|\d+))*\b")


@dataclass
class LLMConfig:
    """Runtime knobs for the LLM path — supplied by app settings (§31)."""

    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 12.0
    max_tokens: int = 900

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


@dataclass
class Narrative:
    """Provider outcome: a validated narrative dict plus provenance."""

    narrative: dict[str, Any]
    status: str = "local_fallback"        # llm | local_fallback (§7 enum)
    provider: str = "deterministic"       # deterministic | llm
    model: str = "deterministic-analyst-v1"
    error: str | None = None
    latency_ms: int = 0


class AnalystProvider:
    """Interface — providers only produce the narrative layer."""

    name = "deterministic"

    async def analyze(self, ctx: dict, baseline: dict,
                      question: str = "") -> Narrative:  # pragma: no cover
        raise NotImplementedError


class DeterministicProvider(AnalystProvider):
    name = "deterministic"

    async def analyze(self, ctx: dict, baseline: dict,
                      question: str = "") -> Narrative:
        return Narrative(narrative=dict(baseline), status="local_fallback",
                         provider="deterministic",
                         model="deterministic-analyst-v1")


def ungrounded_entities(text: str, names: set[str]) -> list[str]:
    """§40 — capitalized multi-word runs that are not known entity names."""
    allowed = {n.strip().lower() for n in names if n and n.strip()}
    bad: list[str] = []
    for match in _RUN.finditer(str(text)):
        run = match.group(0)
        words = run.split()
        if all(w.lower() in _GENERIC for w in words):
            continue
        if words[0].lower() in _GENERIC:
            continue
        low = run.lower()
        if any(a and (a in low or low in a) for a in allowed):
            continue
        bad.append(run)
    return bad


def semantic_validate(obj: Any, ctx: dict) -> tuple[dict | None, str | None]:
    """§39 — accept only structurally complete, fully grounded narratives."""
    if not isinstance(obj, dict):
        return None, "llm output is not a JSON object"
    title = str(obj.get("title") or "").strip()
    summary = str(obj.get("summary") or "").strip()
    what = [str(x).strip() for x in (obj.get("what_is_happening") or [])
            if str(x).strip()]
    areas = [str(x).strip() for x in (obj.get("affected_areas") or [])
             if str(x).strip()]
    if not title or len(title) > 160:
        return None, "title missing or too long"
    if not summary or len(summary) > 1200:
        return None, "summary missing or too long"
    if not what:
        return None, "what_is_happening missing or empty"
    if not areas:
        return None, "affected_areas missing or empty"

    why: list[dict] = []
    for w in (obj.get("why") or [])[:6]:
        if not isinstance(w, dict):
            return None, "why entries must be objects"
        try:
            why.append(WhyFactor(
                factor=str(w.get("factor") or "").strip()[:120] or "factor",
                impact=w.get("impact") or "MEDIUM",
                evidence=str(w.get("evidence") or "").strip()[:500]
                or str(w.get("factor") or "factor"),
                source=str(w.get("source") or "")[:60],
            ).model_dump())
        except Exception as exc:  # pydantic ValidationError
            return None, f"invalid why entry ({exc})"

    effects: list[dict] = []
    for p in (obj.get("predicted_effects") or [])[:6]:
        if not isinstance(p, dict):
            return None, "predicted_effects entries must be objects"
        try:
            effect = PredictedEffect(
                effect=str(p.get("effect") or "").strip()[:300] or "no change",
                likelihood=p.get("likelihood") or "MEDIUM",
                time_horizon=str(p.get("time_horizon") or "")[:60],
                kind="PREDICTED",
                source=str(p.get("source") or "llm")[:60],
                metric=str(p.get("metric") or "")[:40],
            ).model_dump()
        except Exception as exc:
            return None, f"invalid predicted effect ({exc})"
        effects.append(effect)

    # --- grounding (§40) ------------------------------------------------------
    g = grounding(ctx)
    probe = " ".join([title, summary, *what, *areas,
                      *(w["evidence"] for w in why),
                      *(e["effect"] for e in effects)])
    unknown = ungrounded_entities(probe, g["names"])
    if unknown:
        return None, f"ungrounded entities: {unknown[:5]}"
    bad_numbers = ungrounded_numbers(
        " ".join([summary, *what, *[e["effect"] for e in effects]]),
        g["numbers"])
    if bad_numbers:
        return None, f"ungrounded numbers: {bad_numbers[:5]}"

    return {
        "title": title,
        "summary": summary,
        "what_is_happening": what[:8],
        "why": why,
        "affected_areas": areas[:6],
        "predicted_effects": effects,
    }, None


class LLMProvider(AnalystProvider):
    name = "llm"

    def __init__(self, config: LLMConfig):
        self.config = config

    async def analyze(self, ctx: dict, baseline: dict,
                      question: str = "") -> Narrative:
        import httpx

        if not self.config.enabled:
            return Narrative(narrative=dict(baseline), status="local_fallback",
                             provider="deterministic",
                             model="deterministic-analyst-v1")
        started = time.perf_counter()
        prompt = build_user_prompt(ctx, baseline, question)
        payload = {
            "model": self.config.model,
            "temperature": 0.2,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            note = (f"LLM unavailable ({type(exc).__name__}) — deterministic "
                    f"fallback active.")
            log.warning("LLM analyst failed: %s", exc)
            return Narrative(narrative=dict(baseline), status="local_fallback",
                             provider="deterministic",
                             model="deterministic-analyst-v1", error=note,
                             latency_ms=elapsed)

        elapsed = int((time.perf_counter() - started) * 1000)
        narrative, error = semantic_validate(parse_llm_json(content), ctx)
        if error:
            log.warning("LLM analyst rejected (%s); using fallback", error)
            return Narrative(narrative=dict(baseline), status="local_fallback",
                             provider="deterministic",
                             model="deterministic-analyst-v1",
                             error=f"LLM output rejected ({error}) — "
                                   f"deterministic fallback active.",
                             latency_ms=elapsed)
        return Narrative(narrative=narrative, status="llm", provider="llm",
                        model=self.config.model, latency_ms=elapsed)
