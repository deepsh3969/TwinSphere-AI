# TwinSphere AI — Audit Logging

Every security-relevant action and control-plane mutation is written to the
`audit_logs` table by `backend/app/core/audit.py`, queried through a read-only API and
inspected in the **Administration → Audit Log** UI.

## Record schema (`audit_logs`)

| Column | Content |
|---|---|
| `id`, `created_at` | sequence + UTC timestamp (indexed) |
| `action` | dotted event name, e.g. `auth.login`, `authz.denied`, `admin.role_change` (indexed) |
| `outcome` | `SUCCESS` \| `FAILURE` \| `DENIED` (indexed) |
| `actor` | username (`"system"` for engine events) |
| `user_id` | actor's user id when known |
| `entity`, `entity_type`, `entity_id` | what was acted on (e.g. `user` / user id) |
| `ip_address`, `detail` | client IP + structured JSON detail (**redacted**) |
| `request_id` | correlates with the `X-Request-ID` header on the same request (indexed) |

## Action catalog

| Family | Actions | Emitted on |
|---|---|---|
| `auth.*` | `auth.login` (SUCCESS/FAILURE), `auth.logout`, `auth.register`, `auth.password_change` | authentication lifecycle |
| `authz.*` | `authz.denied` | any `require()` rejection — includes the permission, actor and path |
| `admin.*` | `admin.user_create`, `admin.role_change`, `admin.user_disable`, `admin.password_reset` | user administration |
| `realtime.*` | `realtime.start/pause/resume/reset/speed` | simulation control (`simulate`) |
| `simulation.*` | `simulation.start/pause/resume/reset/recover`, `simulation.create` | scenario engine |
| `demo.*` | `demo.reset`, `demo.hard_reset` | demo resets (`reset`) |
| `recommendation.*`, `incident.*`, `route.*`, `settings.*`, `analyst.*` | apply/create/resolve/calculate/update/decision | other controlled mutations |

Read-only GETs are intentionally **not** audited (noise); every state change is.

## Guarantees & redaction

- **Append-only surface:** the audit API exposes only `GET` operations — there is no
  endpoint or UI path to edit or delete audit rows.
- **Redaction:** `detail` values are JSON-serialized through a redactor that masks
  keys matching password/token/secret/authorization patterns
  (`core/audit.py::redact`); no plaintext password, token or cookie ever reaches the
  table (asserted by tests).
- **Denials are events:** failed logins, forbidden calls and rate-limit hits are
  recorded with `FAILURE`/`DENIED` outcomes — absence of an action is therefore
  meaningful.
- **Correlation:** `request_id` links audit rows to API responses and 500s.

## Query API (`/api/audit`, read-only)

| Endpoint | Access | Notes |
|---|---|---|
| `GET /api/audit` | `audit` permission | filters: `q` (free text over actor/action/entity/request id), `action`, `outcome`, `date_from`/`date_to`, `page`/`page_size`; newest first, paginated |
| `GET /api/audit/actions` | `audit` permission | distinct action names for the filter dropdown |

**Scope rule:** callers without `manage` (i.e. `OPERATOR`) receive only the operational
subset — rows whose action starts with `auth.`, `authz.` or `admin.` are excluded.
ADMIN sees everything. See [RBAC.md](RBAC.md).

## UI

`/admin/audit` (ADMIN/OPERATOR): filter bar (text, action, outcome, date range),
scope badge (FULL vs OPERATIONAL), table of time · actor · action · outcome · entity ·
request id, pagination. Covered by `frontend/src/AuditLog` tests and backend Phase 10
tests.

## Retention

Rows accumulate indefinitely — **no automatic purge exists yet** (documented residual
limitation in [SECURITY_AUDIT.md](SECURITY_AUDIT.md)). For long-running production
deployments, add a TTL/archival job before go-live.
