# TwinSphere AI — Authentication

Bearer-token authentication for the REST API and the WebSocket stream, with Argon2id
password storage, server-side revocation and an admin bootstrap path.
See [SECURITY.md](SECURITY.md) for the full model and [RBAC.md](RBAC.md) for what an
authenticated identity is allowed to do.

## Identity model

`users` table (`backend/app/models/entities.py`):

| Column | Purpose |
|---|---|
| `id` (uuid) | `sub` claim of the JWT |
| `username` / `email` | unique login identity / contact |
| `password_hash` | Argon2id (or legacy `pbkdf2$…`, rehashed on next successful login) |
| `role` | `ADMIN \| OPERATOR \| ANALYST \| VIEWER` (whitelist, never free text) |
| `is_active` | disabled accounts fail authentication immediately |
| `last_login_at`, `password_changed_at` | lifecycle timestamps (audited) |
| `token_version` | bumped on password change / role change / disable → invalidates every outstanding token for that user |

## Endpoints (`/api/auth`)

| Method & path | Auth | Rate limit | Notes |
|---|---|---|---|
| `POST /login` `{username,password}` | public | 20/min per **IP** and per **IP+username** | returns `{access_token, token_type, user}`; failure is a generic 401 (no user enumeration); updates `last_login_at`, audits `auth.login` |
| `POST /register` `{username,email,password}` | public (if `REGISTRATION_ENABLED`) | 5/min | always creates `VIEWER`; audits `auth.register` |
| `POST /logout` | Bearer | general | revokes the presented `jti` (deny-list), audits `auth.logout` |
| `GET /me` | Bearer | general | sanitized profile `{id,username,role,is_active,…}` — **never** returns the token |
| `POST /change-password` `{current_password,new_password}` | Bearer | general | verifies current, enforces policy, bumps `token_version`, issues a fresh token for the caller, audits `auth.password_change` |
| `GET /demo` | public (if `DEMO_USERS_ENABLED`) | general | **usernames + roles only**, no passwords (production: endpoint disabled) |
| `GET /roles` | Bearer | general | role → permission map for the frontend |

User administration (ADMIN) lives under `/api/users` — see [RBAC.md](RBAC.md).

## Token lifecycle

- **Issued:** `create_token()` — compact JWT, HS256, `JWT_SECRET`, claims:
  `sub` (user id), `username`, `role`, `tv` (`token_version`), `jti`, `iss`
  (`twinsphere`), `aud` (`twinsphere-api`), `iat`, `exp` (`JWT_EXPIRE_MINUTES`, default
  720 min = 12 h).
- **Validated on every request** (`authenticate_token`): signature → `iss`/`aud` →
  `exp` → `jti` not in `revoked_tokens` → user exists **and** `is_active` →
  `tv == user.token_version`. Any failure → 401.
- **Revoked:**
  - logout → `jti` inserted into `revoked_tokens` (rows expire naturally with the token);
  - password change / role change / disable → `token_version` bumped (kills *all* of the
    user's tokens at once).
- **WebSocket:** token is never in the URL. The client sends
  `{"type":"auth","token"}` as its first frame within `WS_AUTH_TIMEOUT_S`
  (0.4 s in tests); a bad/expired/revoked token closes with **4401** before any state is
  exposed, and tokens are revalidated periodically (60 s) while connected.

## Password storage & policy

- **Argon2id** via `argon2-cffi` (`hash_password` / `verify_password`); legacy PBKDF2
  hashes (`pbkdf2$…`) continue to verify and are upgraded transparently
  (`needs_rehash`) after a successful login.
- `validate_password()` — enforced on register, create-user, change-password, reset:
  length 8–128, must differ from the username, must not be a common password.
  Violations return HTTP 400 with the specific reason.

## Rate limiting

Auth-sensitive buckets (see `core/ratelimit.py`): login 20/min (dual-keyed by IP and
IP+username so one account cannot be sprayed from many IPs unnoticed, nor one IP
enumerate accounts), register 5/min. Exceeding → 429 + `Retry-After`.
Set `RATE_LIMIT_ENABLED=false` only for tests.

## Admin bootstrap

First administrator for a fresh environment (no demo accounts):

```powershell
$env:BOOTSTRAP_ADMIN_PASSWORD = "<strong-password>"   # or interactive prompt
cd backend
.venv\Scripts\python -m app.services.bootstrap_admin --username admin --email admin@example.com
```

Safety rails: refuses to run while `JWT_SECRET` is the development default; enforces the
same password policy; exits non-zero (`SystemExit`) with a clear message on any failure.

## Demo posture (local development only)

The four demo accounts (README → *Demo accounts*) exist only when
`DEMO_USERS_ENABLED=true` (the default outside production). The login page's
**DEMO — local development** chip fills a username from `GET /api/auth/demo`; passwords
are documented in the README, never returned by the API. Both demo users and
self-service registration are disabled automatically under `APP_ENV=production`.
