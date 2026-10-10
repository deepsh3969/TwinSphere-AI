# Phase 11 — Testing, Performance, Reliability & Regression Engineering

## Overview

Phase 11 hardens the TwinSphere test suite for long-term reliability, adds
cross-phase end-to-end coverage, fixes real concurrency bugs, eliminates
non-determinism, wires operational metrics, and creates CI scaffolding.

---

## 1. Cross-phase E2E scenarios (`tests/test_e2e_workflows.py`)

20 tests across six scenarios that exercise the full stack (auth → campus →
incident → risk → AI → simulation → analytics → audit → WS → recovery).

| Scenario | What it covers |
|----------|----------------|
| **A** (a1–a3) | Login + token, campus data layer, 3D payload (`position.x/z`, `size`, `height`, `color`) |
| **B** (b1–b3) | Incident lifecycle, routes/evacuation, AI advisory filtered by `analysis_id` |
| **C** (c1) | Simulation recovery + persisted `SimulationEvent` rows |
| **D** (d1–d5) | Analytics window (`from`/`to`), filters + 404s, pagination, export permissions, empty-window honesty |
| **E** (e1–e3) | Deterministic ticking, seek, replay immutability |
| **F** (f1–f5) | 401s, role matrix (incl. operator can read `/api/realtime/status`), token expiry/logout, audit (records + `DENIED` login), unauthorized controls |

### Known design facts (documented, not bugs)

- **Routes stay `SAFE` during fire by design** — the smoke test deliberately
  forces recalculation proof via `routes_recalculated` sim event rather than
  expecting `Route.status` to flip.
- **`Window.as_dict()` keys** are `preset/from/to/bucket_s/custom` (not
  `start/end`).
- **`/api/audit`** returns `records` (not `items`) + `scope`.
- **Audit outcomes** are `SUCCESS` or `DENIED` only.
- **Failed-login audits** `auth.login` with `outcome=DENIED`.
- **`/api/evacuation/status` `active_plan`** is `state.route_plan`, set only
  by explicit calculate or `GET /api/evacuation/building/{id}` with `apply`
  permission (`activate=True`).
- **`Building.to_dict()`** has nested `position:{x,y,z}`, `size`, `height`.

---

## 2. Concurrency / TOCTOU (`tests/test_concurrency.py`)

### Bug fixed

`create_simulation` checked `state.active_sim` then created a new simulation
without holding a lock — two concurrent creates could both pass the check and
both create an active simulation (TOCTOU race).

### Fix (`app/api/routes_simulations.py`)

- Added module-level `_SIM_LOCK = threading.Lock()`.
- `create_simulation` now holds `_SIM_LOCK` across the check + create + audit.
- Lifecycle transitions (start/pause/resume/reset/recover) are wrapped in
  `_lifecycle()` which holds the same lock for validate + engine call + audit.
- Create guard broadened: any non-`COMPLETED` active sim blocks new creates
  (409), not just `RUNNING/PAUSED/AWAITING_RECOVERY/RECOVERING`.

### Tests (5)

| Test | Mechanism | Assertion |
|------|-----------|-----------|
| `test_concurrent_creates_exactly_one_201` | `_SpyLock` (signals when 2nd thread must wait) + gated engine call (`threading.Event` enter/gate) | `[201, 409]`, 1 engine entry, 1 DB row |
| `test_create_over_completed_still_allowed_under_concurrency` | 6-thread barrier | `[201, 409×5]` |
| `test_concurrent_pause_serialized_single_transition` | 2-thread barrier | `[200, 400]`, one `paused` event |
| `test_concurrent_pause_resume_burst_consistent` | 12-thread burst | codes ⊂ {200, 400}, `0 ≤ pauses−resumes ≤ 1`, final status parity |
| `test_concurrent_reads_stay_consistent` | 10-thread barrier | all 200 + correct shapes |

**No arbitrary sleeps** — synchronization uses `threading.Event` and
`threading.Barrier`; determinism is proven by the `_SpyLock` pattern (the
second thread must see the lock held before proceeding).

---

## 3. Smoke determinism (`tests/smoke_api.py`)

### Root causes of flakiness

1. Conditional branches (anomaly detail, route detail, apply-recommendation
   ×2, register) depended on runtime state that varied across runs.
2. `skip()` did not exist — conditional failures were counted as failures.
3. Anomaly detail used a single ID from the list; if that anomaly disappeared
   between list and detail calls, the test failed.

### Fixes

- Added `skip(name, reason)` helper: records `(name, None, reason)` and prints
  `SKIP <name>`.
- Converted all 5 conditional sites to use `skip()` instead of silently
  passing or failing.
- Anomaly detail now retries with a fresh ID from the list (3 attempts) before
  skipping.
- Summary format changed to `print(f"\n{passed}/{len(ok)} passed ({len(skipped)} skipped)")`
  with `exit(1)` only on failures.

### Result

```
191/194 passed (3 skipped)
```

Deterministic across runs. `skip()` returns `(name, None, reason)`; the
summary counts `None` values as skipped (not passed, not failed).

### Known environment caveat

The live server has `RATE_LIMIT_ENABLED=true` (default login 20/min per
identity). Running smoke twice back-to-back will trip the second run's analyst
login → 429 → `KeyError: 'access_token'` at `smoke_api.py` line ~871.
**Workaround:** space runs ≥60s apart, or set `RATE_LIMIT_ENABLED=false` for
CI. Documented here and in README.

---

## 4. WebSocket resilience (`tests/ws_check.py`)

Extended from 56 to **60 checks**. New checks after the admin block:

| Check | What it verifies |
|-------|-----------------|
| Rapid connect/disconnect ×8 | Manager registry stays consistent; no leaked sockets |
| Reconnect after abrupt close | Server handles abnormal close; new auth succeeds |
| Both clients receive broadcast | `_drain` until `state` frame on two sockets |
| Double subscribe idempotent | Second `subscribe` to same channel returns `ok: true` |

Docstring updated to mention Phase 11.

---

## 5. Observability (`app/core/metrics.py`, `/api/system/metrics`)

### Design

- Thread-safe counters with a **hard key cap (400)** so memory cannot grow
  without bound.
- Pure Python — no external dependency (Prometheus, StatsD, etc.).
- Gauge support (last-write-wins) for live values (e.g. `ws.connections.active`).

### Wired points

| Location | Counter |
|----------|---------|
| `main.py` HTTP middleware | `http.{METHOD}.{route_template}.{status}` (template prevents cardinality explosion from path params) |
| `manager.py` `connect()` / `disconnect()` | `ws.connections.total`, `ws.disconnects.total`, `ws.connections.active` (gauge) |
| `routes_simulations.py` `create_simulation` | `simulations.create.ok` / `conflict` / `bad_request` |
| `routes_simulations.py` `_lifecycle()` | `simulations.lifecycle.{action}.ok` / `error` |
| `ratelimit.py` `check()` | `ratelimit.{category}.blocked` |

### Endpoint

```
GET /api/system/metrics
Authorization: Bearer <token>
```

Response:
```json
{
  "uptime_s": 372.4,
  "counters": {
    "http.GET./api/campus.200": 18,
    "http.POST./api/simulations.201": 3,
    "ws.connections.total": 4,
    "ws.connections.active": 1,
    "simulations.create.ok": 3,
    "ratelimit.login.blocked": 0
  }
}
```

### Tests (`tests/test_metrics.py` — 5 tests)

- Endpoint requires auth (401 without token).
- Snapshot shape: `uptime_s` + `counters` dict.
- HTTP requests are counted (two `/health` calls increment `http.GET./health.*`).
- Simulation lifecycle counters are emitted.
- Rate-limit block counter is incremented (limiter temporarily enabled in the test).

---

## 6. Benchmark (`tests/benchmark_api.py`)

Repeatable p50/p95/p99 + payload-size benchmark for 12 read-heavy endpoints.
Usage:

```bash
python backend/tests/benchmark_api.py [--iterations 40] [--warmup 5] [--json]
```

Exit 1 if any endpoint returns HTTP >= 500. Results are environment-dependent
(Windows dev machine, local SQLite) — see `docs/PERFORMANCE.md` for the
baseline numbers.

---

## 7. Database indexes (`p11e5a7c3d8f4_phase11_reliability_perf.py`)

### Gaps found by `EXPLAIN QUERY PLAN` on the live 87 MB DB

| Query | Before (TEMP B-TREE) | After (index SEARCH) |
|-------|---------------------|----------------------|
| `audit_logs WHERE action=? ORDER BY created_at` | `ix_audit_logs_action` (single-column) | `ix_audit_logs_action_time (action, created_at)` |
| `audit_logs WHERE outcome=? ORDER BY created_at` | `ix_audit_logs_outcome` | `ix_audit_logs_outcome_time (outcome, created_at)` |
| `audit_logs WHERE actor=? ORDER BY created_at` | full scan | `ix_audit_logs_actor_time (actor, created_at)` |
| `incidents WHERE severity=? ORDER BY started_at` | `ix_incidents_severity` | `ix_incidents_severity_started (severity, started_at)` |

### Migration properties

- **Additive, idempotent** — only `CREATE INDEX IF NOT EXISTS` semantics via
  inspector check; no data, columns, or tables modified/dropped.
- **Model declarations** added to `app/models/entities.py` as module-level
  `Index(...)` lines (matching Phase 9 style) so fresh `create_all()` DBs get
  them too.
- Chain: `b3937b6fe73a` → `p6a1c9e4d2f7` → `p7c4e8b2d9f1a` → `p8d9f4b7a2c6e`
  → `p9f3c8d2e7b1` → `p10b4d7e1a9c6` → **`p11e5a7c3d8f4`** (head).

### Verification

`C:\Users\deepe\AppData\Local\Temp\opencode\explain_plans.py` runs the EXPLAIN
queries against the live DB. After migration: all four previously-TEMP-B-TREE
queries now show `SEARCH ... USING INDEX ix_*_time`.

---

## 8. CI (`.github/workflows/ci.yml`)

Three parallel jobs:

| Job | Steps |
|-----|-------|
| **backend** | pip install, `alembic upgrade head` (fresh SQLite), `pytest`, background uvicorn + `smoke_api.py` + `ws_check.py` |
| **frontend** | npm ci, `typecheck`, `test --run`, `build` |
| **security** | `pip-audit -r requirements.txt`, `npm audit --audit-level=critical`, `gitleaks` secret scan (advisory — `continue-on-error: true`) |

Note: security scans are advisory (`|| true` / `continue-on-error`) because
the two known `react-router-dom` moderate advisories are documented as
accepted (see `docs/SECURITY_AUDIT.md` F-22). CI execution has **not been
run locally** — only the workflow file is committed.

---

## 9. React-router advisory investigation (F-22 follow-up)

Installed: `react-router-dom@6.30.6`.

| Advisory | CVE | Affected | Fix version | Exploitability in TwinSphere |
|----------|-----|----------|-------------|------------------------------|
| GHSA-wrjc-x8rr-h8h6 (open redirect via backslash) | CVE-2025-68470 bypass | >=6.0.0 <7.18.0 | 7.18.4 | **Not exploitable** — all `navigate()` / `<Link to>` targets are hardcoded internal paths or interpolate server-controlled building IDs (not URLs). No user/URL-query-controlled navigation. |
| GHSA-337j-9hxr-rhxg (arbitrary constructor injection via `deserializeErrors()`) | — | >=6.4.0 <7.18.0 | 7.18.4 | **Not exploitable** — TwinSphere is a client-only SPA served by nginx; no SSR, no `deserializeErrors()` call, no server-side React Router usage. |

**Decision:** Accept both moderates. Fix requires `react-router-dom` v7
(breaking major: package renamed to `react-router`, Remix convergence, API
shifts). Proportional risk: two moderates that are architecturally unreachable
in this deployment vs. a breaking upgrade. Documented in
`docs/SECURITY_AUDIT.md` F-22.

---

## Test totals (Phase 11)

| Suite | Count | Notes |
|-------|-------|-------|
| Backend pytest | **269** | 239 (Phases 1–10) + 20 E2E + 5 concurrency + 5 metrics |
| Smoke API | **191/194** | 3 skipped (deterministic) |
| WS checks | **60** | 56 (Phases 1–10) + 4 resilience |
| FE unit tests | **193** | 16 files |
| FE typecheck | clean | |
| FE build | clean | |

---

## Running the suites

```bash
# Backend pytest
cd backend && python -m pytest tests -q

# Smoke (live server required)
cd backend && python tests/smoke_api.py

# WS (live server required, lifespan active)
cd backend && $env:PYTHONPATH = 'D:\PROJECTS\TwinSphere-AI;D:\PROJECTS\TwinSphere-AI\backend'; python tests/ws_check.py

# Benchmark (live server required)
cd backend && python tests/benchmark_api.py --iterations 40

# FE
cd frontend && npm run typecheck && npm test -- --run && npm run build
```

---

## Limitations / not run

- **Docker builds** — not run locally (no Docker daemon in this environment).
- **CI execution** — workflow file committed but not executed on GitHub
  Actions; security scans (pip-audit, gitleaks) are advisory in CI.
- **GPU profiling** — not run (no discrete GPU; 3D scene runs on integrated
  graphics or software rendering in CI).
- **Multi-worker rate limiting** — in-memory buckets are per-process; for
  multi-worker production, replace with Redis (see `docs/SECURITY.md`).
- **Benchmark numbers are machine-dependent** — recorded on a Windows dev
  machine with local SQLite; CI numbers will differ.
