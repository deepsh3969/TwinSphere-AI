"""Phase 8 — AI Analyst & Decision Support (spec §7-§66).

Covers the twenty required areas: structure, evidence, confidence,
recommendations, what-changed, modes, queries, fallback, grounding, cache,
cooldown, WS events, persistence, status, RBAC and the human-in-the-loop
decision flow.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai.analyst import (
    AnalystResult, LLMConfig, answer_question, build_context, build_user_prompt,
    compute_confidence, detect_mode, extract_evidence,
    generate_recommendations, parse_llm_json, run_analysis, scrub,
    semantic_validate, system_narrative, ungrounded_entities,
    ungrounded_numbers, what_changed_for,
)
from ai.analyst.fallback import severity_of
from ai.analyst.schemas import Situation, priority_for
from app.core.database import SessionLocal
from app.core.security import create_token
from app.main import app
from app.models.entities import AiAnalysis, AiEvidence, AiRecommendation
from app.services import analyst_service as asvc
from app.services import route_service as rs
from app.services import simulation_engine as simeng
from app.services.demo import full_reset
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.state import TwinState, get_state

client = TestClient(app)
ADMIN = {"Authorization": f"Bearer {create_token('u_admin', 'admin', 'ADMIN')}"}
ANALYST = {"Authorization": f"Bearer {create_token('u_an', 'analyst', 'ANALYST')}"}
OPERATOR = {"Authorization": f"Bearer {create_token('u_op', 'operator', 'OPERATOR')}"}
VIEWER = {"Authorization": f"Bearer {create_token('u_view', 'viewer', 'VIEWER')}"}


@pytest.fixture()
def state():
    st = TwinState(seed=7)
    compute_risk(st)
    return st


def _run(coro):
    return asyncio.run(coro)


def _fire(st, ticks=6, step=5.0):
    """Fire scenario with live simulation + auto evacuation plan (§49)."""
    rs.ensure_initial(st)
    compute_routes(st)
    simeng.create_simulation(st, "fire", "eng", {"intensity": 5, "wind": "NONE"})
    simeng.start_simulation(st, st.active_sim.id)
    for _ in range(ticks):
        simeng.tick_simulation(st, step)
        compute_risk(st)
    rs.revalidate(st)
    return st


def _publish_risk(st, score: float, level: str, trend: str = "INCREASING"):
    factors = [{"label": "Smoke concentration", "contribution": round(score * 0.4, 1),
                "category": "weighted"},
               {"label": "Occupancy density", "contribution": round(score * 0.2, 1),
                "category": "weighted"}]
    st.risk = {"score": score, "level": level, "trend": trend,
               "delta": 5.0, "factors": factors, "explanation": "test"}
    st.risk_published = {"campus": {"score": score, "level": level, "trend": trend,
                                    "delta": 5.0, "raw_score": score,
                                    "factors": factors, "explanation": "test"}}


# ------------------------------------------------------------ §5/§6 context

def test_context_shape_signature_and_scrub(state):
    ctx = build_context(state)
    for key in ("timestamp", "mode", "campus", "simulation", "risk", "anomalies",
                "predictions", "routes", "evacuation", "freshness", "signature",
                "people_at_risk", "incidents", "recovery"):
        assert key in ctx, f"context missing {key}"
    assert len(ctx["signature"]) == 20
    # deterministic: same state → same signature (§44)
    assert build_context(state)["signature"] == ctx["signature"]
    # §41 — no credential-like keys anywhere in the context
    blob = str(ctx).lower()
    assert "api_key" not in blob and "jwt_secret" not in blob
    scrubbed = scrub({"a": {"password": "x", "token": "y", "ok": 1}})
    assert "password" not in scrubbed["a"] and "token" not in scrubbed["a"]
    assert scrubbed["a"]["ok"] == 1
    # §42 — aggregated occupancy only, never person-level data
    assert isinstance(ctx["people_at_risk"], int)
    assert "residents" not in ctx and "person_id" not in ctx


def test_detect_mode_variants(state):
    assert detect_mode(None, None, None, 100.0) == "CAMPUS"
    assert detect_mode(None, "eng", None, 100.0) == "BUILDING"
    assert detect_mode("route", None, None, 100.0) == "ROUTE"
    assert detect_mode(None, None, None, 42.0) == "RECOVERY"
    with pytest.raises(ValueError):
        detect_mode("nonsense", None, None, 100.0)
    assert build_context(state, building_id="eng")["mode"] == "BUILDING"
    with pytest.raises(ValueError):
        build_context(state, mode="nonsense")


# --------------------------------------------------- §50 normal operations

def test_quiet_campus_analysis(state):
    result = _run(run_analysis(build_context(state)))
    assert isinstance(result, AnalystResult)
    assert result.source == "local_fallback" and result.provider == "deterministic"
    assert result.situation.severity == "LOW"
    assert result.situation.priority == "LOW"
    assert result.mode == "CAMPUS"
    assert result.human_decision_required is True
    # calm narrative — no manufactured urgency
    text = (result.situation.title + result.situation.summary).upper()
    assert "CRITICAL" not in text and "ESCALAT" not in text
    # §7 legacy keys survive
    assert result.what_happened and result.why_it_matters
    assert result.likely_next and result.recommended_action
    legacy = result.legacy_dict()
    assert legacy["source"] == "local_fallback"
    assert legacy["severity"] == "LOW"
    # at least routine monitoring, always with human approval
    assert result.recommendations
    assert all(r.requires_human_approval for r in result.recommendations)
    assert [r.priority for r in result.recommendations] == list(
        range(1, len(result.recommendations) + 1))


# ------------------------------------------------------------- §49 fire run

def test_fire_incident_analysis(state):
    _fire(state)
    assert state.route_plan is not None and state.evacuation["status"] != "IDLE"
    ctx = build_context(state, mode="INCIDENT")
    result = _run(run_analysis(ctx, previous=None))

    assert result.mode == "INCIDENT"
    assert result.situation.severity in ("HIGH", "CRITICAL")
    assert result.situation.priority in ("HIGH", "IMMEDIATE")
    assert result.simulation_id, "simulation id must be propagated"
    # what is happening names the live situation
    joined = " ".join(result.what_is_happening).lower()
    assert "simulation" in joined or "fire" in joined
    # evidence links: every recommendation cites real evidence ids
    ev_ids = {e.id for e in result.evidence}
    assert ev_ids, "evidence must exist"
    for rec in result.recommendations:
        assert rec.evidence, "recommendations must cite evidence"
        assert set(rec.evidence_ids) & ev_ids, "evidence_ids must resolve"
    # top recommendation targets the safest available exit
    exits = ctx["routes"]["exit_options"]
    usable = [e for e in exits if e["status"] != "BLOCKED"]
    safest = min(usable, key=lambda e: e["risk"])
    assert result.recommendations[0].category == "EVACUATION"
    assert safest["exit"] in result.recommendations[0].action
    assert result.route_assessment.recommended_route
    # confidence is bounded and componentised (§15)
    assert 0.05 <= result.confidence.overall <= 0.95
    assert sum(c["weight"] for c in result.confidence.components) == pytest.approx(1.0)
    assert result.confidence.level in ("LOW", "MEDIUM", "HIGH")
    # affected areas include the burning building
    assert any("Engineering" in a for a in result.affected_areas)
    assert result.evidence and result.evidence[0].metric.startswith("risk")


def test_recovery_mode_analysis(state):
    state.recovery_progress = 62.0
    _publish_risk(state, 34.0, "MODERATE", trend="DECREASING")
    result = _run(run_analysis(build_context(state)))
    assert result.mode == "RECOVERY"
    assert "Recovery" in result.situation.title
    assert any(r.category == "RECOVERY" for r in result.recommendations)


# ------------------------------------------------------------ §28 what changed

def test_what_changed_requires_previous_context(state):
    ctx1 = build_context(state)
    assert what_changed_for(ctx1, None) == []
    prev = {**ctx1, "risk": {"score": 20.0, "level": "MODERATE"},
            "routes": {"recommended": None}, "simulation": {"simulation_id": ""},
            "evacuation": {"status": "IDLE"}, "people_at_risk": 0}
    _publish_risk(state, 76.0, "HIGH")
    _fire(state)
    ctx2 = build_context(state, mode="INCIDENT")
    changes = what_changed_for(ctx2, prev)
    kinds = [c.kind for c in changes]
    assert "risk_change" in kinds and "route_change" in kinds
    assert "simulation_change" in kinds and "evacuation_change" in kinds
    assert all(c.message for c in changes)


def test_question_answered_from_structured_data(state):
    _fire(state)
    ctx = build_context(state, mode="INCIDENT", question="Why did the route change?")
    result = _run(run_analysis(ctx))
    assert result.question == "Why did the route change?"
    assert result.query_answer, "question must produce a query_answer"
    # §54 answers come from context, not invented text
    answer = result.query_answer.lower()
    assert any(w in answer for w in ("route", "plan", "risk", "confidence"))


# ---------------------------------------------------- §15/§16 confidence

def test_stale_data_lowers_confidence_with_note(state):
    ctx = build_context(state)
    fresh = compute_confidence(ctx, extract_evidence(ctx))
    stale = dict(ctx)
    stale["freshness"] = {**ctx["freshness"], "sensor_oldest_s": 240.0}
    aged = compute_confidence(stale, extract_evidence(stale))
    assert aged["overall"] < fresh["overall"]
    assert any("240" in n and "old" in n for n in aged["notes"])
    assert fresh["overall"] <= 0.95, "never claim near-certainty"


# ------------------------------------------------- §21/§22/§23/§24 recs

def test_recommendations_grounded_sorted_and_approved(state):
    _fire(state)
    ctx = build_context(state, mode="INCIDENT")
    evidence = extract_evidence(ctx)
    conf = compute_confidence(ctx, evidence)
    recs = generate_recommendations(ctx, evidence, conf)
    assert recs
    assert [r.priority for r in recs] == list(range(1, len(recs) + 1))
    assert all(r.requires_human_approval for r in recs)
    assert all(r.action and r.reason and r.evidence for r in recs)
    assert all(0.0 <= r.confidence <= 1.0 for r in recs)
    # evidence strings carry real values (not lorem)
    flat = " ".join(e for r in recs for e in r.evidence)
    assert "/100" in flat or "risk" in flat.lower()
    assert all(r.category in ("EVACUATION", "RESPONSE", "MONITORING",
                              "PREDICTION", "RECOVERY", "GENERAL", "ROUTE")
               for r in recs)


def test_severity_priority_ladder():
    def ctx(score, level, sim=False, evac="IDLE"):
        return {"risk": {"score": score, "level": level},
                "simulation": {"active": sim},
                "evacuation": {"status": evac}}
    assert severity_of(ctx(12, "LOW")) == "LOW"
    assert severity_of(ctx(35, "MODERATE")) == "MODERATE"
    assert severity_of(ctx(55, "ELEVATED")) == "ELEVATED"
    assert severity_of(ctx(35, "MODERATE", sim=True)) == "HIGH"
    assert severity_of(ctx(82, "CRITICAL")) == "CRITICAL"
    assert severity_of(ctx(60, "HIGH", evac="CRITICAL")) == "CRITICAL"
    assert severity_of(ctx(60, "HIGH", evac="ACTIVE")) in ("HIGH", "CRITICAL")
    assert priority_for("LOW") == "LOW"
    assert priority_for("MODERATE") == "MEDIUM"
    assert priority_for("ELEVATED") == "MEDIUM"
    assert priority_for("HIGH") == "HIGH"
    assert priority_for("CRITICAL") == "IMMEDIATE"


# ------------------------------------------------ §39/§40 grounding / LLM

def test_semantic_validation_accepts_grounded_rejects_hallucinations(state):
    ctx = build_context(state)
    score = ctx["risk"]["score"]
    level = ctx["risk"]["level"]
    trend = ctx["risk"]["trend"]
    good = {
        "title": "Campus Operations Stable",
        "summary": f"Campus conditions are currently stable. Risk is {level} "
                   f"at {score}/100 with no active emergency simulations.",
        "what_is_happening": [f"Campus risk is {score}/100 ({level}), "
                              f"trend {trend}."],
        "affected_areas": ["Campus-wide (no localised impact)"],
        "why": [{"factor": "All indicators within bounds", "impact": "LOW",
                 "evidence": "No elevated risk factors in the current context.",
                 "source": "risk_engine"}],
        "predicted_effects": [{"effect": "Conditions remain stable.",
                               "likelihood": "LOW", "time_horizon": "20 minutes"}],
    }
    parsed, err = semantic_validate(good, ctx)
    assert err is None and parsed["title"] == good["title"]

    # unknown building name → rejected
    bad_name = {**good, "affected_areas": ["Weldon Hall"]}
    assert semantic_validate(bad_name, ctx)[0] is None

    # invented large number → rejected (numbers > 29 must be grounded)
    bad_number = {**good, "summary": good["summary"] + " Risk will hit 999/100."}
    parsed_b, err_b = semantic_validate(bad_number, ctx)
    assert parsed_b is None and "999" in (err_b or "")

    # structural failures → rejected
    assert semantic_validate(None, ctx)[0] is None
    assert semantic_validate({**good, "what_is_happening": []}, ctx)[0] is None
    assert semantic_validate({**good, "affected_areas": []}, ctx)[0] is None
    bad_impact = {**good, "why": [{"factor": "f", "impact": "SEVERE",
                                   "evidence": "e"}]}
    assert semantic_validate(bad_impact, ctx)[0] is None

    names = {"Engineering Building", "Emergency Gate 1"}
    assert ungrounded_entities("Engineering Building is safe", names) == []
    assert ungrounded_entities("Weldon Hall is safe", names) == ["Weldon Hall"]
    assert ungrounded_numbers("risk 999", {12.0}) == [999.0]
    assert ungrounded_numbers("risk 12", {12.0}) == []


def test_strict_schema_rejects_invalid_enums():
    with pytest.raises(ValidationError):
        Situation(title="t", summary="s", severity="SEVERE", priority="LOW")
    with pytest.raises(ValidationError):
        Situation(title="t", summary="s", severity="LOW", priority="URGENT")
    with pytest.raises(ValidationError):
        AnalystResult(analysis_id="a" * 61, timestamp="now")
    with pytest.raises(ValidationError):
        AnalystResult(analysis_id="a", timestamp="now", source="chatgpt")


def test_prompt_and_json_parsing(state):
    ctx = build_context(state)
    narrative = system_narrative(ctx)
    prompt = build_user_prompt(ctx, narrative, question="Why?")
    assert "system_context" in prompt and "Why?" in prompt
    assert "password" not in prompt and "api_key" not in prompt
    assert parse_llm_json('```json\n{"title": "x"}\n```') == {"title": "x"}
    assert parse_llm_json('prose {"title": "y"} trailing') == {"title": "y"}
    assert parse_llm_json("not json at all") is None
    assert parse_llm_json("") is None


def test_llm_config_defaults_disabled(state):
    cfg = asvc.llm_config()
    assert isinstance(cfg, LLMConfig)
    assert cfg.timeout > 0 and cfg.max_tokens > 0
    # without an API key the pipeline must use the deterministic provider
    assert cfg.enabled == bool(cfg.api_key)


# ------------------------------------------------------- §36/§44 service

def test_analyze_now_persists_analysis_recs_evidence(state):
    result = _run(asvc.analyze_now(state, force=True, trigger="test"))
    analysis_id = result["analysis_id"]
    assert result["cached"] is False
    with SessionLocal() as db:
        row = db.get(AiAnalysis, analysis_id)
        assert row is not None
        assert row.mode == result["mode"]
        assert row.severity == result["situation"]["severity"]
        assert row.confidence == pytest.approx(result["confidence"]["overall"])
        recs = db.query(AiRecommendation).filter_by(analysis_id=analysis_id).all()
        assert recs and all(r.requires_human_approval for r in recs)
        evs = db.query(AiEvidence).filter_by(analysis_id=analysis_id).all()
        assert len(evs) == len(result["evidence"])
        assert row.payload.get("context_summary", {}).get("signature")


def test_cache_reuse_and_cooldown(state):
    r1 = _run(asvc.analyze_now(state, force=True))
    # unchanged situation → signature cache hit (§44)
    r2 = _run(asvc.analyze_now(state))
    assert r2["cached"] is True and r2["analysis_id"] == r1["analysis_id"]
    assert state.analyst_health["cache_hits"] >= 1

    # cooldown (§36): a changed context is still suppressed right after a run
    state.analyst_last_run = time.monotonic()
    _publish_risk(state, 76.0, "HIGH")
    suppressed = _run(asvc.analyze_now(state))
    assert suppressed["analysis_id"] == r1["analysis_id"]

    # critical situations bypass the cooldown after 5s
    state.analyst_last_run = time.monotonic() - 6.0
    _publish_risk(state, 92.0, "CRITICAL")
    critical = _run(asvc.analyze_now(state))
    assert critical["analysis_id"] != r1["analysis_id"]
    assert critical["situation"]["severity"] in ("HIGH", "CRITICAL")

    # normal cooldown expiry lets a run through
    state.analyst_last_run = time.monotonic() - 100.0
    _publish_risk(state, 40.0, "MODERATE", trend="STABLE")
    later = _run(asvc.analyze_now(state))
    assert later["analysis_id"] != critical["analysis_id"]


def test_queued_ws_events(state):
    state.pending_sim_events.clear()
    _run(asvc.analyze_now(state, force=True))
    events = [e["event"] for e in state.pending_sim_events]
    assert "analyst.analysis_started" in events
    assert "analyst.analysis_completed" in events
    assert "analyst.recommendation_created" in events
    completed = next(e for e in state.pending_sim_events
                     if e["event"] == "analyst.analysis_completed")
    assert "context_summary" not in completed["data"]["result"]
    assert completed["data"]["analysis_id"]

    state.pending_sim_events.clear()
    _publish_risk(state, 88.0, "CRITICAL")
    _run(asvc.analyze_now(state, force=True))
    events2 = [e["event"] for e in state.pending_sim_events]
    assert "analyst.analysis_updated" in events2, "what_changed must be announced"
    if "analyst.alert_created" in events2:
        alert = next(e for e in state.pending_sim_events
                     if e["event"] == "analyst.alert_created")
        assert alert["data"]["alert"]["severity"] == "CRITICAL"
    state.pending_sim_events.clear()


def test_status_block_reports_fallback(state):
    st = asvc.status(state)
    assert st["status"] in ("ONLINE", "FALLBACK", "DEGRADED", "OFFLINE")
    assert st["status"] == "FALLBACK", "no LLM_API_KEY in tests → deterministic"
    assert st["llm_configured"] is False
    assert st["model"] == "deterministic-analyst-v1"
    _run(asvc.analyze_now(state, force=True))
    st2 = asvc.status(state)
    assert st2["runs"] >= 1 and st2["last_source"] == "local_fallback"
    assert st2["current_analysis"] == state.analyst["analysis_id"]
    assert st2["cooldown_seconds"] > 0


def test_background_schedule_never_blocks_tick(state):
    async def scenario():
        state.pending_sim_events.clear()
        assert asvc.schedule(state, trigger="test") is True
        assert asvc.schedule(state) is False, "in-flight guard must hold"
        await state._analyst_task
        assert state._analyst_inflight is False
        assert state.analyst and state.analyst.get("analysis_id")
    _run(scenario())
    state.pending_sim_events.clear()


def test_recommendation_decision_human_in_the_loop(state):
    result = _run(asvc.analyze_now(state, force=True))
    rec_id = result["recommendations"][0]["id"]
    with SessionLocal() as db:
        # unknown id → LookupError (route maps to 404)
        with pytest.raises(LookupError):
            asvc.decide_recommendation(db, "rec_missing", "ACCEPTED", "op")
        outcome = asvc.decide_recommendation(db, rec_id, "ACCEPTED", "operator")
        assert outcome["status"] == "ACCEPTED" and outcome["decided_by"] == "operator"
        row = db.get(AiRecommendation, rec_id)
        assert row.status == "ACCEPTED" and row.decided_at is not None
        # double-decision is refused (409)
        with pytest.raises(ValueError):
            asvc.decide_recommendation(db, rec_id, "DISMISSED", "operator")
        # invalid decision value refused (422 at the schema layer)
        with pytest.raises(ValueError):
            asvc.decide_recommendation(db, rec_id, "MAYBE", "operator")


def test_persistence_is_bounded(state, monkeypatch):
    monkeypatch.setattr(asvc, "ANALYSIS_LIMIT", 2)
    ids = []
    for score, level in ((10.0, "LOW"), (50.0, "ELEVATED"), (70.0, "HIGH")):
        _publish_risk(state, score, level)
        ids.append(_run(asvc.analyze_now(state, force=True))["analysis_id"])
    with SessionLocal() as db:
        assert db.get(AiAnalysis, ids[0]) is None, "oldest analysis pruned"
        assert db.get(AiAnalysis, ids[2]) is not None
        stale = db.query(AiEvidence).filter_by(analysis_id=ids[0]).all()
        assert stale == [], "evidence pruned with its analysis"


# ------------------------------------------------------------ §49 API surface

def _reset_singleton():
    st = get_state()
    full_reset(st)
    st.pending_sim_events.clear()
    return st


def test_http_analyze_endpoint_structure_and_rbac():
    st = _reset_singleton()
    ok = client.post("/api/ai/analyze", json={}, headers=ANALYST)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    for key in ("analysis_id", "situation", "recommendations", "confidence",
                "evidence", "route_assessment", "what_happened", "source",
                "recommended_action", "human_decision_required"):
        assert key in body, f"missing {key}"
    assert body["source"] in ("local_fallback", "llm")
    assert body["human_decision_required"] is True
    assert body["recommendations"][0]["requires_human_approval"] is True

    # invalid mode → 400 with a helpful message
    bad = client.post("/api/ai/analyze", json={"mode": "WRONG"}, headers=ANALYST)
    assert bad.status_code == 400 and "mode" in bad.json()["detail"].lower()

    # RBAC: viewer cannot analyze; operator lacks 'analyze' (read/apply only)
    assert client.post("/api/ai/analyze", json={}, headers=VIEWER).status_code == 403
    assert client.post("/api/ai/analyze", json={}, headers=OPERATOR).status_code == 403
    # question is accepted and answered
    q = client.post("/api/ai/analyze",
                    json={"question": "What is the confidence?"},
                    headers=ADMIN)
    assert q.status_code == 200 and q.json()["query_answer"]
    st.pending_sim_events.clear()


def test_http_analysis_history_endpoints():
    st = _reset_singleton()
    created = client.post("/api/ai/analyze", json={}, headers=ANALYST).json()
    aid = created["analysis_id"]

    listing = client.get("/api/ai/analysis", headers=ANALYST)
    assert listing.status_code == 200
    assert any(a["analysis_id"] == aid for a in listing.json()["analyses"])

    latest = client.get("/api/ai/analysis/latest", headers=ANALYST)
    assert latest.status_code == 200

    detail = client.get(f"/api/ai/analysis/{aid}", headers=ANALYST)
    assert detail.status_code == 200
    assert detail.json()["analysis_id"] == aid

    missing = client.get("/api/ai/analysis/anl_nope", headers=ANALYST)
    assert missing.status_code == 404
    assert client.get("/api/ai/analysis", headers=VIEWER).status_code == 200
    st.pending_sim_events.clear()


def test_http_recommendations_decision_and_evidence():
    st = _reset_singleton()
    created = client.post("/api/ai/analyze", json={}, headers=ANALYST).json()
    rec_id = created["recommendations"][0]["id"]
    ev_id = created["evidence"][0]["id"]
    assert ev_id.startswith(f"{created['analysis_id']}:")

    recs = client.get("/api/ai/recommendations", headers=ANALYST)
    assert recs.status_code == 200
    assert any(r["recommendation_id"] == rec_id
               for r in recs.json()["recommendations"])

    detail = client.get(f"/api/ai/recommendations/{rec_id}", headers=ANALYST)
    assert detail.status_code == 200 and detail.json()["action"]

    # human-in-the-loop: analyst role cannot decide (needs 'apply')
    assert client.post(f"/api/ai/recommendations/{rec_id}/decision",
                       json={"decision": "ACCEPTED"},
                       headers=ANALYST).status_code == 403
    decision = client.post(f"/api/ai/recommendations/{rec_id}/decision",
                           json={"decision": "ACCEPTED"}, headers=OPERATOR)
    assert decision.status_code == 200
    assert decision.json()["status"] == "ACCEPTED"
    # double-decision → 409, bad enum → 422, unknown → 404
    assert client.post(f"/api/ai/recommendations/{rec_id}/decision",
                       json={"decision": "DISMISSED"},
                       headers=OPERATOR).status_code == 409
    assert client.post(f"/api/ai/recommendations/{rec_id}/decision",
                       json={"decision": "MAYBE"}, headers=OPERATOR).status_code == 422
    assert client.post("/api/ai/recommendations/rec_missing/decision",
                       json={"decision": "ACCEPTED"},
                       headers=OPERATOR).status_code == 404

    ev = client.get(f"/api/ai/evidence/{ev_id}", headers=ANALYST)
    assert ev.status_code == 200
    assert ev.json()["metric"] and ev.json()["analysis_id"]
    assert client.get("/api/ai/evidence/anl_x:ev_999", headers=ANALYST).status_code == 404
    st.pending_sim_events.clear()


def test_http_status_includes_analyst_block():
    st = _reset_singleton()
    client.post("/api/ai/analyze", json={}, headers=ANALYST)
    resp = client.get("/api/ai/status", headers=ANALYST)
    assert resp.status_code == 200
    body = resp.json()
    assert "analyst" in body
    analyst = body["analyst"]
    assert analyst["status"] in ("ONLINE", "FALLBACK", "DEGRADED", "OFFLINE")
    assert analyst["llm_configured"] is False
    assert analyst["runs"] >= 1
    legacy = client.get("/api/ai/analyst", headers=ANALYST)
    assert legacy.status_code == 200 and legacy.json().get("recommended_action")
    st.pending_sim_events.clear()


def test_answer_question_helper_shapes():
    ctx_risk = {"risk": {"score": 12.0, "level": "LOW", "trend": "STABLE"},
                "routes": {"recommended": None}, "people_at_risk": 0,
                "campus": {"active_incidents": 0}}
    narrative = {"title": "t", "summary": "Campus stable.", "why": [],
                 "predicted_effects": [], "affected_areas": ["Campus"],
                 "route_assessment": {}}
    out = answer_question("why is the risk high?", ctx_risk, narrative, [], {
        "overall": 0.8, "level": "HIGH", "notes": ["all fresh"]})
    assert "LOW" in out and "12" in out
    conf = answer_question("what is the confidence?", ctx_risk, narrative, [], {
        "overall": 0.8, "level": "HIGH", "notes": ["all fresh"]})
    assert "80%" in conf
