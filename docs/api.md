# TwinSphere AI — API Reference (Simulations, Routes & AI Analyst)

The full REST surface is summarised in the README (`## API surface`). This document
covers the **simulation API group** (the Phase 6 what-if engine endpoints), the
**route/evacuation API group** (Phase 7) and the **AI analyst group** (Phase 8)
in detail — plus the conventions every group shares.

## Conventions

- **Base URL** `http://127.0.0.1:8000` · all routes under `/api/*` · raw resource
  objects (no envelope) · every telemetry payload carries `source: "SIMULATED"`.
- **Auth** — `Authorization: Bearer <JWT>` from `POST /api/auth/login`
  (`{"username": "operator", "password": "operator123"}` → `access_token`).
  - `read` — ADMIN · OPERATOR · ANALYST · VIEWER (list/detail/results/events)
  - `simulate` — ADMIN · OPERATOR (create + lifecycle actions)
- **Errors** — FastAPI/Pydantic defaults: `{"detail": "..."}` with status:
  - `400` engine validation (`ValueError` message from `simulation_engine`)
  - `401` missing/invalid token · `403` role lacks permission
  - `404` unknown `target_id` on create; unknown `sim_id` on detail/results (after the
    history lookup); lifecycle routes only resolve the **active** `sim_id` — unknown or
    history-only ids → 404
  - `409` second active simulation (spec message, see below)
  - `422` malformed JSON/field types (`scenario` itself is a free string — unknown
    scenarios are `400`, not `422`)
- **WebSocket** — typed `simulation.*` events on `/ws` (see `docs/simulation.md`).

## Endpoints

### `GET /api/simulations`

History envelope (latest 50). Role: `read`.

```json
{"active": null,
 "history": [
  {"id": "sim_a1b2c3d4e5", "simulation_code": "SIM-3F9C21", "scenario": "fire",
   "target_id": "eng", "target_type": "BUILDING", "status": "COMPLETED",
   "progress": 100.0, "peak_risk": 78.4, "people_affected": 42,
   "recovery_time_s": 128.4, "params": {...}, "result": {"results": {...}},
   "created_by": "operator", "created_at": "2026-10-05T09:12:03Z",
   "ended_at": "2026-10-05T09:18:41Z"}
 ]}
```

### `POST /api/simulations` → `201`

Create a drill (role: `simulate`). Only **one active simulation** at a time.

```json
// body — fire example
{"scenario": "fire", "target_id": "eng",
 "params": {"intensity": 4, "wind": "E", "ignition_zone": "eng_lab_101"}}
```

| Scenario | `target_id` | `params` |
|---|---|---|
| `fire` | required (building id/code) | `intensity` 1–10 (UI 1–5), `wind` ∈ N/NE/E/SE/S/SW/W/NW/NONE, `ignition_zone` (alias `zone_id`), `initial_occupancy` ≥ 0, `burn_rate` |
| `crowd` | required | `occupancy_increase` 0–300 (default 40) |
| `power` | required | — |
| `road` | optional (road id, defaulted) | `road_id` must exist |
| `temperature` | optional (campus-wide) | — |

Responses (checked in this order): `201` full sim dict · `404` target building not
found · `409` active simulation (RUNNING/PAUSED/AWAITING_RECOVERY/RECOVERING) ·
`400` parameter/scenario validation.

```json
{"id": "sim_a1b2c3d4e5", "simulation_code": "SIM-3F9C21", "scenario": "fire",
 "target_id": "eng", "status": "CREATED", "phase": "created",
 "duration": 330.0, "recover_duration": 130.0, "t": 0.0, "progress": 0.0,
 "risk": {...}, "people_at_risk": 0, "weighted_people": 0, "affected_zones": 0,
 "peak_temperature": 24.0, "peak_smoke": 0.0, "params": {...}, "events": [...],
 "clock": 14.5, "speed": 1.0}
```

### `GET /api/simulations/active`

Current in-memory sim (or `null`). Role: `read`. Handy for UIs that opened a page
mid-run.

### `GET /api/simulations/{sim_id}` (§53)

Full detail: **active run first** (fresh in-memory state), otherwise the persisted
history row (incl. `result.results`). Role: `read`. `404` on unknown id.

### `GET /api/simulations/{sim_id}/results` (§48)

Honest results block — computed **live** while the sim is active, read from the stored
row afterwards. Role: `read`. `404` on unknown id.

```json
{"simulation_id": "sim_a1b2c3d4e5", "status": "COMPLETED", "live": false,
 "results": {"scenario": "fire", "scenario_label": "Fire Emergency",
   "target_id": "eng", "target_name": "Engineering Block",
   "peak_risk": 78.4, "peak_risk_level": "HIGH",
   "peak_people_at_risk": 42, "weighted_people_at_risk": 31.8,
   "affected_zone_count": 5, "peak_temperature": 61.2, "peak_smoke": 188.0,
   "smoke_band": "HEAVY", "burning_zones": 2, "duration_s": 330.0,
   "recovery_time_s": 130.0, "events": 27,
   "intensity": 4, "intensity_label": "SEVERE", "wind": "E"},
 "created_at": "...", "ended_at": "..."}
```

### Lifecycle (role: `simulate`, audited)

All lifecycle routes resolve **only the active simulation's id** — unknown or
history-only ids → `404`. Engine-level refusal surfaces as `400` with its message.

| Route | Effect | Key errors |
|---|---|---|
| `POST /api/simulations/{id}/start` | CREATED/RESET/PAUSED → RUNNING; first start ignites the scenario, creates the incident (`simulation_id`) and queues `simulation.started` (a restart of a paused sim queues `simulation.resumed`) | 404 · 400 "Cannot start simulation in status X" |
| `POST /api/simulations/{id}/pause` | RUNNING → PAUSED (clock + sim freeze) | 404 · 400 "Simulation is not running" |
| `POST /api/simulations/{id}/resume` | PAUSED → RUNNING | 404 · 400 "Simulation is not paused" |
| `POST /api/simulations/{id}/reset` | clear state + Phase 6 deltas → CREATED, campus status back to NORMAL (`simulation.reset`) | 404 |
| `POST /api/simulations/{id}/recover` | → RECOVERING, gradual glide, `simulation.recovery_started` | 404 · 400 "Simulation already completed" |

On duration end the run becomes `AWAITING_RECOVERY` (`simulation.completed` with
`awaiting_recovery: true`); `recover` glides metrics/statuses back (exponential,
τ = 22 s) → `COMPLETED`, results persisted (`sim.results` → `simulations.result`).
`recover` is allowed from any status except `COMPLETED`.

All actions return the full sim dict (pause/resume are idempotent in the operator
sense: refusing with 400 rather than corrupting state). Changes broadcast
`simulation.status` + `system.status` on the backbone and the `simulation.*` typed
family (see `docs/simulation.md`).

### `GET /api/simulations/{sim_id}/events`

Event log for the drill (role: `read`) — persisted rows plus the live in-memory
buffer when the id is active. Unknown ids simply return empty lists (no 404).

```json
{"persisted": [{"t": 0.0, "kind": "created", "message": "Simulation Fire Emergency created.", "data": {...}}],
 "live": [{"t": 12.4, "kind": "spread", "message": "...", "data": {...}}]}
```

## Phase 7 — Routes & evacuation endpoints

All paths below are registered after the legacy `GET /api/routes` router, so
existing route endpoints keep their exact behaviour. Roles: `read` for
GETs, `apply` for `POST /api/routes/{calculate,recalculate}`. Any body
`simulation_id` must match the active simulation (else `400`); unknown modes
are `400` with the valid mode list.

### `POST /api/routes/calculate`

Point-to-point plan. Modes: `shortest | fastest | safest | balanced |
emergency` (unknown → 400, unknown node → 400).

```json
// request
{"origin": "ex_eng_s", "destination": "gate_main", "mode": "safest", "people": 120}
// response (flattened plan)
{"route_id": "rte_…", "kind": "point", "mode": "safest", "status": "RECOMMENDED",
 "route_version": 10, "path": [...], "road_path": [...],
 "distance": 186.0, "estimated_time": 152.2, "risk_score": 1.7,
 "congestion_label": "LOW", "safety": "SAFE", "confidence": "HIGH",
 "alternatives": [...], "simulation_id": null, "source": "api"}
```

### `POST /api/routes/recalculate`

Forces revalidation of the active plan (`404` when none): returns
`{"recalculated": true, "route": {…plan…}, "evacuation": {…summary…}}`.
Pass `mode` to switch weighting first.

### `GET /api/routes/alternatives?origin=&destination=&mode=&limit=`

Per-mode A* rows + cross-mode comparison (no activation):

```json
{"origin": "ex_admin", "destination": "gate_main", "mode": "balanced",
 "routes": [{…recommended…}, {…alternative…}],
 "comparison": {"rows": [{"mode": "shortest", "distance": 132.0, "risk_score": 2.4,
                          "status": "RECOMMENDED", "safety": "SAFE"},
                         {"mode": "safest", "recommended": true, …}],
                "recommended_mode": "safest"}}
```

### `GET /api/routes/evacuation` · `GET /api/evacuation/status`

Campus plan (content-gated refresh): `status` ladder
`IDLE → STANDBY → ACTIVE → CRITICAL`, `people_at_risk`,
`totals {buildings, safe_routes, blocked_routes, bottlenecks}`, per-building
plans with exit roles, exit demand/pressure rows and structured bottlenecks.
`/evacuation/status` adds `active_plan` (flattened) + `route_history_recent`
(live slice, cleared by demo reset; `/api/routes/history` is the persisted
audit that survives it).

### `GET /api/evacuation/building/{building_id}?mode=`

Single-building plan (activates it as the current plan): `status`
`READY | ACTIVE | EVACUATION_CRITICAL`, `primary_exit` / `secondary_exit`,
`exits[] {name, role: PRIMARY|SECONDARY|UNAVAILABLE, people, congestion}`,
`estimated_evacuation_s`, `route_risk`, `has_safe_route`, `reason`.
Unknown building → 400.

### `GET /api/routes/emergency` · `GET /api/emergency-response/routes`

Emergency vehicle route(s). Params: `?vehicle=fire_truck|ambulance|security`,
`?origin=`, `?destination=`. Without an incident or destination the response
is `{"status": "NO_SAFE_ROUTE", "routes": []}`.

```json
{"status": "ok", "incident_node": "ex_eng_s", "routes": [
  {"vehicle": "fire_truck", "vehicle_label": "Fire Truck", "status": "SAFE",
   "origin": "gate_east", "destination": "ex_eng_s", "road_path": [...],
   "distance": 154.0, "eta_s": 18.5, "risk_score": 2.0,
   "blocked_roads_avoided": []}]}
```

### `GET /api/routes/graph` · `GET /api/routes/bottlenecks`

Graph: `nodes[]` (incl. live `risk`), `edges[]`, `counts {nodes: 35, edges: 40}`,
`mode`, `simulation_id`. Bottlenecks: `{bottlenecks: [{location, location_id,
kind: EDGE|EXIT|NODE, severity: LOW|MEDIUM|HIGH, estimated_people, capacity,
congestion, risk, recommendation, shared_by}], exits: […]}`.

### `GET /api/routes/history?limit=&simulation_id=` · `GET /api/routes/{route_id}`

History serves persisted `route_events` rows plus `recent_in_memory` (live
session). Route detail resolves the active plan first, else the persisted
`evacuation_routes` row with its ordered events (404 only when neither
exists).

Typed WS companions: `route.calculated|updated|invalidated|recalculated`,
`emergency_route.updated`, `evacuation.started|updated|completed`,
`bottleneck.detected|cleared` (envelope v1).

## Phase 8 — AI analyst endpoints

Evidence-grounded analyst over the live engines (see `docs/AI_ANALYST.md`).
Every run returns the same strict `AnalystResult` shape whether an LLM
answered or the deterministic fallback did.

**Permissions** — `read` for all GETs; `analyze` (ADMIN · ANALYST) for
`POST /api/ai/analyze`; `apply` (ADMIN · OPERATOR) for recommendation
decisions. VIEWER → 403 on analyze/decide.

### `POST /api/ai/analyze` → `200`

Forces a fresh analysis (bypasses signature cache and cooldown). Role:
`analyze`. Body: `{"question": "…", "mode": "…"}` — optional `question` is
answered from structured data; optional `mode` ∈ `CAMPUS | INCIDENT | BUILDING
| ROUTE | SIMULATION | RECOVERY` (default auto-detected from state; unknown →
`400`). Legacy alias: `focus` is accepted wherever `mode` appears.

```json
{"analysis_id": "anl_0ccf53d58dcf", "mode": "INCIDENT", "status": "completed",
 "timestamp": "2026-10-07T17:51:29Z", "cached": false, "latency_ms": 12,
 "provider": "deterministic", "model": "deterministic-analyst-v1",
 "source": "local_fallback", "human_decision_required": true,
 "question": "How bad is it?", "query_answer": "…answered from structured data…",
 "situation": {"title": "…", "summary": "…", "severity": "HIGH",
                "priority": "HIGH", "mode": "INCIDENT"},
 "what_is_happening": ["…", "…"],
 "why": [{"factor": "…", "impact": "HIGH", "evidence": "…",
           "source": "risk_engine", "evidence_ids": ["anl_…:ev_1"]}],
 "affected_areas": ["ENG-B — fire zone eng_lab_101"],
 "predicted_effects": [{"effect": "…", "likelihood": "HIGH",
                         "time_horizon": "15 minutes", "kind": "PREDICTED",
                         "source": "prediction_engine:risk-rf-v1",
                         "metric": "risk", "evidence_ids": ["anl_…:ev_4"]}],
 "what_changed": [{"kind": "RISK", "message": "…",
                    "previous": "34.2", "current": "71.5"}],
 "route_assessment": {"status": "RECOMMENDED", "recommended_route": "…",
                       "route_id": "rte_…", "origin": "…", "destination": "…",
                       "mode": "emergency", "risk": 4.0, "estimated_time": 22.5,
                       "reason": "…", "alternatives": ["…"]},
 "evidence": [{"id": "anl_…:ev_1", "label": "Campus risk 71.5/100 (HIGH)",
                "source_type": "risk", "source_id": "", "metric": "risk_score",
                "value": 71.5, "unit": "", "severity": "HIGH",
                "timestamp": "2026-10-07T17:51:29Z", "age_seconds": 1.2,
                "confidence": 0.9, "detail": "…"}],
 "confidence": {"overall": 0.78, "level": "HIGH",
                 "components": [{"name": "sensor_availability", "value": 1.0,
                                  "weight": 0.22, "contribution": 0.22}, "…"],
                 "notes": ["…"]},
 "recommendations": [{"id": "anl_…_r1", "priority": 1, "action": "…",
                       "reason": "…", "category": "EVACUATION",
                       "evidence": ["…"], "confidence": 0.78,
                       "requires_human_approval": true, "status": "PENDING",
                       "evidence_ids": ["anl_…:ev_6", "anl_…:ev_8"],
                       "focus": {}}],
 "what_happened": "…", "why_it_matters": "…", "likely_next": "…",
 "recommended_action": "…", "context_summary": {…}, "note": null}
```

### `GET /api/ai/analysis?limit=&mode=&severity=` · `/latest` · `/{analysis_id}`

Persisted history (newest first, cap 100 rows), newest analysis for the current
state (in-memory first, then DB) and one analysis by id (`404` on unknown).
List/detail rows carry top-level `severity`/`status` for filtering.

### `GET /api/ai/recommendations?status=&analysis_id=` · `/{rec_id}`

Human-in-the-loop cards (defaults to the **latest analysis's** cards unless
`?analysis_id=` is given): `{recommendation_id, analysis_id, priority, category,
action, reason, evidence[], evidence_ids[], confidence,
requires_human_approval, status: PENDING|ACCEPTED|DISMISSED, decided_by,
decided_at, created_at}`.

### `POST /api/ai/recommendations/{rec_id}/decision` → `200`

Role `apply`, body `{"decision": "ACCEPTED" | "DISMISSED"}` (bad enum → `422`).
First decision wins — repeat → `409 {"detail": "…"}`; unknown id → `404`.
Updates the row (single source of truth; subsequent `GET`s reflect it) and
returns `{recommendation_id, analysis_id, status, decided_by, decided_at,
action}`.

### `GET /api/ai/evidence/{evidence_id}` · `GET /api/ai/status`

Evidence detail resolves an **analysis-scoped id** (`anl_…:ev_N`, URL-safe as
part of the path) back to its source analysis (`404` unknown) → the evidence
row plus `analysis_id`/`created_at`.
`/api/ai/status → {"analyst": {"status": "ONLINE|FALLBACK|DEGRADED|OFFLINE",
"llm_configured", "model", "cooldown_seconds", "cooldown_remaining_s",
"in_flight", "cache_size", "cache_hits", "runs", "fallbacks", "llm_errors",
"llm_fail_streak", "fail_streak", "last_run", "last_latency_ms",
"last_source", "last_error", "current_analysis", "severity",
"persisted_limit"}}`.

Typed WS companions: `analyst.analysis_started|analysis_completed|
analysis_updated`, `analyst.recommendation_created`, `analyst.alert_created`
(envelope v1 — `context_summary` intentionally absent; `data.analysis_id`
matches the API payloads).

## Related

- Engine reference (scenarios, propagation, recovery, WS events): `docs/simulation.md`
- Routing & evacuation reference (cost model, calibration, validity rules): `docs/ROUTING.md`
- AI analyst reference (pipeline, confidence model, fallback contract): `docs/AI_ANALYST.md`
- Runtime/WS architecture: `docs/architecture.md`
- Live check suites: `backend/tests/smoke_api.py`, `backend/tests/ws_check.py`
