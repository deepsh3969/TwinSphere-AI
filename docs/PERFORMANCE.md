# Performance — TwinSphere AI

## API benchmark baseline (Phase 11)

Recorded on Windows dev machine, local SQLite (87 MB live DB), 40 iterations
after 5 warmup requests, `httpx` sequential client. Run
`python backend/tests/benchmark_api.py` to reproduce on your hardware.

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) | payload (bytes) | code |
|----------|----------|----------|----------|-----------|-----------------|------|
| `GET /health` | 1.5 | 1.9 | 1.9 | 1.5 | 152 | 200 |
| `GET /api/campus` | 11.6 | 13.8 | 14.5 | 12.0 | 72 966 | 200 |
| `GET /api/buildings/eng` | 5.2 | 6.1 | 6.6 | 5.3 | 14 855 | 200 |
| `GET /api/simulations` | 32.9 | 37.8 | 128.5 | 37.3 | 225 302 | 200 |
| `GET /api/analytics/overview` | 236.1 | 264.6 | 427.9 | 245.5 | 2 479 | 200 |
| `GET /api/ai/analyst` | 5.1 | 5.7 | 6.0 | 5.1 | 21 739 | 200 |
| `GET /api/incidents` | 3.7 | 8.4 | 73.1 | 7.5 | 1 921 | 200 |
| `GET /api/analytics/risk` | 45.0 | 149.5 | 177.3 | 60.5 | 18 784 | 200 |
| `GET /api/audit` | 7.5 | 8.2 | 8.7 | 7.6 | 12 309 | 200 |
| `GET /api/history/simulations` | 7.4 | 8.1 | 8.3 | 7.4 | 8 462 | 200 |
| `GET /api/system/status` | 3.1 | 4.1 | 4.1 | 3.3 | 1 180 | 200 |
| `GET /api/realtime/status` | 3.3 | 3.8 | 4.0 | 3.3 | 292 | 200 |

### Observations

- **`/api/analytics/overview`** (~240 ms p50) is the slowest endpoint — it
  performs aggregation across incidents, occupancy, risk scores, and energy
  tables for the default window. Payload is small (2.5 KB); latency is
  dominated by SQLite aggregation, not serialization.
- **`/api/simulations`** (~37 ms p50, 225 KB payload) returns the full
  simulation history (up to 50 rows). The large payload is by design (FE
  paginates client-side).
- **`/api/campus`** (~12 ms, 73 KB) is the 3D scene bootstrap payload
  (buildings + zones + roads + sensors). Stable and well under any UX
  threshold.
- **`/api/incidents`** p99 spikes to ~73 ms — likely first-call SQLite page
  cache miss after other tests write to the DB; not observed in isolation.

---

## Database hot-path indexes

Phase 11 added four composite indexes to eliminate `TEMP B-TREE` sorts on
filtered+sorted queries. Verified with `EXPLAIN QUERY PLAN` against the live
87 MB DB (script: `C:\Users\deepe\AppData\Local\Temp\opencode\explain_plans.py`).

### Before → after

| Query | Before | After |
|-------|--------|-------|
| `audit_logs WHERE action=? ORDER BY created_at` | `SCAN ... USING INDEX ix_audit_logs_action` + TEMP B-TREE for sort | `SEARCH ... USING COVERING INDEX ix_audit_logs_action_time (action=?)` |
| `audit_logs WHERE outcome=? ORDER BY created_at` | `SCAN ... USING INDEX ix_audit_logs_outcome` + TEMP B-TREE | `SEARCH ... USING COVERING INDEX ix_audit_logs_outcome_time (outcome=?)` |
| `audit_logs WHERE actor=? ORDER BY created_at` | full table scan + TEMP B-TREE | `SEARCH ... USING INDEX ix_audit_logs_actor_time (actor=?)` |
| `incidents WHERE severity=? ORDER BY started_at` | `SCAN ... USING INDEX ix_incidents_severity` + TEMP B-TREE | `SEARCH ... USING INDEX ix_incidents_severity_started (severity=?)` |

### Already indexed (unchanged)

- `simulations (created_at)` — list scan
- `simulation_events (simulation_id, t)` — replay reads
- `sensor_readings (sensor_id, created_at)` — sensor history
- `risk_scores (entity_id, created_at)` — analytics range scans
- `route_events (simulation_id, created_at)` — route analytics
- `occupancy_records (building_id, created_at)` — occupancy range scans
- `simulations (status)` — status filter

Migration: `p11e5a7c3d8f4_phase11_reliability_perf.py` (additive, idempotent).

---

## Frontend / 3D performance (Phase 11)

### Store-level capping (already in place, verified)

| Buffer | Cap | Location |
|--------|-----|----------|
| LIVE_LOG_CAP | 40 | `useTwinStore.ts` |
| METRIC_HISTORY_CAP | 30 | `useTwinStore.ts` |
| SENSOR_WINDOW_CAP | 120 | `useTwinStore.ts` |
| timeline events | 120 | `useTwinStore.ts` |
| anomalies | 50 | `useTwinStore.ts` |

### Phase 11 optimizations applied

| File | Optimization | Impact |
|------|-------------|--------|
| `useTwinStore.ts` | `replayEvents` WeakMap cache — stable events array per payload | Eliminates per-frame array identity churn; memoized children stop re-rendering |
| `useTwinStore.ts` | `tickReplay` frame-gating — only rebuilds `replaySnapshot` when `frameAt` changes | Reduces work on high-frequency replay ticks |
| `useTwinStore.ts` | `simulation.tick` handler caps `events` to `slice(-120)` | Prevents unbounded event growth during long runs |
| `Ground.tsx` | Removed unused `snapshot` prop | Memo is now effective (was receiving a new object every render) |
| `CampusScene.tsx` | `BuildingBlock` `onSelect={selectBuilding}` (stable) | Stops per-render inline closures (`() => selectBuilding(b.id)`) |
| `BuildingBlock.tsx` | `onSelect: (id: string) => void`, calls `onSelect(building.id)` | Consistent signature with stable parent handler |
| `SensorMarkers.tsx` | Effect deps trimmed to `[geoKey, emphasis]` / `[colorKey, colorFor]` | Avoids re-running effects when `sensors` array identity changes every frame |
| `EventTimeline.tsx` | `useMemo` + Set-based dedupe (`kind:Math.round(t*100)` keys) | Replaces O(timeline × simEvents) nested scan |
| `FireEffect.tsx` | Refs write `el` (null) so stale groups clear; smoke stride `i*2`/`i*2+1`; refs typed `(THREE.Group | null)[]` | Prevents memory leak from orphaned `THREE.Group`s; fixes collision between smoke and fire refs |

### Known architectural finding (documented, not fixed)

**CampusScene subtree re-renders on every WebSocket frame.** The Zustand
selector returns a new object each time (`snapshot`), so React re-renders the
entire 3D subtree (buildings, roads, sensors, effects) on every ~1s tick.
This is acceptable at current scale (6 buildings, ~20 sensors) but would
become a bottleneck with 50+ buildings or sub-second tick rates. Fixing it
requires either a selector that returns stable references for unchanged
objects, or splitting the scene into independently-subscribed subtrees.
Deferred to Phase 12.

---

## WS / realtime

- **Manager**: asyncio lock-guarded connection registry; broadcast filtered by
  channel permission (`state` → `read`, `admin` → `manage`).
- **Revalidation**: long-lived sockets are re-validated against the DB every
  60 s; disabled/deleted users are dropped.
- **Message size cap**: 16 KB inbound; oversized messages close with 1009.
- **Auth**: token sent via `{"type":"auth","token":"<jwt>"}` after `accept`;
  never from the query string (Phase 10 §10).

---

## Rate limiting

- Sliding-window, in-memory, per-category buckets.
- Categories: `general`, `login`, `register`, `export`, `ai`, `simulation`,
  `admin`, `ws`.
- Key cap: 10 000; coldest third pruned on overflow (bounded memory).
- **Limitation**: per-process only; for multi-worker production, replace with
  Redis (see `docs/SECURITY.md`).
- **CI note**: `RATE_LIMIT_ENABLED=false` in conftest and CI smoke; the live
  server has it on (login 20/min). Space smoke runs ≥60 s apart or expect
  429 → `KeyError` on the second run.

---

## Security scans (advisory)

| Scan | Status | Findings |
|------|--------|----------|
| `pip-audit -r requirements.txt` | advisory in CI | 0 known CVEs in production deps at time of writing |
| `npm audit --audit-level=critical` | advisory in CI | 0 critical; 2 moderate (react-router-dom) — accepted, see `docs/SECURITY_AUDIT.md` F-22 |
| `gitleaks` | advisory in CI | no secrets in tracked files |

---

## Not run / limitations

- **Docker builds** — no Docker daemon in this environment; Dockerfiles are
  committed but not built.
- **CI execution on GitHub Actions** — workflow file committed; not executed
  locally. Security scans are `continue-on-error` in CI.
- **GPU profiling** — not run (no discrete GPU; 3D scene runs on integrated
  graphics or software rendering).
- **Load testing (k6, locust, etc.)** — not run; benchmark is sequential
  single-client, not concurrent load.
- **Benchmark numbers are machine-dependent** — Windows dev machine, local
  SQLite, single uvicorn worker. CI/Linux numbers will differ.
