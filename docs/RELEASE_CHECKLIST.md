# TwinSphere AI — Release Checklist

Run before tagging a release.  The release verification script
(`scripts\release_check.ps1` on Windows, or the commands below) automates
most of this.

---

## Automated checks

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | Backend pytest | `cd backend && python -m pytest tests -q` | All passed, 0 failed |
| 2 | Alembic fresh upgrade | `DATABASE_URL=sqlite:///./tmp.db alembic upgrade head` | Exit 0 |
| 3 | Production secret validation | `APP_ENV=production JWT_SECRET=dev-... python -c "from app.core.config import validate_security_config; validate_security_config()"` | RuntimeError (refused) |
| 4 | Frontend typecheck | `cd frontend && npm run typecheck` | Exit 0 |
| 5 | Frontend unit tests | `cd frontend && npm run test -- --run` | All passed |
| 6 | Frontend production build | `cd frontend && npm run build` | Exit 0 |
| 7 | API smoke (live server) | `cd backend && python tests/smoke_api.py` | Exit 0 (skips reported honestly) |
| 8 | WebSocket checks (live server) | `cd backend && python tests/ws_check.py` | Exit 0 |
| 9 | Load test (optional) | `cd backend && python tests/load_test.py` | Exit 0 |
| 10 | Secret scan | `git grep -nI -E '(AKIA[0-9A-Z]{16}\|ghp_...)'` | No hits |
| 11 | Git status | `git status --porcelain` | Clean (or only intended changes) |

Run all at once:

```powershell
# Windows
.\scripts\release_check.ps1

# skip live-server checks if the server is not running
.\scripts\release_check.ps1 -SkipSmoke -SkipLoad
```

---

## Manual checks

| # | Check | How |
|---|-------|-----|
| 12 | Demo run completes | `POST /api/demo/run` as operator → `status: completed` |
| 13 | Demo reset idempotent | `POST /api/demo/reset` twice → both 200 |
| 14 | Demo double-start conflicts | `POST /api/demo/run` while running → 409 |
| 15 | RBAC matrix | Log in as each role; verify allowed/denied routes |
| 16 | Audit trail | Trigger a denied action; check `/api/audit` shows `DENIED` |
| 17 | Health endpoint | `GET /health` returns `status: ok` |
| 18 | Metrics endpoint | `GET /api/system/metrics` returns counters |
| 19 | Replay immutability | Run a sim; replay; verify original events unchanged |
| 20 | Session expiry | Wait for token expiry or call logout; verify 401 → login |

---

## Docker checks (when Docker is available)

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 21 | Compose config valid | `docker compose config` | Prints resolved config; no errors |
| 22 | Images build | `docker compose build` | Exit 0 |
| 23 | Services healthy | `docker compose up -d && curl localhost:8000/health` | `status: ok` |
| 24 | Smoke against container | Point smoke at `localhost:8000` | Exit 0 |
| 25 | Clean shutdown | `docker compose down` | Exit 0; volumes preserved |

**NOT RUN in this environment** — Docker daemon unavailable.  Syntax was
reviewed manually; `docker compose config` was not executed.

---

## Documentation checks

| # | Check |
|---|-------|
| 26 | README reflects actual test counts and commands |
| 27 | `docs/DEMO_GUIDE.md` matches the demo endpoints |
| 28 | `docs/DEPLOYMENT.md` matches the Dockerfiles / compose file |
| 29 | `docs/OPERATIONS.md` matches the health/metrics endpoints |
| 30 | `docs/SECURITY_AUDIT.md` findings are up to date |
| 31 | `.env.example` documents every supported variable |

---

## Release tagging

After all checks pass:

```bash
git tag -a v1.0.0 -m "TwinSphere AI v1.0.0 — Phase 12 production readiness"
git push origin v1.0.0
```

---

## Honest status reporting

The release verification script distinguishes:

- **PASSED** — check ran and succeeded.
- **FAILED** — check ran and failed (blocks release).
- **SKIPPED** — check intentionally skipped by flag (e.g. `-SkipSmoke`).
- **NOT RUN** — check could not run (missing server, Docker, credentials).

Skipped and NOT RUN checks are **never** counted as passed.  Record them in
the release notes with the reason.
