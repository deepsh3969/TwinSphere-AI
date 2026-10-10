# TwinSphere AI — Demo Guide

A repeatable, deterministic walkthrough of the platform for presentations and
reviews.  Every value shown is **SIMULATED DATA** produced by the deterministic
engine — no real sensors, people counts, or emergency services are connected.

---

## Prerequisites

- Backend + frontend running locally (see README Quick start).
- Logged in as **operator** (has `simulate` + `apply` + `reset`) or **admin**.
- Optional: `APP_ENV=demo` in `.env` relaxes login rate limits for repeated
  runs and keeps demo accounts enabled.

---

## Option A — automated (recommended)

The backend can run the entire scripted demo deterministically:

```bash
# start the run (single-flight; 409 if one is already active)
curl -X POST http://127.0.0.1:8000/api/demo/run \
  -H "Authorization: Bearer $TOKEN"

# poll status
curl http://127.0.0.1:8000/api/demo/status \
  -H "Authorization: Bearer $TOKEN"

# stop mid-run (idempotent)
curl -X POST http://127.0.0.1:8000/api/demo/stop \
  -H "Authorization: Bearer $TOKEN"

# reset campus state without starting a new run (idempotent; never deletes
# users, audit history, or simulation history)
curl -X POST http://127.0.0.1:8000/api/demo/reset \
  -H "Authorization: Bearer $TOKEN"
```

The run applies each step of `DEMO_SCRIPT` against the in-process twin state,
so risk, routes, and incidents evolve deterministically from a known seed.
A rerun after reset produces the same building/zone/incident counts.

### Permission matrix

| Endpoint | Required permission | Typical role |
|----------|--------------------|--------------|
| `GET /api/demo/script` | `read` | any |
| `GET /api/demo/status` | `read` | any |
| `POST /api/demo/run` | `reset` | operator, admin |
| `POST /api/demo/stop` | `reset` | operator, admin |
| `POST /api/demo/reset` | `reset` | operator, admin |
| `POST /api/demo/hard-reset` | `manage` | admin |

---

## Option B — manual walkthrough (frontend)

Use the **Demo Mode** panel (rocket icon in the top bar).  It fetches the
script from `GET /api/demo/script` and drives the UI step by step:

| Step | What you see | Backend effect |
|------|-------------|----------------|
| 1. Normal campus | 3D twin, live sensor tiles ticking | runtime loop |
| 2. Select Engineering | building panel: occupancy, energy, risk | none (UI) |
| 3. Live sensor changes | metrics update over WebSocket | sensor tick |
| 4. AI prediction | occupancy forecast with confidence | prediction engine |
| 5. Start Fire Emergency | Simulation Center → fire → eng | `create_simulation` + `start` |
| 6. Fire spreads | smoke plumes, risk zones animate | simulation tick |
| 7. Risk rises | people-at-risk counter, blocked routes | risk engine |
| 8. Routes recalculated | A* re-routes away from hazard | `compute_routes` |
| 9. Evacuation panel | mode-weighted paths, bottlenecks | route service |
| 10. AI recommendation | analyst narrative + recommendation card | analyst service |
| 11. Apply recommendation | evacuation corridor becomes primary | `apply_recommendation` |
| 12. Recover | recovery progress 0 → 100 % | `recover_simulation` |
| 13. SYSTEM NORMAL | campus returns to normal | `full_reset` |

After the run, open **History** and replay the event sequence (seek, step,
immutability guaranteed).  Then reset the demo for the next presentation.

---

## Determinism

- The engine uses a fixed `RANDOM_SEED` (default 42, configurable).
- The demo runner applies a fixed 30-step virtual tick (15 s each) after
  starting the fire simulation, so risk propagation is reproducible.
- `full_reset` clears in-memory simulation/route/anomaly state but **never**
  deletes users, audit history, or persisted simulation rows.

---

## Honest limitations

- **People-at-risk** is an occupancy-based estimate, not a real headcount.
- **Recovery time** is virtual (compressed for the demo), not an emergency
  response SLA.
- **AI recommendations** are advisory-only; the operator must explicitly
  accept them.  No automated campus action is taken.
- **Route safety labels** (`SAFE`/`CAUTION`/`AVOID`) reflect the simulated
  risk engine, not real-world safety guarantees.
- Anomaly detail may be skipped in the smoke suite when anomalies expire
  between list and detail calls (runtime-dependent); the behaviour is covered
  by an isolated pytest test.
