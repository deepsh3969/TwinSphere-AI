# TwinSphere AI — Security Audit (Phase 10)

**Scope:** full application (Phases 1–9 codebase) reviewed and hardened for Phase 10
("Authentication, Authorization, Security Hardening & Auditability").
**Method:** manual code review of backend (`backend/app/**`, WebSocket layer, seed/bootstrap),
frontend (`frontend/src/**`), and deployment artifacts (`Dockerfile`s, `docker-compose.yml`,
`nginx.conf`, `.env.example`); dependency scanning with `pip-audit` and `npm audit`;
verification with the automated test suites (see [Verification](#verification)).

This document records every finding, its risk, how it was resolved, and how the fix was
verified. Anything that could **not** be verified or was intentionally left unresolved is
listed under [Residual risk & limitations](#residual-risk--limitations).

---

## Findings and resolutions

| ID | Finding | Risk | Resolution | Verification |
|---|---|---|---|---|
| F-01 | `/ws` accepted any connection and exposed state read + control topics to unauthenticated clients. | High | Two-step handshake: connection must send `{"type":"auth","token"}` within `WS_AUTH_TIMEOUT_S` before registration; query-string tokens are rejected before accept; channels are permission-gated (`state`→`read`, `admin`→`manage`); tokens revalidated every 60 s; close codes `4401` (bad/revoked token), `4429` (rate limit), `1009` (oversized frame). | `tests/ws_check.py` (auth-required, bad token, query refusal, channel gating), `tests/test_phase10_security.py` |
| F-02 | Role escalation: registration or user-creation accepted arbitrary `role` strings. | High | `register` always creates `VIEWER`; only ADMIN may create users and only ADMIN may assign/ change non-`VIEWER`→non-`VIEWER` roles (`routes_users.py`, `routes_auth.py`); `role` validated against the `ROLES` whitelist everywhere. | `test_phase10_security.py` (role escalation, register-as-admin rejected), smoke |
| F-03 | Development `JWT_SECRET` default was accepted in production. | High | `config.validate_security_config()`: under `APP_ENV=production` a dev/default secret or wildcard CORS **refuses startup** (non-production emits a warning). Compose passes `JWT_SECRET` via required `${JWT_SECRET:?…}` interpolation. | `test_phase10_security.py::test_wildcard_cors_refused_at_startup`, startup tests, compose file review |
| F-04 | No logout — a JWT was valid until expiry; no revocation. | High | Server-side deny-list (`revoked_tokens.jti`) checked on every authenticated request + per-user `token_version` bumped on password change/role change/disable (invalidates all outstanding tokens). | `test_phase10_security.py` (logout revokes, password change invalidates old token) |
| F-05 | No authorization layer — any authenticated (or unauthenticated) caller could hit mutations, admin and analytics endpoints. | High | Central RBAC in `core/security.py` (`ROLE_PERMISSIONS`, `require(permission)` dependency) applied across all routers; denials return 403 and write an `authz.denied` audit row; frontend routes/nav gated by role (`RequireRole`). See [docs/RBAC.md](RBAC.md). | 48 Phase 10 tests (incl. cross-role matrix), smoke 192/192 |
| F-06 | No user administration (list/create/disable/role change/password reset). | Medium | `GET/POST /api/users`, `PATCH /api/users/{id}`, `POST /api/users/{id}/reset-password` (ADMIN only) + **Administration** UI at `/admin/users` (role table, search/filter, one-time generated password display, self-protection rules). | Phase 10 tests, `App.security.test.tsx`, `AdminUsers.tsx` tests |
| F-07 | Operational events were logged only as application logs; no queryable audit trail or UI. | Medium | `audit_logs` extended (`outcome`, `request_id`, structured `detail` JSON), `core/audit.py` redacting recorder, read-only `GET /api/audit` + `GET /api/audit/actions`, **Audit Log** UI at `/admin/audit` with q/action/outcome/date filters and scope badge. See [docs/AUDIT_LOGGING.md](AUDIT_LOGGING.md). | Phase 10 tests (schema, scoping, redaction, filters), FE audit page tests |
| F-08 | No security-focused automated tests at all. | Medium | `backend/tests/test_phase10_security.py` (48 tests: auth, RBAC, rate limits, headers, secrets, WS-adjacent, audit, user admin) + `frontend/src/**` security suites (41 new assertions across `api.security`, `ws.security`, `Login.security`, `App.security`, store session tests). | Full suites green (see Verification) |
| F-09 | Passwords used stdlib PBKDF2 only. | Medium | Argon2id via `argon2-cffi` is now the default (`hash_password`); legacy `pbkdf2$` hashes still verify and are transparently upgraded (`needs_rehash`) on successful login. | Phase 10 password tests, smoke |
| F-10 | No password policy (length, reuse of username, common passwords). | Medium | `validate_password()`: ≥8 / ≤128 chars, ≠ username, not in common-password list; enforced at register, create-user, change-password, reset; failures return 400 with a clear message. | Phase 10 password policy tests |
| F-11 | Login and other sensitive endpoints had no rate limiting (credential stuffing / abuse). | High | Fixed-window in-memory limiter (`core/ratelimit.py`) with per-category limits: `login` 20/min keyed **both** by IP and `IP|username`, `register` 5/min, `export` 30/min, `ai` 20/min, `simulation` 30/min, `admin` 60/min, `ws` 60/min, `general` 120/min; 429 + `Retry-After`; `RATE_LIMIT_ENABLED=false` for tests. | Phase 10 rate-limit tests (each category), FE 429 handling |
| F-12 | CORS fell back to `*` and permissive defaults. | High | Explicit origin list required (`CORS_ORIGINS`, default localhost dev origins); wildcard refused at startup (unconditional `RuntimeError`, plus production validation); credentials not enabled with wildcard; `Authorization/Content-Type/X-Request-ID` headers only. | Startup tests, `test_wildcard_cors_refused_at_startup` |
| F-13 | No security headers on API responses. | Medium | Base middleware sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (camera/mic/geo denied), `Content-Security-Policy` on HTML, `X-Request-ID` (echoed or generated), optional HSTS (`HSTS_ENABLED`, off by default for plain-HTTP local dev); request body capped at `MAX_REQUEST_BODY_BYTES` (413). The nginx image adds the same headers plus `server_tokens off` for static/proxied responses. | Header tests in Phase 10 suite; nginx reviewed |
| F-14 | Unhandled exceptions could surface as raw 500s; no request correlation. | Medium | Global `Exception` handler returns `{"detail":"Internal server error"}` (no traceback/SQL), every response carries `X-Request-ID`, and 5xx/audit rows correlate by `request_id`. | Exception-handler tests, request-id tests |
| F-15 | Token in URL (WS) and raw `/api` profile endpoints encouraged unsafe handling. | Medium | WS token moved to a first-message auth frame (never in the URL); `GET /api/auth/me` returns the sanitized profile (id/username/role/flags) — never the token. | `ws.security.test.ts`, ws_check, Phase 10 tests |
| F-16 | Frontend ignored 401/403/429 — users saw silent failures or infinite retry loops. | Medium | `handleApiError` maps 401→logout+redirect, 403→`ACCESS DENIED` warning, 429→`RATE LIMITED` warning with `retryAfter`; WS `4401` renews-or-redirects; `RequireRole` blocks unauthorized routes before render. | `twinStore.test.ts`, `App.security.test.tsx`, `api.security.test.ts` |
| F-17 | Hardcoded demo credentials documented and always active. | Medium | Demo accounts stay documented in README for local development but `/api/auth/demo` returns **usernames + roles only (no passwords)**; demo users and self-service registration are disabled when `APP_ENV=production` (`DEMO_USERS_ENABLED`/`REGISTRATION_ENABLED` default false). | Phase 10 demo-endpoint tests, `Login.security.test.tsx` |
| F-18 | Containers ran as root; nginx on privileged port; no compose hardening. | Medium | Backend image creates non-root `twinsphere` user (uid 1000, owns `/app` and the `/data` SQLite volume mount); frontend nginx runs `USER nginx`, listens on **8080** (`pid /tmp/nginx.pid`), compose maps `3000:8080`; both services get `security_opt: no-new-privileges`; Postgres bound to `127.0.0.1` with required password; secrets required via `${VAR:?}`. | Dockerfile/nginx/compose review (build/run not executed — see limitations) |
| F-19 | No `.dockerignore` — `.git`, `.venv`, local `.env`, DB files could enter the build context. | Medium | Root and `frontend/.dockerignore` exclude `.git`, venvs, `node_modules`, `*.db`, `.env*`, tests, docs. | File review |
| F-20 | **PyJWT 2.10.1**: 21 known advisories (CVE range fixed in 2.15.0+). | High | Pinned `PyJWT==2.15.0` in `requirements.txt`; full suite re-run green on the new version. | `pip_audit -r requirements.txt` → *No known vulnerabilities found*; 239 pytest passed |
| F-21 | **pytest 8.3.4**: dev-only advisory (PYSEC-2026-1845). | Low (dev) | Dev dependencies split into `requirements-dev.txt`; upgraded to `pytest==9.0.3` + `pytest-asyncio==1.4.0`; `pip check` clean. | 239 pytest passed on pytest 9 |
| F-22 | npm: `react-router`/`react-router-dom` 2 × moderate advisories (open-redirect via backslash; SSR `deserializeErrors` constructor injection). | Low–Medium (accepted) | **Phase 11 deeper investigation**: installed `react-router-dom@6.30.6`. **GHSA-wrjc-x8rr-h8h6** (CVE-2025-68470 bypass, range >=6.0.0 <7.18.0): open redirect via backslash in `<Link to>`/`useNavigate` — not exploitable here because all `navigate()` / `<Link to>` targets are hardcoded internal paths or interpolate server-controlled building IDs (`/simulation?scenario=fire&building=${detail.id}`); no user/URL-query-controlled navigation exists. **GHSA-337j-9hxr-rhxg** (range >=6.4.0 <7.18.0): arbitrary constructor injection via `deserializeErrors()` in SSR hydration — not exploitable because TwinSphere is a client-only SPA served by nginx; no SSR, no server-side React Router, `deserializeErrors()` never called. **Decision**: accept both moderates. The only fix is `react-router-dom@7`, a breaking major (package renamed to `react-router`, Remix convergence, API shifts across the app). Proportional risk: two architecturally-unreachable moderates vs. a breaking upgrade. Upgrade path: migrate to v7 in a dedicated Phase. | `npm audit` output recorded; FE code review (no untrusted `navigate()`/`to` targets); no SSR present in deployment |
| F-23 | No security documentation / operator guidance. | Medium | This file plus `docs/SECURITY.md`, `docs/RBAC.md`, `docs/AUTHENTICATION.md`, `docs/AUDIT_LOGGING.md`; README Phase 10 section; `.env.example` extended with the full security contract. | Doc review |

---

## Dependency audit results

```text
# backend runtime (requirements.txt)
pip_audit --no-deps -r requirements.txt  →  No known vulnerabilities found

# backend dev (requirements-dev.txt: pytest 9.0.3, pytest-asyncio 1.4.0, pip-audit)
pip check                                →  No broken requirements found

# frontend (npm audit)
2 moderate — react-router (fix requires react-router-dom@7, breaking)  → accepted, see F-22
```

Not re-verified by running services: dependency upgrades were verified by the full
automated suites only (no external DAST/pentest was run).

---

## Verification

| Suite | Command | Result |
|---|---|---|
| Backend unit/integration (incl. 48 Phase 10 security tests) | `python -m pytest tests -q` | **239 passed** |
| Backend end-to-end API smoke | `python tests/smoke_api.py` | **192/192** |
| WebSocket suite (auth, channels, limits) | `python tests/ws_check.py` | **56/56** |
| Frontend (vitest, incl. security suites) | `npm run test` | **193 passed** |
| Frontend typecheck + production build | `npm run typecheck && npm run build` | clean |
| Runtime dependency audit | `pip_audit -r requirements.txt` | 0 known vulnerabilities |

---

## Residual risk & limitations

1. **Browser token storage.** The JWT lives in `localStorage` (classic SPA trade-off vs.
   refresh-token/cookie architecture). An XSS bug could steal it; mitigations are CSP,
   `nosniff`, dependency hygiene, and short-ish expiry (`JWT_EXPIRE_MINUTES`, default 720).
   Moving to `HttpOnly` cookie sessions + refresh tokens is the documented upgrade path.
2. **HSTS is off by default** (`HSTS_ENABLED=false`) because local development is plain
   HTTP. Enable it when serving over TLS behind a terminator.
3. **Rate limiting is in-memory and single-process.** Correct for the current single-
   worker deployment; a multi-replica deployment needs a shared (Redis) store.
4. **No session idle timeout** — only absolute token expiry + revocation on
   logout/password change. Acceptable for the current scope; listed as future work.
5. **Audit log retention is unbounded** — no automatic purge/TTL job yet. Add one before
   long-running production use.
6. **Docker images were not built/run** on this machine (no Docker available). The
   Dockerfiles, nginx config and compose file were reviewed statically and hardening is
   covered by review, not execution.
7. **No CI pipeline exists** in this repository — all verification above was run locally;
   wiring the suites into CI is recommended follow-up work.
8. **External penetration testing not performed.** This audit is a code/dependency review
   backed by automated tests, not a substitute for a professional pentest.
