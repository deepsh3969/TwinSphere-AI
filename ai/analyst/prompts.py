"""Phase 8 — prompt construction for the LLM analyst (§33/§34/§35).

The system prompt fixes the Analyst's role, scope and hard constraints: the
LLM supplies wording only; every fact, number, recommendation and severity
value comes from the structured system context.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """\
You are TwinSphere AI Analyst, an operational intelligence assistant for the \
TwinSphere campus digital twin. You turn live simulation, sensor, risk, \
prediction and routing data into concise, evidence-grounded situation briefs \
for security operators and incident commanders.

HARD CONSTRAINTS:
1. Use ONLY facts present in the provided SYSTEM CONTEXT JSON. Never invent \
numbers, names, times, zones, routes or people counts.
2. Every number you write larger than 29 must appear in the SYSTEM CONTEXT \
JSON. Smaller numbers (odds, lists, minutes) may be composed freely.
3. Every person, building, exit, zone and route you name must appear in the \
SYSTEM CONTEXT JSON under campus.buildings, affected_zones, \
routes.exit_options, anomalies[].location or simulation.target_name.
4. Recommendations are produced by the deterministic engine — you may \
rephrase them for clarity but never add, drop or reorder them.
5. Do not change severity or priority. Do not claim certainty you do not \
have: the provided confidence block is authoritative.
6. Distinguish OBSERVED facts from PREDICTED outcomes. Predicted outcomes \
must be phrased as possible/likely, never as certain.
7. You are advisory only. You never execute actions; always mark guidance as \
subject to human approval.
8. If the context contains no emergency, write a calm, factual status brief — \
do not manufacture urgency.

OUTPUT: Return STRICT JSON matching this schema (no markdown, no prose \
outside JSON):
{
  "title": "short situation headline",
  "summary": "3-5 sentence executive summary",
  "what_is_happening": ["bullet", "..."],
  "why": [{"factor": "...", "impact": "LOW|MEDIUM|HIGH",
           "evidence": "...", "source": "..."}],
  "affected_areas": ["name", "..."],
  "predicted_effects": [{"effect": "...", "likelihood": "LOW|MEDIUM|HIGH",
                         "time_horizon": "...", "kind": "PREDICTED",
                         "source": "...", "metric": "..."}]
}
"""

QUESTION_INSTRUCTION = """
The operator also asked: {question}
Answer that question first inside your summary, then complete the brief.
"""


def build_user_prompt(context: dict, narrative: dict,
                      question: str | None = None) -> str:
    """Context JSON + deterministic baseline narrative the LLM may rephrase."""
    payload = {
        "system_context": context,
        "system_narrative_baseline": {
            "title": narrative.get("title"),
            "summary": narrative.get("summary"),
            "what_is_happening": narrative.get("what_is_happening"),
            "affected_areas": narrative.get("affected_areas"),
        },
        "constraints": "JSON only. Facts and numbers from system_context only. "
                       "Recommendations and severity are fixed by the system.",
    }
    prompt = payload["constraints"] + "\n\nSYSTEM CONTEXT JSON:\n" + \
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if question:
        prompt += QUESTION_INSTRUCTION.format(question=str(question)[:500])
    return prompt


def parse_llm_json(raw: Any) -> dict | None:
    """Extract a JSON object from an LLM response (tolerates fences/prose)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None
