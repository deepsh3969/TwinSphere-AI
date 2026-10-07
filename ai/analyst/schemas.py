"""Phase 8 — AI Analyst structured output schemas (§7).

Strict Pydantic contract for every AnalystResult, validated on BOTH the
deterministic and the LLM path (§39). The Analyst never owns numbers: it
references evidence extracted from the deterministic engines.

Enums are uppercase and membership-checked — an invalid severity/priority/
confidence from the LLM raises ValidationError, which routes the run to the
deterministic fallback instead of reaching the operator.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SEVERITIES = ("LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "IMMEDIATE")
IMPACTS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
LIKELIHOODS = ("LOW", "MEDIUM", "HIGH")
CONFIDENCE_LEVELS = ("LOW", "MEDIUM", "HIGH")
ANALYSIS_MODES = ("INCIDENT", "CAMPUS", "BUILDING", "ROUTE", "SIMULATION", "RECOVERY")
SOURCE_KINDS = ("llm", "local_fallback")

# Situation severity → operator priority (§22; project risk bands).
SEVERITY_PRIORITY = {
    "LOW": "LOW", "MODERATE": "MEDIUM", "ELEVATED": "MEDIUM",
    "HIGH": "HIGH", "CRITICAL": "IMMEDIATE",
}
_RANK = {"LOW": 0, "MODERATE": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4}


def _upper(v: Any) -> str:
    return str(v or "").strip().upper()


def _enum(value: Any, allowed: tuple[str, ...], field_name: str) -> str:
    v = _upper(value)
    if v not in allowed:
        raise ValueError(f"{field_name} must be one of {list(allowed)}, got {value!r}")
    return v


def _probability(value: Any, field_name: str) -> float:
    f = float(value)
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"{field_name} must be within 0..1, got {value!r}")
    return round(f, 4)


class EvidenceItem(BaseModel):
    """§9 — one grounding fact with source, timestamp and severity."""

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="campus", max_length=24)   # sensor|risk|anomaly|prediction|route|evacuation|simulation|bottleneck|incident|campus
    source_id: str = Field(default="", max_length=60)
    metric: str = Field(default="", max_length=40)
    value: float | str | None = None
    unit: str = Field(default="", max_length=16)
    severity: str = Field(default="INFO", max_length=16)
    timestamp: str | None = None
    age_seconds: float | None = Field(default=None, ge=0.0)
    confidence: float | None = None
    detail: str = Field(default="", max_length=400)


class WhyFactor(BaseModel):
    """§8/§18 — contributing factor (never unsupported 'root cause')."""

    model_config = ConfigDict(extra="ignore")

    factor: str = Field(min_length=1, max_length=120)
    impact: str = Field(default="MEDIUM", max_length=16)
    evidence: str = Field(min_length=1, max_length=500)
    source: str = Field(default="", max_length=60)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("impact")
    @classmethod
    def _impact(cls, v: Any) -> str:
        return _enum(v, IMPACTS, "impact")


class PredictedEffect(BaseModel):
    """§14/§20 — projection only; always tagged PREDICTED."""

    model_config = ConfigDict(extra="ignore")

    effect: str = Field(min_length=1, max_length=300)
    likelihood: str = Field(default="MEDIUM", max_length=16)
    time_horizon: str = Field(default="", max_length=60)
    kind: str = Field(default="PREDICTED", max_length=16)
    source: str = Field(default="", max_length=60)   # prediction engine reference
    metric: str = Field(default="", max_length=40)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("likelihood")
    @classmethod
    def _likelihood(cls, v: Any) -> str:
        return _enum(v, LIKELIHOODS, "likelihood")


class RecommendationCard(BaseModel):
    """§21 — advisory only; every operational card demands human approval."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default="", max_length=60)
    priority: int = Field(ge=1, le=9)
    action: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=500)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5)
    requires_human_approval: bool = True
    category: str = Field(default="GENERAL", max_length=24)
    evidence_ids: list[str] = Field(default_factory=list)
    focus: dict[str, Any] = Field(default_factory=dict)   # e.g. {"route_id": ...}

    @field_validator("confidence")
    @classmethod
    def _conf(cls, v: Any) -> float:
        return _probability(v, "recommendation.confidence")

    @field_validator("requires_human_approval")
    @classmethod
    def _human(cls, v: Any) -> bool:
        # §24 — the Analyst can never opt out of human-in-the-loop.
        return bool(v) or True


class RouteAssessment(BaseModel):
    """§7 — routing verdict copied from the route engine (never recomputed)."""

    model_config = ConfigDict(extra="ignore")

    recommended_route: str = Field(default="", max_length=200)
    route_id: str = Field(default="", max_length=60)
    origin: str = Field(default="", max_length=60)
    destination: str = Field(default="", max_length=60)
    mode: str = Field(default="", max_length=20)
    reason: str = Field(default="", max_length=400)
    risk: float = Field(default=0.0, ge=0.0, le=100.0)
    estimated_time: float = Field(default=0.0, ge=0.0)
    status: str = Field(default="", max_length=30)
    alternatives: list[str] = Field(default_factory=list)


class ConfidenceBlock(BaseModel):
    """§15 — weighted evidence confidence, never marketing accuracy."""

    model_config = ConfigDict(extra="ignore")

    overall: float
    level: str = Field(default="MEDIUM", max_length=16)
    components: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("overall")
    @classmethod
    def _overall(cls, v: Any) -> float:
        return _probability(v, "confidence.overall")

    @field_validator("level")
    @classmethod
    def _level(cls, v: Any) -> str:
        return _enum(v, CONFIDENCE_LEVELS, "confidence.level")


class Situation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1200)
    severity: str = Field(default="LOW", max_length=16)
    priority: str = Field(default="LOW", max_length=16)
    mode: str = Field(default="CAMPUS", max_length=16)

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: Any) -> str:
        return _enum(v, SEVERITIES, "situation.severity")

    @field_validator("priority")
    @classmethod
    def _pri(cls, v: Any) -> str:
        return _enum(v, PRIORITIES, "situation.priority")

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: Any) -> str:
        return _enum(v, ANALYSIS_MODES, "situation.mode")


class ChangeItem(BaseModel):
    """§28 — only populated when historical comparison confirms the change."""

    model_config = ConfigDict(extra="ignore")

    kind: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=300)
    previous: str = Field(default="", max_length=80)
    current: str = Field(default="", max_length=80)


class AnalystResult(BaseModel):
    """§7 — the full structured analyst response."""

    model_config = ConfigDict(extra="ignore")

    analysis_id: str = Field(min_length=1, max_length=60)
    timestamp: str = Field(min_length=1, max_length=40)
    mode: str = Field(default="CAMPUS", max_length=16)
    situation: Situation
    what_is_happening: list[str] = Field(default_factory=list)
    why: list[WhyFactor] = Field(default_factory=list)
    affected_areas: list[str] = Field(default_factory=list)
    predicted_effects: list[PredictedEffect] = Field(default_factory=list)
    recommendations: list[RecommendationCard] = Field(default_factory=list)
    route_assessment: RouteAssessment = Field(default_factory=RouteAssessment)
    confidence: ConfidenceBlock
    human_decision_required: bool = True
    evidence: list[EvidenceItem] = Field(default_factory=list)
    what_changed: list[ChangeItem] = Field(default_factory=list)

    # provenance / observability (§45/§56)
    provider: str = Field(default="deterministic", max_length=24)
    model: str = Field(default="deterministic-analyst-v1", max_length=60)
    source: str = Field(default="local_fallback", max_length=24)
    status: str = Field(default="completed", max_length=24)
    latency_ms: int = Field(default=0, ge=0)
    cached: bool = False
    simulation_id: str = Field(default="", max_length=60)
    question: str = Field(default="", max_length=500)
    query_answer: str = Field(default="", max_length=1200)
    note: str | None = None

    # legacy Phase 5 shape kept so existing consumers never break
    what_happened: str = ""
    why_it_matters: str = ""
    likely_next: str = ""
    recommended_action: str = ""
    context_summary: dict[str, Any] = Field(default_factory=dict)
    generated_at: float | None = None

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: Any) -> str:
        return _enum(v, ANALYSIS_MODES, "mode")

    @field_validator("source")
    @classmethod
    def _source(cls, v: Any) -> str:
        u = _upper(v)
        if u not in ("LLM", "LOCAL_FALLBACK"):
            raise ValueError(f"source must be one of {list(SOURCE_KINDS)}, got {v!r}")
        return u.lower()

    @field_validator("provider")
    @classmethod
    def _provider(cls, v: Any) -> str:
        u = _upper(v)
        if u not in ("DETERMINISTIC", "LLM"):
            raise ValueError("provider must be one of ['deterministic', 'llm']")
        return u.lower()

    def legacy_dict(self) -> dict[str, Any]:
        """Flat dict with the Phase 5 keys (what_happened…source)."""
        d = self.model_dump()
        d["severity"] = self.situation.severity
        d["priority"] = self.situation.priority
        d["title"] = self.situation.title
        d["summary"] = self.situation.summary
        d["confidence_score"] = self.confidence.overall
        return d


def max_severity(a: str, b: str) -> str:
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def priority_for(severity: str) -> str:
    return SEVERITY_PRIORITY.get(severity, "MEDIUM")
