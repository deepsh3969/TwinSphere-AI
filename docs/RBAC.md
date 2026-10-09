# TwinSphere AI — RBAC (Role-Based Access Control)

Roles and permissions are defined **once**, centrally, in
`backend/app/core/security.py` (`ROLE_PERMISSIONS`) and enforced by the
`require(permission)` FastAPI dependency. The frontend mirrors the same roles for route
and navigation gating (`RequireRole` in `app/src/App.tsx`, `adminNav` in `AppShell`).

## Roles

| Role | Intent | Default for |
|---|---|---|
| `ADMIN` | Full platform control incl. user administration and complete audit | bootstrap admin, demo `admin` |
| `OPERATOR` | Run the facility: simulation controls, apply, exports, operational audit | demo `operator` |
| `ANALYST` | Read + AI analysis + exports; no operational control | demo `analyst` |
| `VIEWER` | Read-only dashboards and exports of what they can see | **self-service registration** |

`ROLES = ["ADMIN", "OPERATOR", "ANALYST", "VIEWER"]` — any other value is rejected at
user creation, role change, and registration (no free-string roles).

## Permission matrix

| Permission | Meaning | ADMIN | OPERATOR | ANALYST | VIEWER |
|---|---|:-:|:-:|:-:|:-:|
| `read` | Read telemetry, campus, analytics, history, AI, dashboards | ✔ | ✔ | ✔ | ✔ |
| `simulate` | Start/pause/resume/reset/-speed live simulation & demo controls | ✔ | ✔ | · | · |
| `apply` | Apply recommendations / control-plane mutations | ✔ | ✔ | · | · |
| `analyze` | Trigger AI analysis & analyst decisions | ✔ | · | ✔ | · |
| `export` | CSV exports | ✔ | ✔ | ✔ | · |
| `reset` | Demo/hard resets | ✔ | ✔ | · | · |
| `audit` | Read the audit log (**operational subset** for non-`manage` roles — see below) | ✔ | ✔ | · | · |
| `manage` | User administration (create/update/disable/reset/role change) + full audit | ✔ | · | · | · |

## Special rules

- **Operational audit subset.** `OPERATOR` holds `audit` but not `manage`; the audit API
  filters out `auth.*`, `authz.*` and `admin.*` action families for anyone without
  `manage` (`routes_audit.py`) — operators see day-to-day operational events, only
  admins see authentication and account-management events.
- **Registration always yields `VIEWER`** (`routes_auth.py`), regardless of any client
  input; only `manage` may create users with other roles or change roles.
- **Self-protection.** Admins cannot disable themselves or demote their own role in a
  way that strands the last administrator (validated in `routes_users.py`).
- **Password reset is one-time plaintext.** `POST /api/users/{id}/reset-password`
  returns a generated password exactly once (ADMIN only); it is never recoverable later.

## Enforcement points

| Layer | Mechanism |
|---|---|
| REST | `dependencies=[require("…")]` per route (e.g. `routes_realtime.py` → `simulate`, `routes_users.py` → `manage`, `routes_audit.py` → `audit`) |
| Denials | HTTP 403 `{"detail":"Forbidden"}` + `authz.denied` audit row with actor, permission, path |
| WebSocket | subscriptions gated per channel: `state` requires `read`, `admin` requires `manage`; unauthenticated clients never register (Phase 10 handshake) |
| Frontend routes | `/admin/users` → ADMIN only; `/admin/audit` → ADMIN/OPERATOR; unauthorized access redirects to a safe route with a warning toast |
| Frontend nav | Administration section renders only for roles that may reach those routes |

## Examples

```powershell
# ANALYST tries to start the simulation → 403 + audit row
curl -X POST http://127.0.0.1:8000/api/realtime/start -H "Authorization: Bearer $ANALYST_TOKEN"
# {"detail":"Forbidden"}

# VIEWER tries to list users → 403 (manage required)
curl http://127.0.0.1:8000/api/users -H "Authorization: Bearer $VIEWER_TOKEN"

# OPERATOR reads the audit log → operational actions only (auth.*/authz.*/admin.* hidden)
curl http://127.0.0.1:8000/api/audit -H "Authorization: Bearer $OPERATOR_TOKEN"
```

Coverage: the full matrix (each role × representative allowed/denied routes) is asserted
in `backend/tests/test_phase10_security.py`; login/logout/401 flows are covered by
`tests/smoke_api.py` and `frontend/src/App.security.test.tsx`.
