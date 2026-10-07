"""Phase 8 — AI Analyst service (§36/§44/§45/§53/§55/§56/§57).

Application-side glue around the `ai.analyst` pipeline:

* triggers   — explicit (API), boot, and background runtime refreshes with
               cooldown (§36) + context-signature cache (§44); a critical
               situation bypasses the cooldown after 5s. LLM calls never run
               on the simulation tick — `schedule()` fires an asyncio task.
* events     — analyst.* WS events queued on `state.pending_sim_events` and
               flushed by the runtime via manager.emit (Phase 6 pattern), plus
               the legacy `broadcast("analyst", result)` stream kept for the
               existing UI store.
* persistence— ai_analyses / ai_recommendations / ai_evidence rows (§57),
               bounded to ANALYSIS_LIMIT, failures never break an analysis.
* status     — ONLINE / FALLBACK / DEGRADED / OFFLINE observability (§56).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from ai.analyst import LLMConfig, build_context, run_analysis
from ai.analyst.fallback import severity_of
from app.core.config import settings
from app.models.entities import AiAnalysis, AiEvidence, AiRecommendation
from app.models.entities import utcnow

log = logging.getLogger("twinsphere.analyst.service")

ANALYSIS_LIMIT = 100        # persisted analyses kept (§57)
CACHE_LIMIT = 20            # in-memory signature cache entries (§44)
EVENT_QUEUE_LIMIT = 60      # matches simulation/route event queues


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def llm_config() -> LLMConfig:
    return LLMConfig(
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
        timeout=settings.LLM_TIMEOUT,
        max_tokens=settings.LLM_MAX_TOKENS,
    )


# --------------------------------------------------------------------- context
def build_state_context(state: Any, *, mode: str | None = None,
                        building_id: str | None = None,
                        question: str = "") -> dict:
    """Normalized context for a run — raises ValueError for an unknown mode."""
    return build_context(state, mode=mode, building_id=building_id,
                         question=question)


def _is_critical(ctx: dict) -> bool:
    evac = ctx.get("evacuation") or {}
    if str(evac.get("status", "IDLE")) in ("ACTIVE", "CRITICAL"):
        return True
    try:
        return severity_of(ctx) == "CRITICAL"
    except Exception:  # pragma: no cover - defensive
        return False


def _cooldown_window(ctx: dict) -> float:
    window = float(settings.ANALYST_COOLDOWN_SECONDS)
    if _is_critical(ctx):
        window = min(window, 5.0)
    return window


# ---------------------------------------------------------------------- events
def queue_analyst_event(state: Any, event: str, data: dict) -> None:
    """§55 — queue a typed analyst.* WS event for the runtime to flush."""
    state.pending_sim_events.append({"event": event, "data": data})
    if len(state.pending_sim_events) > EVENT_QUEUE_LIMIT:
        del state.pending_sim_events[: len(state.pending_sim_events) - EVENT_QUEUE_LIMIT]


# ---------------------------------------------------------------- persistence
def _persist(state: Any, payload: dict, signature: str) -> None:
    from app.core.database import SessionLocal

    analysis_id = payload.get("analysis_id", "")
    try:
        with SessionLocal() as db:
            slim = {k: v for k, v in payload.items() if k != "context_summary"}
            slim["context_summary"] = {
                "signature": signature,
                "mode": payload.get("mode", "CAMPUS"),
                "risk_score": (payload.get("context_summary") or {}).get(
                    "risk", {}).get("score"),
                "risk_level": (payload.get("context_summary") or {}).get(
                    "risk", {}).get("level"),
            }
            if db.get(AiAnalysis, analysis_id) is None:
                db.add(AiAnalysis(
                    id=analysis_id,
                    mode=payload.get("mode", "CAMPUS"),
                    severity=(payload.get("situation") or {}).get("severity", "LOW"),
                    priority=(payload.get("situation") or {}).get("priority", "LOW"),
                    status=payload.get("status", "completed"),
                    source=payload.get("source", "local_fallback"),
                    provider=payload.get("provider", "deterministic"),
                    model=payload.get("model", ""),
                    title=(payload.get("situation") or {}).get("title", ""),
                    summary=(payload.get("situation") or {}).get("summary", ""),
                    confidence=(payload.get("confidence") or {}).get("overall", 0.0),
                    confidence_level=(payload.get("confidence") or {}).get("level", "LOW"),
                    question=payload.get("question", ""),
                    context_signature=signature,
                    simulation_id=payload.get("simulation_id", ""),
                    latency_ms=int(payload.get("latency_ms", 0) or 0),
                    cached=bool(payload.get("cached", False)),
                    payload=slim,
                ))
                for i, card in enumerate(payload.get("recommendations") or []):
                    db.add(AiRecommendation(
                        id=card.get("id") or f"{analysis_id}_r{i + 1}",
                        analysis_id=analysis_id,
                        priority=int(card.get("priority", i + 1)),
                        category=card.get("category", "GENERAL"),
                        action=card.get("action", ""),
                        reason=card.get("reason", ""),
                        evidence=card.get("evidence") or [],
                        evidence_ids=card.get("evidence_ids") or [],
                        confidence=float(card.get("confidence", 0.5) or 0.5),
                        requires_human_approval=True,
                        status="PENDING",
                    ))
                for ev in payload.get("evidence") or []:
                    value = ev.get("value")
                    db.add(AiEvidence(
                        id=ev.get("id") or f"{analysis_id}:ev",
                        analysis_id=analysis_id,
                        label=ev.get("label", "")[:200],
                        source_type=ev.get("source_type", "campus")[:24],
                        source_id=ev.get("source_id", "")[:60],
                        metric=ev.get("metric", "")[:40],
                        value="" if value is None else str(value),
                        unit=ev.get("unit", "")[:16],
                        severity=ev.get("severity", "INFO")[:16],
                        timestamp=ev.get("timestamp") or "",
                        age_seconds=ev.get("age_seconds"),
                        confidence=ev.get("confidence"),
                        detail=ev.get("detail", ""),
                    ))

            # bounded history (§57): keep the newest ANALYSIS_LIMIT analyses.
            # SessionLocal has autoflush=False → flush the pending insert first
            # so the new analysis is inside the retention window.
            db.flush()
            ids = [r[0] for r in db.query(AiAnalysis.id)
                   .order_by(AiAnalysis.created_at.desc())
                   .limit(ANALYSIS_LIMIT).all()]
            if len(ids) >= ANALYSIS_LIMIT:
                stale = db.query(AiAnalysis).filter(
                    ~AiAnalysis.id.in_(ids)).all()
                stale_ids = [s.id for s in stale]
                if stale_ids:
                    db.query(AiRecommendation).filter(
                        AiRecommendation.analysis_id.in_(stale_ids)).delete(
                            synchronize_session=False)
                    db.query(AiEvidence).filter(
                        AiEvidence.analysis_id.in_(stale_ids)).delete(
                            synchronize_session=False)
                    for s in stale:
                        db.delete(s)
            db.commit()
    except Exception:
        log.exception("analyst persistence failed (analysis still returned)")


# ----------------------------------------------------------------------- runs
async def analyze_now(state: Any, *, question: str = "", mode: str | None = None,
                      building_id: str | None = None, force: bool = False,
                      trigger: str = "manual", broadcast: bool = True) -> dict:
    """One full analyst run: context → cache/cooldown → pipeline → events →
    persistence. Returns the full result dict (Phase 5 keys preserved)."""
    ctx = build_state_context(state, mode=mode, building_id=building_id,
                              question=question)
    signature = str(ctx.get("signature", ""))
    health = state.analyst_health
    previous = state.analyst or {}

    # §44 signature cache — unchanged situation reuses the last analysis
    if not force and not question and signature in state.analyst_cache:
        cached = {**state.analyst_cache[signature], "cached": True}
        state.analyst = cached
        health["cache_hits"] = int(health.get("cache_hits", 0)) + 1
        return cached

    # §36 cooldown — explicit API calls (force) always bypass
    if not force and state.analyst_last_run:
        elapsed = time.monotonic() - state.analyst_last_run
        if elapsed < _cooldown_window(ctx):
            return previous or {}

    queue_analyst_event(state, "analyst.analysis_started", {
        "mode": ctx.get("mode", "CAMPUS"), "trigger": trigger,
        "signature": signature, "question": bool(question), "at": _iso(),
    })

    try:
        result = await run_analysis(
            ctx, question=question, llm=llm_config(),
            previous=state._analyst_prev_ctx or None)
    except Exception as exc:
        health["fail_streak"] = int(health.get("fail_streak", 0)) + 1
        health["last_error"] = f"{type(exc).__name__}: {exc}"
        if int(health["fail_streak"]) >= 3:
            health["status"] = "OFFLINE"
        log.exception("analyst run failed")
        raise

    payload = result.model_dump()
    configured = bool(settings.LLM_API_KEY)

    # --- state bookkeeping ----------------------------------------------------
    state.analyst = payload
    state.analyst_last_run = time.monotonic()
    state.analyst_last_signature = signature
    state._analyst_prev_ctx = ctx
    state.analyst_cache[signature] = payload
    while len(state.analyst_cache) > CACHE_LIMIT:
        state.analyst_cache.pop(next(iter(state.analyst_cache)))

    health["runs"] = int(health.get("runs", 0)) + 1
    health["fail_streak"] = 0
    health["last_run"] = _iso()
    health["last_latency_ms"] = int(result.latency_ms)
    health["last_source"] = result.source
    health["llm_configured"] = configured
    if configured and result.source != "llm":
        health["fallbacks"] = int(health.get("fallbacks", 0)) + 1
        health["llm_errors"] = int(health.get("llm_errors", 0)) + 1
        health["llm_fail_streak"] = int(health.get("llm_fail_streak", 0)) + 1
        health["last_error"] = result.note or "LLM returned no usable narrative"
    elif result.source == "llm":
        health["llm_fail_streak"] = 0
    elif not configured:
        health["fallbacks"] = int(health.get("fallbacks", 0)) + 1

    health["status"] = compute_status(state)

    # --- events (§55) ---------------------------------------------------------
    base = {"analysis_id": result.analysis_id, "mode": result.mode,
            "trigger": trigger, "at": _iso()}
    queue_analyst_event(state, "analyst.analysis_completed", {
        **base,
        "result": {k: v for k, v in payload.items() if k != "context_summary"},
        "severity": result.situation.severity,
        "priority": result.situation.priority,
        "source": result.source,
        "confidence": result.confidence.overall,
        "recommendation_count": len(result.recommendations),
        "cached": False,
    })
    if result.what_changed:
        queue_analyst_event(state, "analyst.analysis_updated", {
            **base,
            "what_changed": [c.model_dump() for c in result.what_changed],
            "severity": result.situation.severity,
            "priority": result.situation.priority,
        })
    prev_ids = {r.get("id") for r in (previous.get("recommendations") or [])}
    for card in result.recommendations:
        if card.id and card.id not in prev_ids:
            queue_analyst_event(state, "analyst.recommendation_created", {
                **base, "recommendation": card.model_dump()})
    prev_severity = (previous.get("situation") or {}).get("severity", "")
    if result.situation.severity == "CRITICAL" and prev_severity != "CRITICAL":
        alert = {
            "id": f"alert_anl_{result.analysis_id}",
            "level": "CRITICAL", "severity": "CRITICAL", "type": "ANALYST",
            "title": result.situation.title,
            "message": result.situation.summary[:300],
            "entity_id": "", "created_at": _iso(),
            "acknowledged": False, "resolved_at": None,
        }
        state.alerts.append(alert)
        if len(state.alerts) > 50:
            del state.alerts[: len(state.alerts) - 50]
        queue_analyst_event(state, "analyst.alert_created", {**base, "alert": alert})

    # --- AI timeline entry ----------------------------------------------------
    try:
        from app.services.ai_service import append_ai_event
        level = ("critical" if result.situation.severity == "CRITICAL"
                 else "warn" if result.situation.severity in ("HIGH", "ELEVATED")
                 else "info")
        append_ai_event(
            state, "SYSTEM", f"Analyst brief · {result.situation.title}",
            f"{result.situation.severity}/{result.situation.priority} · "
            f"{result.source} · confidence {result.confidence.overall:.0%} · "
            f"{len(result.recommendations)} recommendation(s).",
            level=level)
    except Exception:  # pragma: no cover - timeline is best effort
        log.debug("analyst timeline append failed", exc_info=True)

    # --- persistence (§57) ----------------------------------------------------
    if not result.cached:
        _persist(state, payload, signature)

    # --- legacy broadcast stream (Phase 5 consumers) --------------------------
    if broadcast:
        try:
            from app.websocket.manager import manager
            await manager.broadcast("analyst",
                                    {**payload, "context_summary": {}})
        except Exception:  # pragma: no cover - no clients / closed loop
            log.debug("analyst broadcast skipped", exc_info=True)

    return payload


def schedule(state: Any, trigger: str = "runtime") -> bool:
    """Fire-and-forget refresh for the runtime loop — never blocks a tick (§37).
    Returns False when a run is already in flight."""
    if state._analyst_inflight:
        return False
    state._analyst_inflight = True

    async def _background() -> None:
        try:
            await analyze_now(state, trigger=trigger)
        except Exception:
            log.exception("background analyst refresh failed")
        finally:
            state._analyst_inflight = False

    state._analyst_task = asyncio.get_running_loop().create_task(_background())
    return True


# ---------------------------------------------------------------------- status
def compute_status(state: Any) -> str:
    health = state.analyst_health
    if int(health.get("fail_streak", 0)) >= 3:
        return "OFFLINE"
    if not bool(settings.LLM_API_KEY):
        return "FALLBACK"
    if int(health.get("llm_fail_streak", 0)) >= 2:
        return "DEGRADED"
    return "ONLINE"


def status(state: Any) -> dict:
    health = state.analyst_health
    current = compute_status(state)
    health["status"] = current
    window = float(settings.ANALYST_COOLDOWN_SECONDS)
    remaining = 0.0
    if state.analyst_last_run:
        remaining = max(0.0, window - (time.monotonic() - state.analyst_last_run))
    return {
        "status": current,
        "llm_configured": bool(settings.LLM_API_KEY),
        "model": settings.LLM_MODEL if settings.LLM_API_KEY else "deterministic-analyst-v1",
        "cooldown_seconds": window,
        "cooldown_remaining_s": round(remaining, 1),
        "in_flight": bool(state._analyst_inflight),
        "cache_size": len(state.analyst_cache),
        "cache_hits": int(health.get("cache_hits", 0)),
        "runs": int(health.get("runs", 0)),
        "fallbacks": int(health.get("fallbacks", 0)),
        "llm_errors": int(health.get("llm_errors", 0)),
        "llm_fail_streak": int(health.get("llm_fail_streak", 0)),
        "fail_streak": int(health.get("fail_streak", 0)),
        "last_run": health.get("last_run"),
        "last_latency_ms": int(health.get("last_latency_ms", 0)),
        "last_source": health.get("last_source"),
        "last_error": health.get("last_error"),
        "current_analysis": (state.analyst or {}).get("analysis_id", ""),
        "severity": ((state.analyst or {}).get("situation") or {}).get("severity", ""),
        "persisted_limit": ANALYSIS_LIMIT,
    }


# ----------------------------------------------------------------- read/write
def _row_payload(row: AiAnalysis) -> dict:
    payload = dict(row.payload or {})
    payload.setdefault("analysis_id", row.id)
    # top-level copies of the indexed columns so list filters stay legible
    payload["severity"] = payload.get("severity") or row.severity
    payload["status"] = payload.get("status") or row.status
    payload["persisted_at"] = row.created_at.isoformat() if row.created_at else None
    return payload


def list_analyses(db: Any, limit: int = 20, mode: str | None = None,
                  severity: str | None = None) -> list[dict]:
    query = db.query(AiAnalysis).order_by(AiAnalysis.created_at.desc())
    if mode:
        query = query.filter(AiAnalysis.mode == mode.upper())
    if severity:
        query = query.filter(AiAnalysis.severity == severity.upper())
    return [_row_payload(r) for r in query.limit(limit).all()]


def get_analysis(db: Any, analysis_id: str) -> dict | None:
    row = db.get(AiAnalysis, analysis_id)
    return _row_payload(row) if row else None


def list_recommendations(db: Any, status: str | None = None,
                         analysis_id: str | None = None) -> list[dict]:
    query = db.query(AiRecommendation).order_by(
        AiRecommendation.priority.asc(), AiRecommendation.created_at.desc())
    if analysis_id:
        query = query.filter(AiRecommendation.analysis_id == analysis_id)
    else:
        latest = (db.query(AiAnalysis.id).order_by(AiAnalysis.created_at.desc())
                  .first())
        if latest is None:
            return []
        query = query.filter(AiRecommendation.analysis_id == latest[0])
    if status:
        query = query.filter(AiRecommendation.status == status.upper())
    return [{
        "recommendation_id": r.id, "analysis_id": r.analysis_id,
        "priority": r.priority, "category": r.category, "action": r.action,
        "reason": r.reason, "evidence": r.evidence or [],
        "evidence_ids": r.evidence_ids or [], "confidence": r.confidence,
        "requires_human_approval": r.requires_human_approval,
        "status": r.status, "decided_by": r.decided_by,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in query.all()]


def decide_recommendation(db: Any, recommendation_id: str, decision: str,
                          actor: str) -> dict:
    """§24 human-in-the-loop — accept/dismiss an analyst recommendation."""
    row = db.get(AiRecommendation, recommendation_id)
    if row is None:
        raise LookupError(f"Analyst recommendation not found: '{recommendation_id}'")
    decision = decision.upper()
    if decision not in ("ACCEPTED", "DISMISSED"):
        raise ValueError(f"decision must be ACCEPTED or DISMISSED, got {decision!r}")
    if row.status in ("ACCEPTED", "DISMISSED", "APPLIED"):
        raise ValueError(f"recommendation already decided: {row.status}")
    row.status = decision
    row.decided_at = utcnow()
    row.decided_by = actor
    db.commit()
    return {
        "recommendation_id": row.id, "analysis_id": row.analysis_id,
        "status": row.status, "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "action": row.action,
    }


def get_evidence(db: Any, evidence_id: str) -> dict | None:
    row = db.get(AiEvidence, evidence_id)
    if row is None:
        return None
    value: Any = row.value
    try:
        value = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        pass
    return {
        "id": row.id, "analysis_id": row.analysis_id, "label": row.label,
        "source_type": row.source_type, "source_id": row.source_id,
        "metric": row.metric, "value": value, "unit": row.unit,
        "severity": row.severity, "timestamp": row.timestamp,
        "age_seconds": row.age_seconds, "confidence": row.confidence,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
