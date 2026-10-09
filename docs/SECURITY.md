# TwinSphere AI — Security Architecture

How TwinSphere authenticates, authorizes, limits, records and ships securely.
Related: [SECURITY_AUDIT.md](SECURITY_AUDIT.md) (findings → fixes → verification),
[RBAC.md](RBAC.md), [AUTHENTICATION.md](AUTHENTICATION.md), [AUDIT_LOGGING.md](AUDIT_LOGGING.md).

## Security model (defense in depth)

```text
1. Configuration gate      validate_security_config() — refuses startup on dev secrets /
                           wildcard CORS when APP_ENV=production; compose requires JWT_SECRET
2. Transport               CORS allow-list (explicit origins), security headers middleware,
                           X-Request-ID correlation, request body cap (413), optional HSTS
3. Rate limiting           per-category fixed windows (login/register/export/AI/sim/admin/ws/general)
4. Authentication          Bearer JWT (HS256, iss/aud/exp/jti), Argon2id passwords,
                           server-side revocation (jti deny-list + token_version)
5. Authorization           central RBAC matrix + require(permission) on every protected route;
                           WS channels gated the same way; frontend RequireRole mirrors it
6. Audit                   every login/logout/register/password/role/admin/authz-denied and
                           operational mutation recorded with actor, outcome, IP, request-id
7. Deployment              non-root containers, nginx on 8080, no-new-privileges,
                           loopback-only Postgres, .dockerignore, production env defaults
```

## Controls at a glance

| Control | Where | Knob |
|---|---|---|
| JWT secret validation | `backend/app/core/config.py` (`validate_security_config`) | `JWT_SECRET`, `APP_ENV` |
| JWT issue/verify/revocation | `backend/app/core/security.py` | `JWT_EXPIRE_MINUTES` (720), `JWT_ISSUER`, `JWT_AUDIENCE` |
| Password hashing (Argon2id, legacy PBKDF2 verify+rehash) | `core/security.py` | — |
| Password policy (≥8, ≤128, ≠username, not common) | `core/security.py::validate_password` | — |
| RBAC matrix | `core/security.py::ROLE_PERMISSIONS`, `require()` | see [RBAC.md](RBAC.md) |
| Rate limits | `core/ratelimit.py` | `RATE_LIMIT_ENABLED`, `*_RATE_LIMIT_PER_MINUTE` |
| Security headers + body cap + request-id | `app/main.py` middleware | `MAX_REQUEST_BODY_BYTES` (1 MB), `HSTS_ENABLED`, `SECURITY_HEADERS_ENABLED` |
| CORS allow-list (wildcard refused) | `app/main.py` + config validation | `CORS_ORIGINS` |
| Generic 500 + no stack leaks | `app/main.py` exception handler | — |
| WebSocket auth handshake + channel ACL + revalidation | `app/websocket/manager.py`, `app/main.py` | `WS_AUTH_TIMEOUT_S`, `WS_RATE_LIMIT_PER_MINUTE` |
| Audit trail | `core/audit.py`, `routes_audit.py`, UI `/admin/audit` | see [AUDIT_LOGGING.md](AUDIT_LOGGING.md) |
| User administration | `routes_users.py`, UI `/admin/users` | ADMIN only |
| Demo/registration posture | `routes_auth.py`, config | `DEMO_USERS_ENABLED`, `REGISTRATION_ENABLED` (both false under production) |
| Non-root images, hardened nginx/compose | `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.yml` | `${JWT_SECRET:?}`, `${POSTGRES_PASSWORD:?}` |

## Frontend posture

- Token stored in `localStorage` (documented residual risk — see audit §limitations);
  never placed in URLs (WS auth is a first message, not a query parameter).
- Boot revalidates the session via `GET /api/auth/me`; 401 → login redirect, 403 →
  `ACCESS DENIED` warning, 429 → `RATE LIMITED` warning (`Retry-After` respected).
- `/admin/users` and `/admin/audit` are wrapped in `RequireRole`; the Administration nav
  section renders only for roles that can reach those routes.
- The login page fetches `/api/auth/demo` for **usernames only** in development; passwords
  are documented in README's Demo accounts table.

## Production deployment checklist

1. `APP_ENV=production` (compose default).
2. `JWT_SECRET` — unique, ≥32 chars, from a secrets manager (`compose` refuses to start without it).
3. `CORS_ORIGINS` — explicit origins only (wildcard fails startup).
4. `DEMO_USERS_ENABLED=false` / `REGISTRATION_ENABLED=false` (production defaults) or
   bootstrap the first admin explicitly:
   ```powershell
   $env:BOOTSTRAP_ADMIN_PASSWORD = "<strong-password>"
   python -m app.services.bootstrap_admin --username admin --email admin@example.com
   ```
   (the CLI refuses to run while `JWT_SECRET` is the development default).
5. Serve behind TLS; then set `HSTS_ENABLED=true`.
6. If exposing multiple replicas: replace the in-memory rate limiter with a shared store.
7. Rotate `JWT_SECRET` knowing it invalidates all outstanding tokens (intended).

## Quick verification

```powershell
cd backend
.venv\Scripts\python -m pytest tests -q          # includes 48 security tests → 239 passed
.venv\Scripts\python tests\smoke_api.py          # 192/192 (live server)
.venv\Scripts\python tests\ws_check.py           # 56/56 (live server)
cd ..\frontend && npm run test                   # includes security suites → 193 passed
```
