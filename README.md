# TwinSphere AI — Smart Campus Digital Twin & Simulation Platform

An AI-powered **digital twin of a university campus**: live simulated telemetry flows through a
sensor engine into a central twin state, out to risk / prediction / anomaly / optimisation engines,
and into an interactive 3D scene — where operators can run what--if drills (fire, crowd, power,
road, heat) and apply AI recommendations to drive the campus back to **SYSTEM NORMAL**.

> **Honesty note:** every value in this platform is produced by a deterministic simulation engine
> and is labelled **SIMULATED DATA**. The architecture is built so real IoT streams can replace the
> simulator without touching the AI, optimisation or visualisation layers.

---

## Architecture

```mermaid
flowchart LR
    subgraph Data
        S[Sensor Engine<br/>diurnal curves + drift]
        H[(SQLite / PostgreSQL<br/>readings · sims · audit)]
    end

    subgraph Core
        TS[TwinState<br/>buildings · zones · roads · routes]
        SIM[Simulation Engine<br/>fire · crowd · power · road · heat]
        RT[Runtime Loop<br/>sensor tick · sim tick · AI refresh]
    end

    subgraph AI["AI package (/ai)"]
        R[Risk engine]
        A[Anomaly detection<br/>z-score + IsolationForest]
        P[Prediction<br/>RandomForest + fallback]
        O[A* route optimiser]
        AN[Analyst<br/>LLM or local fallback]
        ACT[Actions<br/>apply recommendation]
    end

    subgraph API["FastAPI (/backend)"]
        REST[REST /api/*]
        WS[WebSocket /ws]
    end

    subgraph Frontend["React + Three.js/R3F"]
        CC[Command Center]
        TE[3D Twin Explorer]
        SC[Simulation Center]
        AI[AI Intelligence]
        AN2[Analytics · History · Settings]
        DEMO[Demo Mode]
    end

    S --> TS
    H --> TS
    SIM --> TS
    RT --> TS
    TS --> R & A & P & O & AN
    R & P & O --> ACT
    TS --> REST
    SIM --> WS
    RT --> WS
    REST --> Frontend
    WS --> Frontend
    ACT --> SIM
```

**Simulation lifecycle**

```mermaid
stateDiagram-v2
    [*] --> CREATED: create
    CREATED --> RUNNING: start
    PAUSED --> RUNNING: resume
    RUNNING --> PAUSED: pause
    RUNNING --> AWAITING_RECOVERY: duration elapsed
    AWAITING_RECOVERY --> RECOVERING: operator recovers
    RUNNING --> RECOVERING: operator recovers
    RECOVERING --> COMPLETED: 100% recovered
    CREATED --> CREATED: reset
    RUNNING --> CREATED: reset
    COMPLETED --> [*]
```

---

## Quick start (local development)

Prerequisites: **Node ≥ 18**, **Python 3.11+** (Docker optional).

### 1. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:PYTHONPATH = (Resolve-Path ..).Path          # repo root (PowerShell)
.venv\Scripts\uvicorn app.main:app --port 8000    # or: python -m uvicorn app.main:app --port 8000
```

First boot seeds the campus (6 buildings with campus codes, 15 floors, 29 zones, 40-road graph,
44 coded sensors, 24 h of SIMULATED history at 5-minute resolution), warms the AI engines and starts
the runtime loop. API docs: <http://localhost:8000/docs>.

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev           # http://localhost:5173  (proxies /api, /health, /ws → :8000)
```

### 3. Docker (alternative)

```bash
docker compose up --build        # frontend → http://localhost:3000, backend → :8000
# optional PostgreSQL:
DATABASE_URL=postgresql+psycopg2://twin:twin@postgres:5432/twinsphere \
  docker compose --profile postgres up --build
```

---

## Demo accounts

| Username | Password | Role | Capabilities |
|---|---|---|---|
| `admin` | `admin123` | ADMIN | read · simulate · analyze · manage · apply |
| `operator` | `operator123` | OPERATOR | read · simulate · apply |
| `analyst` | `analyst123` | ANALYST | read · analyze |
| `viewer` | `viewer123` | VIEWER | read |

Use the in-app **DEMO MODE** button for a scripted, guided presentation flow
(fire drill → risk rises → routes re-optimise → AI recommendation → apply → recover), with a
one-click reset between runs.

Phase 10: demo accounts and self-registration are **development conveniences** — both are
disabled automatically under `APP_ENV=production`, `/api/auth/demo` returns usernames only
(never passwords), and registration always creates a `VIEWER`.

---

## Feature map

| Route | What it does |
|---|---|
| `/` | Product overview + architecture diagram |
| `/login` | Role-based sign-in with one-click demo credentials |
| `/dashboard` | Command Center: live 3D campus, risk gauge, AI rail, metric strip, event ticker, **server-computed KPI strip with trends**, **system-health bottom bar**, **campus health score + What Changed?**, **replay mode (`?replay=<simId>`)** with transport controls + LIVE/REPLAY banner |
| `/twin` | 3D Twin Explorer: camera presets, layer toggles (**incl. Risk**), building/road/exit inspector, live tab (system status + event timeline), realtime sim controls, **RISK MODE** (buildings tinted by published risk), **routes tab + Routes & Evacuation panel** (Phase 7) |
| `/simulation` | 5 scenario cards, ignition-zone/intensity/wind controls, start/pause/resume/reset/recover, live metrics (people · risk · zones · temp · smoke · speed), results panel, speed chips, demo drill |
| `/ai` | Published (stabilised) campus risk, risk by building, predictions with honest confidence, anomalies with band/severity filters, AI events, **Operations Analyst with the Phase 8 structured brief** (severity · confidence meter · what-changed · route assessment · grounding evidence · recommendation decisions) + **analyst status pill**, mandatory AI-limitations disclaimer |
| `/analytics` | Full analytics workspace: 15M–30D + custom windows, building/zone/metric/incident/simulation filters (**URL-persisted**), server-side aggregation (risk bands, occupancy, energy, environment, sensor health, buildings, routes, AI, campus health, incidents, simulations), building compare, **CSV export** |
| `/history` | Historical intelligence: **Incidents \| Simulations tabs** with server-side pagination/filters (URL-persisted), incident detail drawer (timeline · metrics · **report** · CSV export), simulation detail (metrics · events · linked incidents), **two-run compare**, **Replay button → `/dashboard?replay=<simId>`** |
| `/settings` | Clock speed, sensor tick, system health, display defaults, **change password**, demo reset |
| `/admin/users` | Phase 10 — Administration: user table (search · role filter), create user, role change, enable/disable, one-time password reset (ADMIN) |
| `/admin/audit` | Phase 10 — Audit log: action/outcome/date filters, scope badge (FULL admin / OPERATIONAL operator), request-id correlation |

**Scenarios:** Fire Emergency (330 s + 130 s recovery) · Crowd Surge · Power Failure · Road Closure ·
Extreme Temperature — each with distinct physics, incidents, recommendations and recovery behaviour.

---

## API surface (summary)

```
GET  /health                      service + DB status
POST /api/auth/login              Phase 10: JWT + role (rate-limited · audited · generic 401)
POST /api/auth/register           public self-registration → always VIEWER (gated)
POST /api/auth/logout             revoke presented jti · GET /api/auth/me → profile
POST /api/auth/change-password    Argon2id policy check → bumps token_version
GET  /api/auth/demo               demo usernames+roles only (dev; disabled in production)
GET  /api/auth/roles              role → permission map
GET/POST /api/users               ADMIN: list (?q&role&is_active&page) · create (role whitelist)
PATCH /api/users/{id}             ADMIN: role change · enable/disable (self-protection rules)
POST /api/users/{id}/reset-password  ADMIN: one-time generated password (returned once)
GET  /api/audit · /api/audit/actions  audit query (q/action/outcome/date · audit permission;
                                   auth.*/authz.*/admin.* hidden without manage)
GET  /api/campus                  twin snapshot + metadata · summary · data_source=SIMULATED
GET  /api/buildings?type=&status= building list (codes · descriptions · coordinates)
GET  /api/buildings/{id|code}     building detail (zones · sensors · exits · routes · predictions)
GET  /api/buildings/{id|code}/floors   floors of a building (accepts id or code, e.g. ENG-B)
GET  /api/floors?building_id=     all floors · GET /api/floors/{id} → floor + zones
GET  /api/zones?building_id&floor_id&floor&zone_type&risk_level
GET  /api/zones/{id}              zone detail (404 on unknown id)
GET  /api/sensors?type&building_id&zone_id&status
GET  /api/sensors/{id|code}       sensor detail (accepts id or sensor_code, e.g. ENG-B-TEMP-01)
GET  /api/sensors/{id}/history?limit&start&end   readings (source=SIMULATED · quality=GOOD)
GET  /api/risk · /api/risk/{entity_id}          campus + per-entity risk (404 on unknown)
                                                → + published (stabilised) · hierarchy · risk_history
GET  /api/routes?recompute=       A* evacuation routes
GET  /api/predictions             stored predictions (entity_type · prediction_time)
GET  /api/incidents?status= · /api/incidents/{id}   incidents (incident_code · location_*)
GET  /api/ai/{predictions,anomalies,events,status,analyst}
                                Phase 5: anomalies (severity · building_id · metric · start · end)
                                  · /api/ai/anomalies/{id} (404 on unknown)
                                  · predictions (?horizon_min&entity_id&metric) 
                                  · /api/ai/predictions/{entity_id}
                                  · bounded AI event timeline · engine health
POST /api/ai/analyze              analyst run (role: analyze) → structured AnalystResult;
                                  body {"question"?, "mode"?} with mode ∈ CAMPUS|
                                  INCIDENT|BUILDING|ROUTE|SIMULATION|RECOVERY
                                  (400 on unknown) · question answered from structured data
GET  /api/ai/analysis             Phase 8: persisted history (?limit&mode&severity, newest first)
GET  /api/ai/analysis/latest · /api/ai/analysis/{id}   latest (state or DB) · detail (404 on unknown)
GET  /api/ai/recommendations      Phase 8: analyst recommendation cards (?status&analysis_id)
GET  /api/ai/recommendations/{id} one card (404 on unknown)
POST /api/ai/recommendations/{id}/decision   human-in-the-loop ACCEPTED|DISMISSED
                                  (role apply · 409 when already decided · 422 on bad enum)
GET  /api/ai/evidence/{id}        Phase 8: one grounding evidence item (analysis-scoped id)
POST /api/simulations             create drill → /{id}/{start,pause,resume,reset,recover}
                                  Phase 6: validation → 400 · single active → 409 ·
                                  GET /api/simulations/{id} (active or history) ·
                                  GET /api/simulations/{id}/results (live or stored §48 block)
POST /api/recommendations/{id}/apply   apply recommendation (role: apply)
GET  /api/analytics/timeseries?range=1H|6H|24H|7D|30D
GET /api/demo/script · POST /api/demo/reset
GET  /api/realtime/status          simulator status (status · speed · clock · clients · seed)
POST /api/realtime/{start,pause,resume,reset}   controls (role: simulate · audited · idempotent)
POST /api/realtime/speed           body {"speed": 1|2|5|10} → else 400
WS   /ws                          state · simulation · event · analyst + typed live events
                                   (sensor.batch_update · occupancy.update · building.update ·
                                    simulation.status · system.status — envelope v1)
                                    Phase 5: ai.anomaly · ai.prediction · risk.update
                                    (published campus/buildings — envelope v1)
                                    Phase 6: simulation.created/started/paused/resumed/reset/
                                    recovery_started/recovery_progress/recovered/completed ·
                                    simulation.tick (1 Hz) · simulation.zone_update (diff) ·
                                    simulation.risk_update — envelope v1
                                    Phase 7: route.calculated/updated/invalidated/
                                    recalculated · emergency_route.updated ·
                                    evacuation.started/updated/completed ·
                                    bottleneck.detected/cleared — envelope v1
                                    Phase 8: analyst.analysis_started/
                                    analysis_completed/analysis_updated ·
                                    recommendation_created · alert_created —
                                    envelope v1 (no context_summary)
GET  /api/routes/graph             Phase 7: route graph (35 nodes · 40 edges · live risk)
POST /api/routes/calculate         point-to-point plan (role apply) → 400 on bad mode/node
POST /api/routes/recalculate       force revalidation of the active plan
GET  /api/routes/alternatives      recommended + alternatives + cross-mode comparison
GET  /api/routes/evacuation        campus plan: buildings · exits · bottlenecks
GET  /api/evacuation/status        overview + active plan + live route history
GET  /api/evacuation/building/{id} per-building plan with exit roles (activates plan)
GET  /api/routes/emergency · /api/emergency-response/routes
                                   emergency vehicle route(s) (?vehicle=&origin=&destination=)
GET  /api/routes/bottlenecks       structured capacity bottlenecks
GET  /api/routes/history?limit=    persisted route_events audit (survives resets)
GET  /api/routes/{route_id}        active plan first, then persisted row + events
GET  /api/analytics/overview|risk|occupancy|energy|environment|sensors
                                   Phase 9: window aggregates (?range=15M|1H|6H|24H|7D|30D
                                   |CUSTOM&start=&end= · building_id on risk/occupancy/
                                   energy/environment) → KPI trends · risk bands · series
GET  /api/analytics/buildings · /buildings/{id} · /buildings/compare?ids=
                                   building rows · per-building detail (risk+occupancy+
                                   environment+incidents+sensors) · 2–3 building compare
GET  /api/analytics/sensors/{id}   sensor health detail (series · stats · trend)
GET  /api/analytics/routes · /ai · /system · /health · /what-changed?ago=
                                   route/AI aggregates · system components · campus health
                                   score · what changed since N minutes ago (honest
                                   unavailable reasons — never fabricated)
GET  /api/analytics/export?kind=&range=&start=&end=&format=   CSV download
GET  /api/history/incidents?status=&severity=&kind=&q=&page=  paginated incidents
GET  /api/history/incidents/{id} · /report · /export?format=  detail · report · CSV
GET  /api/history/simulations?scenario=&status=&q=&page=      paginated simulations
GET  /api/history/simulations/{id} · /events · /compare?a=&b= detail · events · 2-run diff
GET  /api/history/simulations/{id}/replay · /frame?t=         Phase 9: replay payload
                                   (frames · events · risk series · route/AI/incident
                                   context · speeds) + single deterministic frame
GET  /api/history/export?kind=     history CSV (incidents | simulations)
```

---

## Phase 2 — Campus Data Layer

The data foundation every later phase builds on: a seeded, queryable campus model served by REST.

### Campus entities

| Table | Purpose | Key Phase 2 fields |
|---|---|---|
| `buildings` | 6 campus structures | `code` (`ADMIN-A`, `ENG-B`, `CS-C`, `LIB-D`, `CAN-E`, `CLI-F`), `description`, `latitude`/`longitude`, `position_y`, indexed `status` |
| `floors` | **new table** — one row per storey (15 total) | `id = {CODE}-F{n}` (e.g. `ENG-B-F1`), `floor_number` (1-based), `zone_count`, `area_sqm`, `is_evacuation_level` |
| `zones` | 29 rooms/spaces | `floor_id` link, `zone_type`, `risk_level`, `width`/`depth`/`height` |
| `roads` · `road_nodes` | 40-road / 35-node graph | existing topology (A* input) |
| `sensors` | 44 devices | `sensor_code` (e.g. `ENG-B-TEMP-01`, `ENG-B-HUM-02`, …, `CAMPUS-TRF-01`), `zone_id`, `status`, `normal_min`/`normal_max`, `min_value`/`max_value`, installation `x/y/z` |
| `sensor_readings` | 24 h of history (288 pts/sensor @ 5 min) | `source=SIMULATED`, `quality=GOOD`, composite time index |
| `incidents` | incident register | `incident_code` (`INC-0001`…), `location_type`/`location_id`, indexed `status` |
| `simulations` | drill records | `simulation_code` (`SIM-0001`…), `target_type`, `simulation_speed`, `current_step`/`total_steps` |
| `evacuation_routes` | persisted A* routes | Phase 1 table (route_nodes ↔ `node_path`, estimated time ↔ `eta_s`) |
| `risk_scores` · `predictions` · `recommendations` · `system_alerts` · `audit_logs` | AI + ops records | `entity_type`, `incident_id`/`estimated_impact`, `severity`/`type`/`is_active`, `user_id`/`ip_address` |

**ID conventions** — internal IDs (`eng`) stay stable for Phase 1 consumers; every building also
carries a human campus `code` (`ENG-B`) and **both resolve** in `/api/buildings/{id}`,
`/api/buildings/{id}/floors` and `/api/floors` filters (case-insensitive). Sensors resolve by id
(`temperature_eng`) or `sensor_code` (`ENG-B-TEMP-01`). All seeded telemetry is labelled
`source: SIMULATED` / `data_source: SIMULATED`.

### Seed data

```powershell
cd backend
$env:PYTHONPATH = (Resolve-Path ..).Path
.venv\Scripts\python -m app.services.seed            # init schema + seed if empty + print stats
.venv\Scripts\python -m app.services.seed --stats    # print statistics only
.venv\Scripts\python -m app.services.seed --reset    # drop everything and reseed
# → Seed data loaded. Users: 4, Buildings: 6, Floors: 15, Zones: 29, Road nodes: 35,
#   Roads: 40, Sensors: 44, Sensor readings: 12672, Incidents: 3, Simulations: 4, …
```

Seeding is idempotent: users/demo incidents/simulation history are written once, while the
**static campus model** (buildings → floors → zones → graph → sensors) is re-synced on every run,
and legacy pre-Phase 2 rows get backfilled codes/locations.

### Migrations

Alembic is configured (`backend/alembic/`, revision `b3937b6fe73a`) with the URL taken from
`DATABASE_URL` / `.env`:

```powershell
.venv\Scripts\python -m alembic upgrade head      # fresh database → full schema
.venv\Scripts\python -m alembic revision --autogenerate -m "change"
.venv\Scripts\python -m alembic stamp head        # existing DB created before Alembic
```

For developer convenience the app also runs an **additive schema sync at startup**
(`ensure_schema()`): missing tables/columns/indexes are created, never dropped — so a Phase 1
database upgrades in place on next boot. Production flows should use `alembic upgrade head`.

### Phase 2 APIs (examples)

```bash
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/buildings/ENG-B          # by code
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/buildings/ENG-B/floors   # F1..F4
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/floors/ENG-B-F1          # floor + zones
curl -H "Authorization: Bearer $TOKEN" "localhost:8000/api/zones?building_id=ENG-B&zone_type=LAB"
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/zones/does-not-exist     # 404 + message
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/sensors/ENG-B-TEMP-01    # by sensor_code
curl -H "Authorization: Bearer $TOKEN" "localhost:8000/api/sensors/ENG-B-TEMP-01/history?limit=5&start=2026-01-01T00:00:00Z"
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/predictions              # stored predictions
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/incidents/inc_seed_1     # incident_code lookup
```

Responses follow the platform's Phase 1 JSON conventions (raw resource objects, no envelope);
spec-style field names are exposed alongside existing ones (`zone_type` ≡ `kind`,
`parameters` ≡ `params`, `results` ≡ `result`, `reason` ≡ `rationale`, `last_reading` ≡ live value).

### Phase 2 tests

```powershell
.venv\Scripts\python -m pytest tests -q           # includes tests/test_phase2_campus_data.py
.venv\Scripts\python tests\smoke_api.py           # 59 live checks incl. floors/codes/SIMULATED labels
```

Covers: seed statistics · building/floor/zone/sensor lookups by id **and** code · filters
(type/status/building_id/floor_id/zone_type/risk_level/zone_id/status) · 404s for invalid ids ·
ISO-8601 history windows · `source=SIMULATED` labelling · stored predictions · incident codes ·
campus summary.

---

## Phase 3 — Interactive 3D Digital Twin

The `/twin` page turns the Phase 1 scene and Phase 2 campus data into an interactive,
honest digital twin: every panel reads real API data, simulated telemetry is always labelled
`SIMULATED`, and connectivity is never faked. **Frontend-only** — no backend changes.

### What the twin shows

| Area | Details |
|---|---|
| Viewport | `CampusScene` (React Three Fiber): damped camera rig, buildings with per-type architecture, real zone volumes, floor highlight band (`Ground`/`Level N`), sensor markers + tooltips, active-incident markers, roads/gates with blocked closures, labels, crowd dots, evac routes, heatmap, night mode |
| Left rail | building search + list (risk · occupancy · temperature), roads/exits tabs, campus legend (risk ladder · 9 sensor colors · status · SIMULATED note) |
| Toolbar | view modes **Overview / Buildings / Sensors / Zones** (each applies a layer preset) + camera commands **Reset / Top / Focus** |
| Layers panel | 12 layer checkboxes, scene extras (grid · crowd · evac routes · heatmap · night) and a sensor-type filter (all 9 types) |
| Inspectors | campus overview → **building inspector** (spec §18/§49 stats, real floor selector from `/buildings/{id}/floors`, zones list, clickable sensor chips) → **sensor inspector** (live value · normal range · 24 h history chart from `/sensors/{id}/history` · source label) |
| Status bar | `DIGITAL TWIN` + connection truth, data source, building/zone/sensor/active-incident counts, last update time |

### Data flow

- WS `state` frames are the primary live feed; `useTwinStore` **merges** campus-only keys
  (`summary`, `data_source`, `metadata`, `route_report`) that `GET /api/campus` adds but
  `state.snapshot()` omits, so live pushes never drop them.
- `useCampus` falls back to REST `/api/zones` + `/api/sensors` (15 s) whenever the link is down
  or zones/sensors are still missing, and refreshes the campus summary every 60 s.
- Selection model (spec §32): building → floor → sensor with explicit clearing rules; floors
  scope the zone/sensor lists in the inspector and the highlight in the scene.
- Loading/error are first-class: staged `INITIALIZING DIGITAL TWIN` loader and an explicit
  `DIGITAL TWIN CONNECTION ERROR` + Retry panel (`—` instead of invented values everywhere).

### Phase 3 tests

```powershell
cd frontend
npm run test                              # vitest (24): utils · store · page
npm run typecheck && npm run build
```

Covers: geo↔world round-trip · floor labels · view-mode layer presets · layer & sensor-filter
toggles · building→floor→sensor selection rules · WS merge keeping campus-only keys · page
states (loader / error + retry / ready shell) · layer & view-mode interactions · building
inspector with derived floor chips · sensor drill-through with the 24 h chart.

---

## Phase 4 — Real-Time Simulation & Live Digital Twin

The campus becomes a genuinely *live* twin: a backend simulation engine streams typed
WebSocket events every tick, operators control the simulation in real time, and the
`/twin` UI surfaces it all — always labelled `SIMULATED`, never inventing values.

### Simulation engine

| Piece | Behaviour |
|---|---|
| `SimulationContext` | pure per-tick context (no RNG): active scenario modifiers — `occupancy_multiplier`/`occupancy_delta`, `temperature_offset` (+9 °C) & `energy_multiplier` (×1.35) scoped to `{target}, eng, cs, lib`, `blocked_roads`, `blocked_zones` |
| Runtime gating | loop advances the clock + ticks only while status is `RUNNING`; `PAUSED` freezes accumulators and broadcasts a state heartbeat; `STOPPED` at boot when `SIMULATION_ENABLED=false`; `reset` restores the 10:00 baseline and sets `PAUSED` |
| Persistence | telemetry batched every `SIMULATION_PERSIST_INTERVAL` (default 20 s → 10 ticks) instead of every tick |
| Seed | `SIMULATION_SEED` (optional) > `RANDOM_SEED` — exposed in `/api/realtime/status` |

### Realtime controls (`simulate` role: ADMIN/OPERATOR)

```powershell
GET  /api/realtime/status   # status · speed · clock · last_tick · clients · data_source
POST /api/realtime/pause    # idempotent — pausing while paused returns 200, clock frozen
POST /api/realtime/resume   # 400 when status is STOPPED
POST /api/realtime/start    # STOPPED → RUNNING
POST /api/realtime/reset    # clock → 10:00, telemetry baseline, status PAUSED, audited
POST /api/realtime/speed    # {"speed": 5} — only 1x/2x/5x/10x accepted, else 400
```

Every mutation is audited and broadcasts `simulation.status` + `system.status` to all
connected clients. VIEWER/ANALYST get 403 on mutations (GET stays open).

### WebSocket live events (envelope v1)

Each sensor tick emits, in order: `sensor.batch_update` (changed sensors only) →
`occupancy.update` → `building.update` → `simulation.status` → `system.status`, then the
legacy `state` frame — all with `event_version: 1`, `timestamp`, `source: "SIMULATED"` and
`data` (aliased as `payload` for older consumers). Client pings every 4 s keep the uplink
honest; silence > 6 s flips the badge to `DEGRADED`.

### Live UI (`/twin`)

- **SimControlPanel** — start/pause/resume/reset + 1x/2x/5x/10x, status pill, sim clock,
  `SIMULATED` source; disabled for read-only roles or when the simulator is off.
- **Status bar** — pulsing **LIVE** badge while streaming + `Sim RUNNING · 10:30 · 2x`.
- **Live rail tab** — `SystemStatus` (backend/database/websocket/simulator/AI, clients,
  risk, incidents from `system.status`) + `LiveEvents` (bounded timeline of controls,
  status flips, risk changes and system outages actually observed by the session).
- **Honest live data** — CampusOverview trend arrows need ≥5 samples (else `—`),
  BuildingInspector occupancy/status/risk stream from `building.update`, SensorInspector
  shows a bounded (120-point) live chart above the 24 h history, sensor markers keep
  static geometry cached (a telemetry tick rewrites only what changed).

### Phase 4 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 53 passed (incl. 16 realtime tests)
.venv\Scripts\python tests\ws_check.py                  # 18/18 (typed events + envelopes + ping)
.venv\Scripts\python tests\smoke_api.py                 # 59 checks (server must be running)

cd frontend
npm run test                                             # vitest → 47 passed
```

---

## Phase 5 — AI Anomaly Detection, Prediction & Risk Intelligence

Local, deterministic AI turns the live telemetry into **anomaly detection, honest
forecasts and a stabilised risk index** — with the caveat always on screen: scores are
weighted indicators, predictions are statistical estimates, neither is a guarantee.

### Layered anomaly engine (`ai/anomaly/`)

| Layer | Rule |
|---|---|
| L1 threshold | any depth with ≥6 samples → immediate (skip L1 for `energy`, wide natural variance) |
| L2 rolling z-score | ≥6 samples; production `z_threshold=4.0`, score = \|z\| × 15 |
| L3 time-of-day baseline | per entity/metric/hour EWMA (`n ≥ 8`); survives the rolling window so persistence is satisfiable |
| L4 isolation forest | optional multivariate check (skippable for deterministic tests) |
| Raise | threshold fires immediately; statistical score ≥ 75 fires immediately; else 2 consecutive observations |
| Release | score decays −18/cycle, drops out below 25; tracker capped at 50 entities |
| Bands | NORMAL 0–20 · LOW 21–40 · MODERATE 41–60 · HIGH 61–80 · CRITICAL 81–100 |

Cold start is honest: fewer than 6 samples → `INSUFFICIENT_DATA`, never a fake score.

### Prediction models (`ai/prediction/`)

- ≥100 samples → scikit-learn RandomForest (`occupancy-rf-v1` / `energy-rf-v1`, joblib to
  `ai/models/`, 80/20 chronological split, retrain every 600 s or +20 samples).
- 6–99 samples → deterministic baseline (confidence clamped 0.30–0.85).
- <6 samples → `insufficient_data` / `INSUFFICIENT_DATA` — **confidence withheld**, not invented.
- Metrics are honest: `r2 = null` when variance ≈ 0, `mape = null` when the truth mean ≈ 0;
  RF confidence clamped 0.30–0.95 and dropped to `LOW_CONFIDENCE` when `r2 < 0.3`.
- `GET /api/ai/predictions?horizon_min=30` (default horizons 15/30/60).

### Risk engine (`ai/risk/`)

- Building factors (occupancy · smoke · fire · temperature · blocked exits · air quality ·
  anomaly · power · status) → campus blend (worst 0.65 + mean 0.35 + blocked roads +
  incidents + outdoor temperature).
- **Raw risk stays raw** (`state.risk` — Phase 1 physics/tests unchanged); a separate
  *published* view is stabilised by `RiskStability` (asymmetric EMA: rise 0.55, jumps ≥25
  → 1.0, decay 0.35; publish upgrade ≥ `min_delta`, downgrade ≥ 2.5 × `min_delta`) so the
  UI never flickers between levels.
- Hierarchy refresh (campus → building → floor → zone → sensor with weights + explanations)
  happens once per AI cycle and ships as `hierarchy` on `/api/risk`.

### AI scheduler + WebSocket events

Runs only while the simulation is `RUNNING`, every `AI_ANALYSIS_INTERVAL_SECONDS` (15 s);
failures mark the engine degraded without ever affecting the simulator, WS or REST.

```powershell
WS ai.anomaly     {anomalies, count, new, data_quality, sensor_status, clock}
WS ai.prediction  {predictions, count, horizons, clock}
WS risk.update    {campus, buildings, raw_level, clock}   # campus/buildings = published
```

All three reuse the Phase 4 envelope (`event_version`/`timestamp`/`source`).

### API

```powershell
GET /api/ai/anomalies?severity&building_id&metric&start&end&limit
GET /api/ai/anomalies/{anomaly_id}          # 404 on unknown
GET /api/ai/predictions?horizon_min&entity_id&metric&limit
GET /api/ai/predictions/{entity_id}
GET /api/ai/events?limit                    # bounded AI timeline (40)
GET /api/ai/status                          # engines · horizons · degraded
GET /api/risk · /api/risk/{entity_id}       # + published · hierarchy · risk_history
```

### Frontend

- **AI Intelligence (`/ai`)** — published campus risk (raw → published delta, trend,
  risk-history sparkline), risk by building, prediction cards (horizon tabs, confidence
  bar with `confidence_label`, MAE/RMSE/R²/n), AI events, anomaly list with
  severity/building filters and band chips, sensor-status counts, Operations Analyst,
  and the **mandatory AI-limitations disclaimer**. Polls `refreshAi()` every 20 s; a dead
  AI status endpoint shows `AI DEGRADED` instead of a stale badge.
- **RISK MODE** — `Risk` view mode / layer chip tints buildings toward their published
  band (LOW green → CRITICAL deep red, subtle blend + outline + score chip) and gives
  flagged sensors a pulsing `!` badge with band colour — colour is never the only signal.
- **Dashboard** — AI strip (AI Risk smoothed · Active Anomalies · Next Forecast · AI
  Sensor Flags · AI Health) and both risk gauges now prefer the published score.
- **Inspectors** — SensorInspector gained an **AI Status** block (band, score, detector,
  samples vs minimum, "confidence withheld" when cold); BuildingInspector gained a
  **Risk — Published** block (smoothed vs raw, trend, top factors).

### Phase 5 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 87 passed (53 legacy + 34 Phase 5)
.venv\Scripts\python tests\smoke_api.py                 # 84/84 (server must be running)
.venv\Scripts\python tests\ws_check.py                  # 25/25 (+ ai.anomaly/prediction/risk.update)

cd frontend
npm run test                                             # vitest → 64 passed (47 legacy + 17 Phase 5)
```

---

## Phase 6 — Emergency What-If Simulation Engine

Deepens the Phase 2 drill engine into a full **what-if system**: the flagship 🔥 Fire
scenario (ignition → spread → evacuation → recovery) plus Crowd / Power / Road /
Temperature share one deterministic emergency engine with sensor feedback, gradual
recovery, an honest results block and typed `simulation.*` WebSocket telemetry.

### Engine (`ai/simulation/` — pure, deterministic, no I/O)

| Module | Rules |
|---|---|
| `propagation.py` | zone-graph fire spread (`ignite`/`step_fire`/`suppress`) with wind bias (8 directions + NONE), smoke diffusion/decay, `zone_totals` (raw + severity-weighted people: FIRE 1.0 · SMOKE 0.6 · AFFECTED 0.3) |
| `fire_simulation.py` | intensity **1–5 labels** LOW…EXTREME (engine still accepts legacy 1–10), wind validation, smoke severity 0–100 → CLEAR/LIGHT/MODERATE/HEAVY/CRITICAL, building status ladder **NORMAL → ALERT → DANGER → CRITICAL** from live fire state |
| `crowd_simulation.py` | density curve + occupancy multiplier ramp toward the surge |
| `power_failure_simulation.py` | service drops, backup-generator pickup, status chain |
| `road_closure_simulation.py` | block / reopen + congestion impact on routes |
| `extreme_temperature_simulation.py` | campus heat event payload |
| `recovery_engine.py` | exponential glide (`RECOVERY_TAU=22`) — recovery is **gradual, never teleports** |

### Live simulation state (§46)

`active_sim` now streams `weighted_people`, `affected_zones`, `max_people_at_risk`,
`peak_temperature`, `peak_smoke` and (on `simulation.tick`) flat `risk`, `risk_level`,
`speed`, `building_smoke`, `building_temperature`, `building_status` extras. Peaks take
the max of zone-model and sensor readings; the sensor engine adds fire→building heat
coupling on top of the existing smoke/AQ coupling. Fire ignition sets the target
building to `ALERT` and the ladder escalates from live state (recovery walks it back to
`OPERATIONAL`).

### Results (§48)

Completion computes an honest block from the actual run — `peak_risk` (+severity level),
`peak_people_at_risk`, `weighted_people_at_risk`, `affected_zone_count`,
`peak_temperature`, `peak_smoke` (+band), `duration_s`, `recovery_time_s`, `events`,
`intensity` (+label), `wind` — stored on the simulation row and served live or from
history by `GET /api/simulations/{id}/results`.

### WebSocket events (§27–§28)

```powershell
WS simulation.created/started/paused/resumed/reset/recovery_started/completed/recovered
WS simulation.recovery_progress   {recovery_progress, ...sim}
WS simulation.tick                1 Hz sim snapshot + risk/speed/building extras
WS simulation.zone_update         changed zone statuses only (diffed)
WS simulation.risk_update         campus + target-building score/level
```

Typed events are queued by the (sync) engine (`queue_sim_event`) and flushed by the
runtime loop through `manager.emit` — legacy `state`/`simulation`/`event` broadcasts
still flow alongside. A failing simulation tick degrades only the `simulation` health
flag; twin, sensors, AI and the socket keep running (failure isolation).

### Frontend (§55–§59)

- **Simulation Center** — ignition-zone selector, intensity slider with 1–5 labels,
  9-way wind compass, live metrics (people, risk, affected zones, peak temp, building
  smoke, speed), speed chips (0.5/1/2/4×), results panel (live + history drill-down),
  SIMULATED DATA badge and demo-drill launcher.
- **SIMULATION ACTIVE banner** (AppShell) — red while RUNNING with scenario/target/
  elapsed/people-at-risk, amber while PAUSED, blue recovery strip kept for RECOVERING.
- **3D hazard visuals** — burning/smoky/affected zones tint red/orange/amber with a
  pulsing hazard ring and stay visible even when the zones layer is off; FOCUS INCIDENT
  button on the Twin Explorer rails the camera to the incident building and selects it.
- Store handles every `simulation.*` event (tick merge, zone diffs, risk updates,
  lifecycle toasts + history refresh on completion).

### Phase 6 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 106 passed (87 + 19 Phase 6)
.venv\Scripts\python tests\smoke_api.py                 # 107/107 (server must be running)
.venv\Scripts\python tests\ws_check.py                  # 39/39 (+ simulation.* events)

cd frontend
npm run test                                            # vitest → 69 passed (64 + 5 Phase 6)
```

---

## Phase 7 — Route & Evacuation Optimization

Production route engine over the Phase 2 road graph: **five weight-per-mode
A\*/Dijkstra routes**, campus + per-building evacuation plans, emergency
vehicle response, dynamic invalidation with automatic re-routing,
exit-capacity bottlenecks, a persisted route audit and a full
Routes & Evacuation panel in the twin. Pure structured computation — no LLM
anywhere in this path.

### Engine (`ai/optimization/` — pure, deterministic, no I/O)

| Module | Rules |
|---|---|
| `graph.py` | cached topology (35 nodes · 40 edges) + dynamic refresh: congestion, blocked edges, edge risk = `max(road risk, endpoint risk)` |
| `route_cost.py` | `w_d·dist/100 + w_t·time/60 + w_r·risk/100 + w_c·congestion + w_cap·capacity overload`; 5 mode weight tables (`shortest/fastest/safest/balanced/emergency`) |
| `astar.py` | A\* with admissible euclidean heuristic × mode distance weight (weight 0 → Dijkstra) |
| `dijkstra.py` | ground-truth reference used by tests/audit |
| `congestion.py` | exit pressure (`demand/capacity`), edge overload, corridor heuristics → structured bottlenecks (EXIT/EDGE/NODE · LOW/MEDIUM/HIGH) |
| `evacuation.py` | building plans (exit roles, queue time, safety ladder) + campus plan (status `IDLE→STANDBY→ACTIVE→CRITICAL`) |
| `emergency_vehicle.py` | fire truck / ambulance / security profiles (speed, access rules, gates) |
| `optimizer.py` | classification (`RECOMMENDED/ALTERNATIVE/NOT_RECOMMENDED/BLOCKED`), validity rules, cross-mode comparison |

Calibration: `REF_DIST=100` · `REF_TIME=60` · `EDGE_CAPACITY_BASE=200 ppm` ·
`EXIT_FLOW_PER_CAPACITY=312.5 ppm` · `WALK_SPEED=1.35` · `VEHICLE_SPEED=8.3`
(full model in `docs/ROUTING.md`).

### Live risk → routes

`risk_engine` now propagates building risk onto exit nodes (×0.85 decay/cycle)
and touching roads, so `safest`/`balanced` react to real conditions: during a
fire the eng escapes report `HIGH_RISK`/`NOT_RECOMMENDED` with exit risk 100,
while `safest` chooses a longer, lower-risk path than `shortest` on clean
state (186 m/risk 1.7 vs 132 m/risk 2.4). Hard sim reset clears node/road
risk with the hazard.

### Dynamic re-routing (§10/§26/§32)

Every runtime tick validates the active plan: `edge_blocked`,
`risk_increased` (Δ ≥ 25), `exit_unavailable` (node risk ≥ 75) and
`destination_unavailable` invalidate → `route.invalidated` + auto-recalc
(`route.recalculated`). ACTIVE/CRITICAL evacuation with no plan auto-activates
a building plan. Improvement adoption is gated (`Δrisk ≥ 10` or `time ≤ 0.85×`)
so plans never churn for noise.

### API + WebSocket

See the API surface block above — `/api/routes/*`, `/api/evacuation/*` and
`/api/emergency-response/routes` (12 endpoints) plus the typed
`route.*` / `evacuation.*` / `bottleneck.*` WS family. Legacy `GET /api/routes`
is untouched. `route_events` audit (migration `p7c4e8b2d9f1a`) survives resets;
`route_history_recent` is the live session slice.

### Frontend (§41–§42)

- **Routes tab + RoutePanel** — evacuation strip, calculator (exits vs gates,
  4 mode chips), active plan with distance/ETA/risk/congestion, recalculation,
  cross-mode comparison table, per-building plans with exit roles, bottlenecks,
  emergency dispatch, history and colour legend.
- **3D** — animated chevron arrows on the active route, origin/destination
  markers, dashed emergency-vehicle lines, bottleneck pulse rings.
- **Dashboard** — `Evac Plan` metric tile (status tone, people at risk, plan
  mode/version) opens the twin with the panel; Demo Mode step 9 does the same.

### Phase 7 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 130 passed (106 + 24 Phase 7)
.venv\Scripts\python tests\smoke_api.py                 # all pass (~128; 3 conditional checks) — server must be running
.venv\Scripts\python tests\ws_check.py                  # 43/43 (+ route.* events)

cd frontend
npm run test                                            # vitest → 90 passed (69 + 21 Phase 7)
```

---

## Phase 8 — AI Analyst & Decision Support

Evidence-grounded, provider-agnostic analyst over the existing Phase 1–7 engines.
The **deterministic pipeline computes everything that matters** (evidence,
confidence, severity, priority, route assessment, affected areas, what changed,
recommendations); an optional LLM only rephrases the narrative and is validated
against the structured context before it is ever shown. With no `LLM_API_KEY`
the platform runs the local fallback analyst end-to-end — no blank screens, no
blocked simulation loop, no hallucinated numbers.

```mermaid
flowchart LR
    ST[Campus state<br/>risk · sim · routes ·<br/>evacuation · predictions] --> CTX[build_context<br/>normalized + signature]
    CTX --> CACHE{signature<br/>cache hit?}
    CACHE -->|hit + not forced| DONE[Return cached result]
    CACHE -->|miss| COOL{cooldown<br/>15s / 5s critical?}
    COOL -->|blocked| PREV[Re-serve previous analysis]
    COOL -->|pass| PIPE[Deterministic pipeline]
    PIPE --> EV[evidence.py<br/>grounded facts]
    EV --> CONF[confidence.py<br/>6 weighted components]
    EV --> REC[recommendations.py<br/>ranked, evidence-linked]
    PIPE --> LLM{LLM configured?}
    LLM -->|no / error / timeout /<br/>failed validation| FALL[fallback.py narrative]
    LLM -->|yes| PROV[providers.LLMProvider<br/>timeout 12s · JSON only]
    PROV --> VAL[semantic_validate<br/>entity + number grounding]
    VAL -->|reject| FALL
    VAL -->|ok| MERGE[Merge: system-owned fields<br/>+ LLM prose]
    FALL --> RES[AnalystResult<br/>Pydantic schema]
    MERGE --> RES
    RES --> BOOK[cache · cooldown · health<br/>WS analyst.* events<br/>ai_analyses/ai_recommendations/ai_evidence<br/>FE brief · evidence · decisions]
```

### Engine (`ai/analyst/` — pure, deterministic core; provider-agnostic I/O)

| Module | Rules |
|---|---|
| `schemas.py` | `AnalystResult` + `Situation`/`Confidence`/`EvidenceItem`/`Recommendation`/`ChangeItem`… — strict Pydantic, enum-validated (severity ladder, source kinds, modes) |
| `context.py` | normalized context from state (`MODES`: INCIDENT/CAMPUS/BUILDING/ROUTE/SIMULATION/RECOVERY, auto-detected) + `context_signature` (md5) that drives the cache |
| `evidence.py` | grounded evidence items (`ev_N` → analysis-scoped `anl_…:ev_N`) from risk, anomalies, predictions, people, routes, evacuation, simulation, congestion |
| `confidence.py` | 6 weighted components (sensor availability .22 · freshness .20 · route certainty .18 · prediction confidence .15 · anomaly agreement .13 · simulation consistency .12) → overall clamped 0.05–0.95 + level + honest notes |
| `recommendations.py` | deterministic ranking (priority 1..n) with `evidence_ids` linking every card back to facts |
| `fallback.py` | local narrative, severity/priority ladder, legacy Phase 5 fields, question answering from structured data, change detection |
| `prompts.py` | system + user prompt build and strict JSON parsing of the LLM reply |
| `providers.py` | `DeterministicProvider` (always available) · `LLMProvider` (httpx, `LLM_TIMEOUT=12s`, `LLM_MAX_TOKENS=900`) · `semantic_validate` rejects ungrounded entities/numbers → automatic fallback |
| `analyst.py` | `run_analysis()` orchestrator: evidence → confidence → recommendations → provider → validated `AnalystResult`, `what_changed_for()` (risk/route/simulation/evacuation/people change), `route_assessment_for()` |

### Triggers, cache & health (`backend/app/services/analyst_service.py`)

- **Signature cache** — unchanged context (md5) reuses the last analysis (20 entries);
  `POST /api/ai/analyze` always forces a fresh run.
- **Cooldown** — `ANALYST_COOLDOWN_SECONDS=15` between *triggered* refreshes
  (risk-change/cadence runtime triggers); CRITICAL severity or ACTIVE evacuation
  shortens it to 5 s; API calls bypass it.
- **Runtime integration** — `runtime.py` schedules fire-and-forget analyses on
  risk change and cadence; the simulation loop never awaits an LLM.
- **Health** — `status()` → `ONLINE | FALLBACK | DEGRADED | OFFLINE` with runs,
  cache hits, fallbacks, LLM error streaks, last latency/source/error, cooldown
  (surfaced at `GET /api/ai/status → "analyst"` and the `/ai` status pill).
- **Persistence** — `ai_analyses` (bounded to 100) · `ai_recommendations` ·
  `ai_evidence` (migration `p8d9f4b7a2c6e`); failures are logged, never raised.

### Human-in-the-loop (§24)

Recommendations are **advice only**: cards are born `PENDING` with
`requires_human_approval=true`; operators/admins `ACCEPTED` or `DISMISSED`
(decided rows record `decided_by`/`decided_at`; one decision per card → 409).
The Analyst never executes an action and cannot block the sim loop.

### API + WebSocket

`POST /api/ai/analyze` (role `analyze`, body `{question?, mode?}` — 400 on unknown mode) ·
`GET /api/ai/analysis` (`?limit&mode&severity`) · `/analysis/latest` ·
`/analysis/{id}` · `GET /api/ai/recommendations` (`?status&analysis_id`) ·
`POST /api/ai/recommendations/{id}/decision` (role `apply`) ·
`GET /api/ai/evidence/{id}` · `GET /api/ai/status` (+`analyst` block) — see
`docs/api.md`. WS `analyst.analysis_started|analysis_completed|analysis_updated|
recommendation_created|alert_created` (envelope v1, `context_summary` stripped);
legacy `analyst` broadcast kept for back-compat.

### Frontend

- **`components/ai/AnalystBrief.tsx`** — structured brief: severity/priority
  chips, confidence meter with component breakdown, what-is-happening, why,
  affected areas, predicted effects, what-changed, route assessment, question
  answer, recommendation cards with ACCEPT/DISMISS (role-gated). Falls back to
  the Phase 5 narrative blocks on legacy payloads.
- **`components/ai/EvidencePanel.tsx`** — every claim's grounding evidence;
  expanding an item round-trips `GET /api/ai/evidence/{id}`.
- **AI page (`/ai`)** — analyst status pill (`ONLINE/FALLBACK/DEGRADED/OFFLINE`),
  brief + evidence + decision workflow (ANALYST/ADMIN run analyses,
  OPERATOR/ADMIN decide).
- **Dashboard** — AI-INSIGHT block (compact brief + evidence) in the AI rail.
- **Store/WS** — `analyst.analysis_completed|analysis_updated` frames update the
  brief live; `analystStatus` slice feeds the pill.

### Phase 8 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 156 passed (130 + 26 Phase 8)
.venv\Scripts\python tests\smoke_api.py                 # 147/147 (server must be running)
.venv\Scripts\python tests\ws_check.py                  # 48/48 (+ analyst.* events)

cd frontend
npm run test                                            # vitest → 97 passed (90 + 7 Phase 8)
```

---

## Phase 9 — Command Center, Analytics & Historical Intelligence

Everything the platform has persisted — risk scores, occupancy, readings, route
events, AI analyses, incidents, simulations — is now queryable as **server-side
aggregated analytics**, presented as a professional command center, a full
analytics workspace, a historical intelligence page and **deterministic
simulation replay**. No new chart library, no fake data: every series comes from
persisted rows, and empty windows report `available: false` with a reason.

```mermaid
flowchart LR
    DB[(SQLite · indexed<br/>risk_scores · occupancy_records ·<br/>sensor_readings · route_events ·<br/>ai_analyses · incidents · simulations ·<br/>simulation_events)] --> AGG[analytics_service.py<br/>window + bucket + trend + honesty]
    AGG --> RA[routes_analytics.py<br/>17 endpoints · role read]
    DB --> HS[history_service.py<br/>lists · detail · report · compare]
    HS --> RH[routes_history.py<br/>11 endpoints · role read]
    DB --> RP[replay_service.py<br/>WallClockMap · frames · events]
    RP --> RF["/replay · /frame?t="]
    RA --> AN[/analytics workspace<br/>URL state + CSV export/]
    RA --> DB2[/dashboard KPI strip ·<br/>system-health bar · What Changed?/]
    RH --> HI[/history tabs<br/>detail · report · compare/]
    RF --> RE[Replay transport<br/>PLAY/PAUSE/RESET · 0.5–10x<br/>replay slice ≠ live state]
    RE --> DB2
```

### Aggregation & honesty (`backend/app/services/analytics_service.py`)

- **Windows** — `15M | 1H | 6H | 24H | 7D | 30D | CUSTOM(start,end)`; every
  response echoes `window/source/computed_at`. SQLite bucket SQL uses
  `literal_column` (SQLAlchemy would otherwise compile `/` as `a / (? + 0.0)`).
- **Risk bands (5)** — `RISK_BANDS` mirrors `state.risk_level()`:
  LOW ≤20 · MODERATE ≤40 · ELEVATED ≤60 · HIGH ≤80 · CRITICAL;
  `RISK_KPI_STATUS` maps MODERATE/ELEVATED→WARN, HIGH/CRITICAL→CRITICAL.
  `_time_in_categories` reports exactly these five categories.
- **Trends** — every block carries `TrendBlock{direction,delta,delta_pct,label,
  available}`; unavailable when a window has <2 points (no fabricated deltas).
- **Honesty** — no rows in window → `available: false` + `reason`; series are
  never interpolated. `ENV_METRICS` order: temperature, humidity, air_quality,
  smoke, water. CSV `EXPORT_KINDS`: summary, risk, occupancy, energy,
  sensor_health, buildings, routes, incidents, simulations.

### History & replay (`history_service.py` · `replay_service.py`)

- **Incidents/simulations** — server-side pagination (`page/page_size/pages`),
  filters (status/severity/kind/q/building · scenario/status/q), detail with
  metrics + timeline, `report` (executive summary · timeline categories ·
  contributing factors · response actions), 2-simulation compare, CSV export.
- **Replay** — `build_replay()` assembles `frames` (≤500, evenly stepped),
  persisted `events`, `risk_series`, route/AI/incident context and a
  `WallClockMap` (tz-normalized) mapping sim-t → wall-clock;
  `replay_frame(id, t)` returns the same frame deterministically.
  `LIFECYCLE_STATUS` maps lifecycle kinds → CREATED/RUNNING/PAUSED/RECOVERING/
  AWAITING_RECOVERY/RECOVERED/COMPLETED.
- **Indexes (migration `p9f3c8d2e7b1`)** — 6 indexes over the aggregation
  columns (time+entity risk, readings by time, occupancy by time, incidents
  by status/started, simulations by status/created, simulation_events by sim+t).

### Frontend

- **`/dashboard`** — `components/dashboard/KpiStrip.tsx` (window KPIs +
  sparklines from `GET /analytics/overview`), `SystemHealthBar.tsx` (9
  components, 30 s refresh), `HealthChangesPanel.tsx` (campus health score +
  What Changed?), right-rail `ai|health` tabs, and replay mode driven by
  `?replay=<simId>` (sim card replaced by `ReplayControls`, `ReplayBanner`
  shows LIVE/REPLAY; exiting clears the URL param).
- **`/analytics`** — all filters live in the URL (`range,start,end,building,
  zone,metric,kind,status,severity,q,scenario,compare`) so views are shareable
  and refresh-safe; sections render server-computed blocks only;
  `utils/download.ts` handles authenticated CSV downloads.
- **`/history`** — Incidents | Simulations tabs (URL `tab` + filters +
  pagination), incident drawer (timeline · metrics · report · CSV), simulation
  drawer (metrics · events-by-category · linked incidents), 2-run compare
  panel, **Replay** buttons that navigate to `/dashboard?replay=<id>`.
- **Replay store slice** (`useTwinStore`) — `loadReplay/closeReplay/
  setReplayT/setReplaySpeed/setReplayPlaying/stepReplay/tickReplay` plus a
  derived `replaySnapshot`: topology from the live base, all dynamic values
  strictly from the persisted frame. `CampusScene` renders
  `replaySnapshot ?? snapshot`, so **replay never mutates live state**.

### Phase 9 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 191 passed (156 + 35 Phase 9)
.venv\Scripts\python tests\smoke_api.py                 # 180/180 (server must be running)
.venv\Scripts\python tests\ws_check.py                  # 48/48

cd frontend
npm run typecheck && npm run build
npm run test                                            # vitest → 152 passed (97 + 55 Phase 9)
```

Covers §60 endpoint behaviour (windows, bands, honesty, RBAC, CSV), §61 replay
determinism (same t → same frame; frame-derived state; source honesty) and §62
UI (replay store/transport/banner, History tabs/drawers/compare/replay
hand-off, Analytics URL state + export) against **captured real API responses**
(`frontend/src/testData/`).

---

## Phase 10 — Authentication, Authorization, Security Hardening & Auditability

Identity, roles, hardened auth flows, centralized RBAC, rate limiting, security headers,
WebSocket authentication and a queryable audit trail — backend, UI, tests, docs and
deployment posture. Full detail: [docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md) (audit →
fixes → verification), [docs/SECURITY.md](docs/SECURITY.md),
[docs/AUTHENTICATION.md](docs/AUTHENTICATION.md), [docs/RBAC.md](docs/RBAC.md),
[docs/AUDIT_LOGGING.md](docs/AUDIT_LOGGING.md).

### Roles & permissions

Four roles — `ADMIN` · `OPERATOR` · `ANALYST` · `VIEWER` — with a central matrix in
`backend/app/core/security.py` (`read · simulate · apply · analyze · export · reset ·
audit · manage`) enforced by `require(permission)` on every protected route; denials
return 403 and write an `authz.denied` audit row. The frontend mirrors it with
`RequireRole` routes and role-aware navigation. Matrix + special rules →
[docs/RBAC.md](docs/RBAC.md).

### Authentication

- **Argon2id** passwords (`argon2-cffi`) with legacy PBKDF2 verify + transparent rehash;
  policy ≥8/≤128, ≠ username, not a common password.
- Login → HS256 JWT (`sub·username·role·tv·jti·iss·aud·exp`, 12 h default); validated on
  every request against signature, issuer, audience, expiry, **jti deny-list** and the
  user's `token_version` (bumped on password change / role change / disable → all
  outstanding tokens die at once).
- Endpoints: `POST /api/auth/{login,register,logout,change-password}`, `GET /api/auth/{me,demo,roles}`;
  admin bootstrap `python -m app.services.bootstrap_admin --username …`
  (refuses dev secrets, prompts or `BOOTSTRAP_ADMIN_PASSWORD`).
- Rate limits: login 20/min dual-keyed (IP + IP|username), register 5/min, exports
  30/min, AI 20/min, simulation 30/min, admin 60/min, WS 60/min, general 120/min → 429 +
  `Retry-After`.

### Hardening

- **WebSocket:** token never in the URL — first frame `{"type":"auth","token"}` within
  `WS_AUTH_TIMEOUT_S` (4401 on bad/revoked token before any state), permission-gated
  channels (`state`→read, `admin`→manage), 60 s revalidation, 4429/1009 backpressure.
- **Headers/middleware:** `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Permissions-Policy`, CSP (HTML), `X-Request-ID` correlation,
  1 MB body cap → 413, generic 500s (no stack/SQL leaks), optional HSTS.
- **CORS:** explicit origin list only — wildcard refused at startup; `APP_ENV=production`
  additionally refuses dev `JWT_SECRET` defaults (compose requires `${JWT_SECRET:?…}`).
- **Demo posture:** demo users + registration auto-disabled in production; `/api/auth/demo`
  never returns passwords.

### Audit trail & user administration

`audit_logs` gains `outcome` + `request_id`; `core/audit.py` redacts
password/token/secret fields. Actions cover `auth.*`, `authz.*`, `admin.*` and every
control-plane mutation (`realtime.*`, `simulation.*`, `demo.*`, …). Read-only
`GET /api/audit[/actions]` with q/action/outcome/date filters; **OPERATOR sees only the
operational subset** (`auth.*/authz.*/admin.*` hidden). UI: **Administration → Audit Log**.

**`/admin/users` (ADMIN):** search/role filter, create user (whitelisted role), role
change, enable/disable, one-time password reset — with self-protection rules (no
self-disable/demote stranding the last admin).

### Migration

`p10b4d7e1a9c6_phase10_security` — `users` gains `is_active · last_login_at ·
password_changed_at · token_version`; new `revoked_tokens` deny-list; `audit_logs` gains
`outcome · request_id` (indexes on action/outcome/created_at/request_id).

### Frontend

- `/login`: demo-chip fills usernames (passwords stay in README), clear 401/429 messages.
- Session: boot revalidates via `GET /api/auth/me`, logout calls the API, change-password
  swaps the token; 401 → login, 403 → `ACCESS DENIED`, 429 → `RATE LIMITED`.
- `RequireRole` guards `/admin/*`; Administration nav only for ADMIN/OPERATOR.

### Phase 10 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 239 passed (191 + 48 Phase 10)
.venv\Scripts\python tests\smoke_api.py                 # 192/192 (server must be running)
.venv\Scripts\python tests\ws_check.py                  # 56/56

cd frontend
npm run typecheck && npm run build
npm run test                                            # vitest → 193 passed (152 + 41 Phase 10)
```

Covers the auth matrix (each role × allowed/denied routes), token revocation, password
policy/hashing, rate-limit buckets, headers/CORS/secrets validation, WS handshake +
channel ACL, audit schema/scoping/redaction, user administration, and the frontend
session/RBAC/403/429 handling. Dependencies re-audited: `pip_audit` → 0 runtime
vulnerabilities (PyJWT → 2.15.0, pytest → 9); `npm audit` → 2 moderate react-router
advisories accepted with rationale (fix = breaking v7) in
[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).

---

## Phase 11 — Testing, Performance, Reliability & Regression Engineering

Full details: [docs/PHASE_11_TESTING.md](docs/PHASE_11_TESTING.md) · [docs/PERFORMANCE.md](docs/PERFORMANCE.md)

- **Cross-phase E2E** — `tests/test_e2e_workflows.py`: 20 tests across scenarios A–F
  covering auth → campus → 3D payload → incident → risk → AI advisory → simulation
  lifecycle → analytics window/filters/pagination/export → deterministic replay →
  role matrix → audit.
- **Concurrency / TOCTOU fix** — `app/api/routes_simulations.py` gains a module-level
  `_SIM_LOCK` serializing create-check-act and all lifecycle transitions; create guard
  broadened to block any non-`COMPLETED` active sim. 5 concurrency tests prove no
  double-create, no interleaved transitions, and consistent concurrent reads.
- **Smoke determinism** — `tests/smoke_api.py` adds `skip()` helper; 5 conditional
  sites converted; anomaly detail retries with a fresh ID; summary reports
  `191/194 passed (3 skipped)` — deterministic across runs.
- **WebSocket resilience** — `tests/ws_check.py` extended to 60 checks: rapid
  connect/disconnect, reconnect after abrupt close, dual-client broadcast, double
  subscribe idempotency.
- **Observability** — `app/core/metrics.py`: thread-safe, key-capped (400) in-process
  counters wired into HTTP middleware (route-template keyed), WS manager, simulation
  lifecycle, and rate limiter. `GET /api/system/metrics` exposes uptime + counters.
  5 tests.
- **Benchmark** — `tests/benchmark_api.py`: repeatable p50/p95/p99 + payload sizes for
  12 read-heavy endpoints; baseline numbers in [docs/PERFORMANCE.md](docs/PERFORMANCE.md).
- **DB indexes** — migration `p11e5a7c3d8f4_phase11_reliability_perf.py` adds four
  composite indexes (`audit_logs(action,outcome,actor,created_at)`,
  `incidents(severity,started_at)`) eliminating `TEMP B-TREE` sorts on filtered+sorted
  queries. Verified with `EXPLAIN QUERY PLAN` on the live 87 MB DB.
- **React-router advisories** — deeper investigation: GHSA-wrjc-x8rr-h8h6 (open
  redirect) and GHSA-337j-9hxr-rhxg (deserializeErrors injection) both
  architecturally unreachable in this SPA (no SSR, no untrusted navigation targets).
  Accepted with rationale (fix = breaking v7).
- **CI** — `.github/workflows/ci.yml`: backend (pytest + smoke + ws), frontend
  (typecheck + test + build), security (pip-audit + npm audit + gitleaks) as parallel
  jobs. Security scans are advisory (`continue-on-error`).

### Phase 11 tests

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q                 # 269 passed (239 + 20 E2E + 5 concurrency + 5 metrics)
.venv\Scripts\python tests\smoke_api.py                 # 191/194 (3 skipped; server must be running; space runs >=60s — login rate limit)
.venv\Scripts\python tests\ws_check.py                  # 60/60
.venv\Scripts\python tests\benchmark_api.py             # p50/p95/p99 + payload sizes (server must be running)

cd frontend
npm run typecheck && npm run build
npm run test                                            # vitest → 193 passed
```

---

## Testing

```powershell
# Backend end-to-end API suite — start the server first, or run the combined flow:
cd backend
$env:PYTHONPATH = (Resolve-Path ..).Path
.venv\Scripts\python -m uvicorn app.main:app --port 8000     # terminal 1
.venv\Scripts\python tests\smoke_api.py                      # terminal 2  → 191/194 (3 skipped)
.venv\Scripts\python tests\ws_check.py                       # WebSocket checks → 60/60
.venv\Scripts\python tests\benchmark_api.py                  # p50/p95/p99 benchmark (12 endpoints)

.venv\Scripts\python -m pytest tests -q                      # unit/integration → 269 passed
#   (239 Phases 1–10 + 20 E2E + 5 concurrency + 5 metrics)

# Frontend
cd frontend
npm run typecheck && npm run build
npm run test                               # vitest: utils + store + panels + twin/AI/analyst/history/analytics/replay/security → 193 passed

# CI (GitHub Actions)
.github/workflows/ci.yml                   # backend (pytest+smoke+ws) + frontend (typecheck+test+build) + security (pip-audit+npm-audit+gitleaks)
```

---

## Repository layout

```
TwinSphere-AI/
├── backend/            FastAPI app: API, auth, WebSocket, runtime loop, services
│   ├── app/{api,core,models,services,schemas,websocket}
│   ├── alembic/        Alembic migrations (b3937b6fe73a baseline → p6a1c9e4d2f7 → p7c4e8b2d9f1a routes → p8d9f4b7a2c6e analyst → p9f3c8d2e7b1 analytics indexes → p10b4d7e1a9c6 security → p11e5a7c3d8f4 reliability/perf indexes)
│   ├── requirements-dev.txt   Phase 10: dev/test deps split (pytest 9, pip-audit)
│   └── tests/          smoke_api.py · ws_check.py · benchmark_api.py · pytest suite (incl. Phase 2 + Phase 10 security + Phase 11 E2E/concurrency/metrics)
├── ai/                 Deterministic + ML engines: risk, prediction, anomaly, simulation, optimization, analyst
├── frontend/           React 18 · Vite · Tailwind v4 · Three.js/R3F · Recharts · Zustand · Vitest
├── database/           (SQLite file lives in backend/ by default; this dir is for external DB artifacts)
├── simulation-data/    Exported campus_model.json + sensor_history.csv (generated at seed time)
├── docs/               architecture.md · api.md · AI_ANALYST.md · ROUTING.md · simulation.md · ANALYTICS.md · REPLAY.md
│                       SECURITY_AUDIT.md · SECURITY.md · RBAC.md · AUTHENTICATION.md · AUDIT_LOGGING.md
│                       PHASE_11_TESTING.md · PERFORMANCE.md
├── .github/workflows/  ci.yml (backend + frontend + security)
├── docker-compose.yml  backend + frontend (+ optional postgres profile)
└── .env.example        Environment contract
```

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///…/backend/twinsphere.db` | SQLAlchemy URL (SQLite or PostgreSQL) |
| `JWT_SECRET` | `dev-only-change-me-in-production` | JWT signing secret — **startup refuses dev default when `APP_ENV=production`** (compose requires it) |
| `APP_ENV` | `development` | `production` → demo users + registration off, strict secret/CORS validation |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed origins — wildcard refused at startup |
| `JWT_EXPIRE_MINUTES` | `720` | Access-token lifetime (Phase 10) |
| `DEMO_USERS_ENABLED` / `REGISTRATION_ENABLED` | dev `true` / prod `false` | Phase 10 demo + self-registration gates |
| `RATE_LIMIT_ENABLED` + `*_RATE_LIMIT_PER_MINUTE` | `true` (+ per-category) | Phase 10 limiter (login 20 · register 5 · export 30 · ai 20 · simulation 30 · admin 60 · ws 60 · general 120 per minute) |
| `HSTS_ENABLED` / `SECURITY_HEADERS_ENABLED` | `false` / `true` | Phase 10 transport hardening (enable HSTS behind TLS) |
| `MAX_REQUEST_BODY_BYTES` | `1000000` | Phase 10 body cap → HTTP 413 |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | empty / `gpt-4o-mini` | Optional LLM analyst (deterministic fallback when unset) |
| `LLM_TIMEOUT` / `LLM_MAX_TOKENS` | `12` / `900` | Phase 8 LLM call budget — on timeout/error/bad JSON the deterministic fallback answers |
| `ANALYST_COOLDOWN_SECONDS` | `15` | Phase 8 minimum gap between triggered analyst refreshes (5 s at CRITICAL; API bypasses) |
| `SENSOR_TICK_SECONDS` | `2.0` | Telemetry cadence |
| `SIMULATION_SPEED` | `1.0` | Virtual clock multiplier (× 15 virtual-s per real second) |
| `SIMULATION_ENABLED` | `true` | Phase 4 live simulator runtime; `false` boots STOPPED and closes `/ws` with 1013 |
| `SIMULATION_PERSIST_INTERVAL` | `20.0` | Seconds between batched `sensor_readings` writes |
| `SIMULATION_SEED` | unset (→ `RANDOM_SEED`) | Dedicated seed for the realtime simulator |
| `WEBSOCKET_ENABLED` | `true` | Set `false` to refuse all `/ws` upgrades |
| `VITE_API_URL` / `VITE_WS_URL` | same-origin | Frontend API/WS targets when not using the dev proxy |

Copy `.env.example` → `.env` (loaded automatically by the backend).
