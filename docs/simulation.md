# TwinSphere AI — Emergency What-If Simulation Engine (Phase 6)

Reference for the deterministic emergency simulator: scenarios, validation rules, the
state machine, sensor feedback, recovery, results and the `simulation.*` WebSocket
events. Everything here is **simulated data** — the engine has no I/O of its own; the
runtime loop, REST API and store are the only things that persist or broadcast.

## Layers

```
ai/simulation/            pure models (no imports from backend)
  propagation.py          zone-graph fire spread · wind · smoke · zone_totals
  fire_simulation.py      intensity/wind/occupancy validation · smoke bands · status ladder
  crowd_simulation.py     density + occupancy multiplier ramp
  power_failure_simulation.py  service drops · backup generators · status chain
  road_closure_simulation.py   block/reopen · congestion impact
  extreme_temperature_simulation.py  campus heat event
  recovery_engine.py      exponential glide (RECOVERY_TAU = 22 s)
backend/app/services/
  simulation_engine.py    orchestrator: validation §52 · lifecycle · peaks · results §48
  state.py                SimulationState · SimulationContext · build_simulation_context
  sensor_engine.py        applies scenario modifiers to every sensor tick
  runtime.py              drives tick_simulation + flushes queued simulation.* events
```

The engine shares the Phase 4 clock (`state.clock`, `state.speed`) — there is no second
clock. Sensor ticks and simulation ticks advance together while the simulator is
`RUNNING`; `PAUSED` freezes both.

## Scenarios (§50–§51)

| Scenario | key | Duration | Recovery | Target | Distinct physics |
|---|---|---|---|---|---|
| Fire Emergency | `fire` | 330 s | 130 s | building (required) | zone-graph spread, wind, smoke, heat |
| Crowd Surge | `crowd` | 300 s | 90 s | building (required) | occupancy multiplier ramp, density |
| Power Failure | `power` | 240 s | 110 s | building (required) | service drop, backup pickup |
| Road Closure | `road` | 300 s | 80 s | road id (defaults) | block/reopen, route congestion |
| Extreme Temperature | `temperature` | 360 s | 120 s | campus | outdoor heat event |

### Fire parameters (`POST /api/simulations` body `params`)

| Param | Type | Default | Rules |
|---|---|---|---|
| `intensity` | number | 5 | engine accepts **1–10**; UI exposes **1–5** with labels `intensity_label()`: 1 LOW · 2 MODERATE · 3 HIGH · 4 SEVERE · 5+ EXTREME (legacy 6–10 tests stay valid, labels clamp to EXTREME) |
| `wind` | string | `E` | one of 9: `N NE E SE S SW W NW NONE` (validated, uppercase-normalised) |
| `ignition_zone` | string | first LAB in target, else any zone | must belong to the target building; `zone_id` is accepted as an alias (renamed before validation) |
| `initial_occupancy` | int | — | `>= 0` if present |
| `burn_rate` | number | 1.0 | spread rate multiplier |

Crowd: `occupancy_increase` 0–300 % (default 40). Road: `road_id` must exist in the
road graph (defaults to the first road).

### Validation → HTTP (§52)

- Unknown scenario / bad parameter / ignition zone not in target → **400** with the
  engine's `ValueError` message (unknown scenario is a 400, not a 422 — `scenario` is
  a free string in the schema).
- `fire`/`crowd`/`power` without `target_id` → 400.
- Second active simulation (`RUNNING`/`PAUSED`/`AWAITING_RECOVERY`/`RECOVERING`) →
  **409** "An active simulation is already running. Please stop or recover the current
  simulation first."
- Unknown `sim_id` on detail/lifecycle → **404**.

## State machine (§30–§46)

```
CREATED ──start──> RUNNING ──duration done──> AWAITING_RECOVERY ──recover──> RECOVERING ──> COMPLETED
   │                  │ │                          │                              │
   │                pause ⇄ resume               reset                          reset
   └──────────────────┴─┴──────────────────────────┴──────────────────────────────┘
                                              (reset clears state + deltas, status back to CREATED)
```

- `start` ignites the scenario: fire spreads from `ignition_zone`, an **incident** is
  created on the target building carrying `simulation_id` (Alembic
  `p6a1c9e4d2f7_phase6_incident_simulation_link`), alerts/recommendations are raised.
- Ticking runs `tick_simulation(dt)` once per runtime loop step (scaled by
  simulation speed); every tick updates bookkeeping and queues typed events.
- At `duration` the sim enters `AWAITING_RECOVERY` (completion event carries
  `awaiting_recovery: true`); `recover` starts the gradual glide; on finish status is
  `COMPLETED`, results are stored on the DB row and `simulation.completed` fires again.

## Fire model (§38–§45)

- `propagation.ignite` marks the ignition zone `FIRE` with heat proportional to
  intensity; `step_fire` spreads to graph neighbours each tick — probability boosted by
  wind alignment (`WIND_VECTORS`, 8 directions + NONE), smoke diffuses a hop and decays
  each tick; `suppress` glides zones back toward normal during recovery.
- `zone_totals(zones, building_id)` returns per-status counts, raw `people_at_risk`
  (zone occupancy) and **severity-weighted** `weighted_people`
  (`FIRE 1.0 · SMOKE 0.6 · AFFECTED 0.3 · NORMAL 0.0`).
- Smoke severity = `smoke_units / 300 → 0–100` → band
  `CLEAR · LIGHT · MODERATE · HEAVY · CRITICAL` (`SMOKE_BANDS`).
- Peaks (`peak_temperature`, `peak_smoke`) take the **max of zone-model totals and the
  building's sensors**, so instrument readings participate even in engine-only tests.
- Building status ladder from live state (`building_status()`):
  `CRITICAL` if `burning_zones >= 2 or max_fire >= 0.7`;
  `DANGER` if `burning >= 1 and max_fire >= 0.45`;
  `ALERT` if any fire / affected ≥ 1 / smoke severity ≥ 6;
  else `NORMAL`. Ignition sets the target building to `ALERT` immediately; recovery
  walks it back to `OPERATIONAL` — never teleported.

## Sensor feedback (§47)

`build_simulation_context()` carries active-scenario modifiers (occupancy multiplier,
temperature offset, smoke/heat contributions) into the sensor tick. On top of the
existing smoke → air-quality coupling, Phase 6 adds **fire heat coupling**: zone heat
raises the building's temperature sensors while a fire burns, so instruments move with
the scenario instead of the scenario being a UI-only overlay.

## Recovery (§49)

`recovery_engine.glide(current, baseline, dt, tau=22)` — exponential convergence:
~63 % of the remaining gap closes every 22 s of (scaled) time. `recovery_percent()`
drives `simulation.recovery_progress` and the snapshot's `recovery_progress`. Statuses,
metrics and effects are released gradually; `reset` is the only way to jump state.

## Results (§48)

`compute_results()` builds an honest block from the actual run — served live
(`live: true`) while active, or from the stored row after completion:

```json
{
  "scenario": "fire", "scenario_label": "Fire Emergency",
  "target_id": "eng", "target_name": "Engineering Block", "status": "COMPLETED",
  "peak_risk": 78.4, "peak_risk_level": "HIGH",
  "peak_people_at_risk": 42, "weighted_people_at_risk": 31.8,
  "affected_zone_count": 5, "peak_temperature": 61.2, "peak_smoke": 188.0,
  "smoke_band": "HEAVY", "burning_zones": 2,
  "duration_s": 330.0, "recovery_time_s": 130.0, "events": 27,
  "intensity": 4, "intensity_label": "SEVERE", "wind": "E"
}
```

`peak_risk` is captured **inside** `tick_simulation` each tick (max of observed scores),
so it reflects the real run regardless of who ticks first.

## WebSocket events (§27–§28)

The engine is synchronous: `queue_sim_event(state, event, data)` appends to
`state.pending_sim_events` (capped at 60, oldest dropped); the runtime loop flushes
them through `manager.emit` with the standard envelope
(`event_version: 1`, `timestamp`, `source: "SIMULATED"`). Legacy `state`/`simulation`/
`event` broadcasts continue alongside.

| Event | When | Data |
|---|---|---|
| `simulation.created` | create | full sim dict |
| `simulation.started` / `simulation.resumed` | first start / resume | sim dict |
| `simulation.paused` | pause | sim dict |
| `simulation.reset` | reset | sim dict |
| `simulation.recovery_started` | recover | sim dict |
| `simulation.recovery_progress` | during recovery | sim dict + `recovery_progress` |
| `simulation.recovered` | glide finished | sim dict |
| `simulation.completed` | duration done (`awaiting_recovery: true`) and final completion | sim dict (+ results on final) |
| `simulation.tick` | every runtime step (≈1 Hz × speed) | sim dict + flat `risk`, `risk_level`, `speed`, `building_smoke`, `building_temperature`, `building_status` |
| `simulation.zone_update` | zone statuses changed (diffed; first observation skipped) | `{simulation_id, changed: [{id, building_id, status, fire, smoke, temperature, risk_level}], count, clock}` |
| `simulation.risk_update` | risk recomputed (every telemetry flush) | `{simulation_id, risk, level, target_id, target_risk, people_at_risk, clock}` |

Sim dict includes `weighted_people`, `affected_zones`, `max_people_at_risk`,
`peak_temperature`, `peak_smoke`, `results` (once computed), plus the legacy fields.

## Failure isolation (§67)

A raising simulation tick is caught by the runtime: the `simulation` health flag goes
false (`/api/realtime/status` → `simulation_engine`), increments
`runtime._sim_failures`, and **nothing else stops** — twin, sensors, AI cycles and the
socket keep running. Health recovers when a tick succeeds again.

## Frontend

- **Simulation Center** (`/simulation`) — scenario cards, ignition-zone selector,
  intensity slider with 1–5 labels, 9-way wind compass, live metrics (people, risk,
  affected zones, peak temp, building smoke, sim speed), speed chips (0.5/1/2/4×),
  results panel (live + history drill-down), `SIMULATED DATA` badge, demo-drill
  launcher (`DemoMode` creates **and** starts).
- **AppShell banner** — red `SIMULATION ACTIVE` (scenario/target/elapsed/people)
  while RUNNING, amber while PAUSED, blue recovery strip while RECOVERING.
- **3D hazard visuals** — burning/smoky/affected zones tint + pulsing hazard ring
  (`HazardPulse`), visible even with the zones layer off; **FOCUS INCIDENT** on the
  Twin Explorer rails the camera to the incident building and selects it.
- **Store** — `simulation.tick` merges into `snapshot.active_sim`; lifecycle events
  update active sim, toasts, live log, `recovery_progress` and refresh history on
  completion/reset.

## Tests

| Suite | Count | Where |
|---|---|---|
| Unit/integration | 19 Phase 6 tests (spread closure, wind-east, escalation + heat coupling, recovery, 5 scenarios, validation, 409, detail/results, telemetry, queue/flush, §66 chain) | `backend/tests/test_phase6_simulation.py` (suite total 106) |
| Live REST smoke | Phase 6 drill + validation battery + detail/results + 409 | `backend/tests/smoke_api.py` (107/107) |
| Live WS | create/start + `simulation.*` collection + envelope checks | `backend/tests/ws_check.py` (39/39) |
| Frontend | 5 store tests (tick merge, zone diff, risk update, lifecycle, ignore-without-id) | `frontend/src/store/twinStore.test.ts` (69 total) |

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python tests\smoke_api.py     # server must be running
.venv\Scripts\python tests\ws_check.py
cd ..\frontend
cmd /c npm run typecheck && cmd /c npm test
```
