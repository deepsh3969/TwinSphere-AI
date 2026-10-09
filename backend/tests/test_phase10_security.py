"""Phase 10 §24 — authentication, authorization, rate limiting, audit and
WebSocket security tests.

Every scenario adapts the spec's checklist to this repository's architecture
(Bearer JWT + DB-backed principals + `require(permission)` RBAC).  No existing
test is weakened here — this file only adds coverage.
"""

import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import ratelimit
from app.core.audit import audit
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import ROLE_PERMISSIONS, create_token, hash_password, validate_password
from app.main import app
from app.models.entities import AuditLog, User
from app.services import bootstrap_admin

client = TestClient(app)


def _login(username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _tok(username: str, password: str) -> str:
    r = _login(username, password)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(username: str, password: str) -> dict:
    return {"Authorization": f"Bearer {_tok(username, password)}"}


def _delete_user(identifier: str) -> None:
    """Remove a user created by a Phase 10 test so session-wide seed stats
    (e.g. ``test_seed_statistics``) stay exact."""
    with SessionLocal() as db:
        row = db.query(User).filter(
            (User.id == identifier) | (User.username == identifier)).first()
        if row is not None:
            db.delete(row)
            db.commit()


ADMIN = {"Authorization": f"Bearer {create_token('u_admin', 'admin', 'ADMIN')}"}
OPERATOR = {"Authorization": f"Bearer {create_token('u_operator', 'operator', 'OPERATOR')}"}
ANALYST = {"Authorization": f"Bearer {create_token('u_analyst', 'analyst', 'ANALYST')}"}
VIEWER = {"Authorization": f"Bearer {create_token('u_viewer', 'viewer', 'VIEWER')}"}


# ------------------------------------------------------- 1-3 login outcomes

def test_login_success_returns_token_and_profile():
    r = _login("admin", "admin123")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "ADMIN"
    assert "password_hash" not in r.text


def test_login_invalid_password():
    r = _login("admin", "not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials"


def test_login_unknown_account_uniform_response():
    """User-enumeration resistance: unknown user and wrong password are
    byte-identical responses (§24.20)."""
    unknown = _login(f"ghost_{uuid.uuid4().hex[:8]}", "whatever123")
    wrong = _login("admin", "still-not-it")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


# ----------------------------------------------------------- 4-7 token edge

def _signed(payload: dict, secret: str = None, algorithm: str = "HS256") -> str:
    return jwt.encode(payload, secret or settings.JWT_SECRET, algorithm=algorithm)


def test_expired_token_rejected():
    now = int(time.time())
    token = _signed({"sub": "u_admin", "username": "admin", "role": "ADMIN",
                     "jti": uuid.uuid4().hex, "iss": settings.JWT_ISSUER,
                     "aud": settings.JWT_AUDIENCE, "ver": 0,
                     "iat": now - 7200, "exp": now - 60})
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Token expired"


def test_malformed_token_rejected():
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid token"


def test_invalid_signature_rejected():
    token = _signed({"sub": "u_admin", "username": "admin", "role": "ADMIN",
                     "jti": uuid.uuid4().hex, "iss": settings.JWT_ISSUER,
                     "aud": settings.JWT_AUDIENCE, "ver": 0,
                     "iat": int(time.time()), "exp": int(time.time()) + 600},
                    secret="some-other-secret")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_algorithm_rejected():
    token = _signed({"sub": "u_admin", "username": "admin", "role": "ADMIN",
                     "jti": uuid.uuid4().hex, "iss": settings.JWT_ISSUER,
                     "aud": settings.JWT_AUDIENCE, "ver": 0,
                     "iat": int(time.time()), "exp": int(time.time()) + 600},
                    algorithm="HS512")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_missing_authentication_401():
    for url in ("/api/analytics/overview", "/api/users", "/api/audit",
                "/api/simulations", "/api/auth/me"):
        assert client.get(url).status_code == 401, url


# ----------------------------------------------------- 7-9-10 role enforcement

def test_insufficient_permissions_403():
    checks = [
        (VIEWER, "post", "/api/simulations", {"scenario": "fire", "target_id": "eng"}),
        (VIEWER, "post", "/api/realtime/pause", None),
        (VIEWER, "get", "/api/users", None),
        (VIEWER, "get", "/api/audit", None),
        (ANALYST, "post", "/api/simulations", {"scenario": "fire", "target_id": "eng"}),
        (ANALYST, "post", "/api/ai/recommendations/rec_x/decision", {"decision": "ACCEPTED"}),
        (OPERATOR, "post", "/api/ai/analyze", {"question": "why?"}),
    ]
    for hdr, method, url, body in checks:
        if method == "post":
            resp = client.post(url, headers=hdr, json=body)
        else:
            resp = client.get(url, headers=hdr)
        assert resp.status_code == 403, (method, url, resp.status_code, resp.text[:120])


def test_token_role_claim_is_not_authoritative():
    """A VIEWER holding a token that *claims* ADMIN must still be a VIEWER:
    effective permissions come from the database (§5/§9)."""
    forged = create_token("u_viewer", "viewer", "ADMIN")
    r = client.get("/api/users", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 403


def test_register_cannot_escalate_role():
    name = f"p10reg{uuid.uuid4().hex[:6]}"
    try:
        r = client.post("/api/auth/register", json={
            "username": name, "email": f"{name}@t.local",
            "password": "Sup3rSecret!", "role": "ADMIN", "is_active": True})
        if r.status_code == 409:  # already seeded by an earlier run
            pytest.skip("username exists")
        assert r.status_code in (200, 201)
        assert r.json()["user"]["role"] == "VIEWER"
    finally:
        _delete_user(name)


def test_mass_assignment_ignored_on_user_create():
    suffix = uuid.uuid4().hex[:6]
    name = f"p10mass{suffix}"
    try:
        r = client.post("/api/users", headers=ADMIN, json={
            "username": name, "email": f"{name}@t.local",
            "password": "MassAssign1!",
            "role": "VIEWER", "id": "u_evil", "password_hash": "ignored",
            "token_version": 99, "is_active": True})
        assert r.status_code == 201, r.text
        user = r.json()["user"]
        assert user["role"] == "VIEWER"
        assert user["id"].startswith("u_") and user["id"] != "u_evil"
    finally:
        _delete_user(name)


# ------------------------------------------------------- 11-12 user admin

def test_role_update_requires_manage():
    assert client.patch("/api/users/u_viewer", json={"role": "ADMIN"},
                        headers=OPERATOR).status_code == 403
    assert client.patch("/api/users/u_viewer", json={"role": "ADMIN"},
                        headers=VIEWER).status_code == 403
    ok = client.patch("/api/users/u_viewer", json={"role": "VIEWER"}, headers=ADMIN)
    assert ok.status_code == 200


def test_last_admin_protection():
    demote = client.patch("/api/users/u_admin", json={"role": "OPERATOR"}, headers=ADMIN)
    assert demote.status_code == 409
    disable = client.patch("/api/users/u_admin", json={"is_active": False}, headers=ADMIN)
    assert disable.status_code == 409
    # integrity preserved
    me = client.get("/api/auth/me", headers=ADMIN)
    assert me.status_code == 200 and me.json()["role"] == "ADMIN"


def test_admin_cannot_disable_self():
    r = client.patch("/api/users/u_admin", json={"is_active": False}, headers=ADMIN)
    assert r.status_code == 409


def test_disabled_user_cannot_login_and_loses_sessions():
    name = f"p10dis{uuid.uuid4().hex[:6]}"
    uid = ""
    try:
        created = client.post("/api/users", headers=ADMIN, json={
            "username": name, "email": f"{name}@t.local",
            "password": "DisabledUser1!", "role": "OPERATOR"})
        assert created.status_code == 201, created.text
        uid = created.json()["user"]["id"]
        token = _tok(name, "DisabledUser1!")

        assert client.patch(f"/api/users/{uid}", json={"is_active": False},
                            headers=ADMIN).status_code == 200
        # correct password but disabled → 403; old token → 401
        assert _login(name, "DisabledUser1!").status_code == 403
        assert client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {token}"}).status_code == 401
        # re-enable so the session ends in a consistent state
        client.patch(f"/api/users/{uid}", json={"is_active": True}, headers=ADMIN)
        assert _login(name, "DisabledUser1!").status_code == 200
    finally:
        _delete_user(uid or name)


# -------------------------------------------------------- 13 rate limiting

def test_rate_limit_login_429():
    original_enabled = settings.RATE_LIMIT_ENABLED
    original_limit = settings.LOGIN_RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_ENABLED = True
    settings.LOGIN_RATE_LIMIT_PER_MINUTE = 3
    ratelimit.reset()
    try:
        codes = []
        last = None
        for _ in range(4):
            last = _login("admin", "definitely-wrong")
            codes.append(last.status_code)
        assert codes[:3] == [401, 401, 401], codes
        assert last.status_code == 429, codes
        assert last.headers.get("retry-after")
        assert "retry" in last.json()["detail"].lower()
    finally:
        settings.RATE_LIMIT_ENABLED = original_enabled
        settings.LOGIN_RATE_LIMIT_PER_MINUTE = original_limit
        ratelimit.reset()


def test_rate_limit_export_429():
    original_enabled = settings.RATE_LIMIT_ENABLED
    original_limit = settings.EXPORT_RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_ENABLED = True
    settings.EXPORT_RATE_LIMIT_PER_MINUTE = 1
    ratelimit.reset()
    try:
        first = client.get("/api/analytics/export?kind=summary", headers=OPERATOR)
        second = client.get("/api/analytics/export?kind=summary", headers=OPERATOR)
        assert first.status_code == 200
        assert second.status_code == 429
    finally:
        settings.RATE_LIMIT_ENABLED = original_enabled
        settings.EXPORT_RATE_LIMIT_PER_MINUTE = original_limit
        ratelimit.reset()


def test_rate_limit_never_429_when_disabled():
    # suite-wide posture: limiter off outside the two dedicated tests above
    for _ in range(5):
        assert _login("admin", "admin123").status_code == 200


# ------------------------------------------------------------ 14 CORS

def test_cors_allows_configured_origin_only():
    preflight = client.options("/api/auth/login", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"

    evil = client.options("/api/auth/login", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert evil.headers.get("access-control-allow-origin") in (None, ""), evil.headers


# ------------------------------------------------- 15-16 request validation

def test_login_identifier_and_password_bounds():
    long_name = "x" * 300
    r = client.post("/api/auth/login", json={"username": long_name, "password": "abc"})
    assert r.status_code == 422
    r2 = client.post("/api/auth/login", json={"username": "admin", "password": "y" * 300})
    assert r2.status_code == 422


def test_oversized_body_413():
    r = client.post("/api/auth/login",
                    content=b"{" + b"a" * (settings.MAX_REQUEST_BODY_BYTES + 1000) + b"}",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


def test_password_policy_validation():
    with pytest.raises(Exception) as exc:
        validate_password("short", "admin")
    assert getattr(exc.value, "status_code", None) == 400
    with pytest.raises(Exception):
        validate_password("admin", "admin")  # matches username
    with pytest.raises(Exception):
        validate_password("password", "someone")  # common


# ------------------------------------------------------- 17-19 audit trail

def test_audit_login_success_and_failure_recorded():
    _login("admin", "admin123")
    _login("admin", "wrong-password-x")
    with SessionLocal() as db:
        ok = (db.query(AuditLog).filter(AuditLog.action == "auth.login",
                                        AuditLog.outcome == "SUCCESS")
              .order_by(AuditLog.id.desc()).first())
        bad = (db.query(AuditLog).filter(AuditLog.action == "auth.login",
                                         AuditLog.outcome == "DENIED")
               .order_by(AuditLog.id.desc()).first())
        assert ok is not None and ok.actor == "admin"
        assert bad is not None and "Invalid credentials" in bad.detail
        assert "wrong-password-x" not in bad.detail  # passwords never stored


def test_audit_access_restriction_and_scopes():
    assert client.get("/api/audit", headers=VIEWER).status_code == 403
    op = client.get("/api/audit?page_size=5", headers=OPERATOR)
    adm = client.get("/api/audit?page_size=5", headers=ADMIN)
    assert op.status_code == 200 and op.json()["scope"] == "operational"
    assert adm.status_code == 200 and adm.json()["scope"] == "full"
    # operational subset excludes auth/authz/admin internals
    actions = {r["action"] for r in op.json()["records"]}
    assert not any(a.startswith(("auth.", "authz.", "admin.")) for a in actions), actions
    full_actions = {r["action"] for r in adm.json()["records"]}
    assert any(a.startswith(("auth.", "admin.", "authz.")) for a in full_actions), full_actions


def test_audit_secret_redaction():
    with SessionLocal() as db:
        audit(db, "test.redaction", detail="changed password=hunter2 token=abc.def")
        row = (db.query(AuditLog).filter(AuditLog.action == "test.redaction")
               .order_by(AuditLog.id.desc()).first())
        assert row is not None
        assert "hunter2" not in row.detail and "abc.def" not in row.detail
        assert "redacted" in row.detail


def test_audit_append_only_no_write_endpoints():
    audit_routes = [(tuple(sorted(r.methods)), r.path) for r in app.routes
                    if getattr(r, "path", "").startswith("/api/audit")]
    assert audit_routes, "audit API missing"
    for methods, path in audit_routes:
        assert methods == ("GET",), (methods, path)


# --------------------------------------------------- 20 user enumeration
# (covered by test_login_unknown_account_uniform_response)

# ----------------------------------------------------- 21-23 WebSocket

@pytest.fixture()
def ws_timeout():
    original = settings.WS_AUTH_TIMEOUT_S
    settings.WS_AUTH_TIMEOUT_S = 0.4
    yield
    settings.WS_AUTH_TIMEOUT_S = original


def test_ws_rejects_query_string_token():
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=abc"):
            pass


def test_ws_rejects_unauthenticated(ws_timeout):
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive()
        assert msg["type"] == "websocket.close"


def test_ws_rejects_invalid_token(ws_timeout):
    with client.websocket_connect("/ws") as ws:
        ws.send_text('{"type":"auth","token":"garbage"}')
        msg = ws.receive()
        assert msg["type"] == "websocket.close"


def test_ws_valid_token_receives_state():
    token = _tok("viewer", "viewer123")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(__import__("json").dumps({"type": "auth", "token": token}))
        first = ws.receive_json()
        assert first["type"] == "state"


def _recv_until(ws, pred, limit=8):
    for _ in range(limit):
        frame = ws.receive_json()
        if pred(frame):
            return frame
    return None


def test_ws_channel_authorization():
    token = _tok("viewer", "viewer123")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(__import__("json").dumps({"type": "auth", "token": token}))
        ws.receive_json()  # state
        ws.send_text(__import__("json").dumps({"type": "subscribe", "channel": "admin"}))
        sub = _recv_until(ws, lambda f: f.get("type") == "subscription")
        assert sub and sub["ok"] is False, sub


def test_ws_invalid_messages():
    token = _tok("viewer", "viewer123")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(__import__("json").dumps({"type": "auth", "token": token}))
        ws.receive_json()
        ws.send_text("not json at all")
        err = _recv_until(ws, lambda f: f.get("type") == "error")
        assert err and err["error"] == "invalid_json", err
        ws.send_text(__import__("json").dumps({"type": "mystery"}))
        err2 = _recv_until(ws, lambda f: f.get("type") == "error")
        assert err2 and err2["error"] == "unknown_type", err2


# ------------------------------------------------------ 24 password change

def test_password_change_flow_and_revocation():
    name = f"p10pw{uuid.uuid4().hex[:6]}"
    try:
        created = client.post("/api/users", headers=ADMIN, json={
            "username": name, "email": f"{name}@t.local",
            "password": "FirstPass123", "role": "VIEWER"})
        assert created.status_code == 201, created.text
        old_token = _tok(name, "FirstPass123")
        h = {"Authorization": f"Bearer {old_token}"}

        bad = client.post("/api/auth/change-password",
                          json={"current_password": "WrongPass1", "new_password": "NextPass123"},
                          headers=h)
        assert bad.status_code == 400
        weak = client.post("/api/auth/change-password",
                           json={"current_password": "FirstPass123", "new_password": "abc"},
                           headers=h)
        assert weak.status_code == 422  # schema minimum
        ok = client.post("/api/auth/change-password",
                         json={"current_password": "FirstPass123", "new_password": "NextPass123"},
                         headers=h)
        assert ok.status_code == 200
        # old session revoked, fresh token issued, old password dead
        assert client.get("/api/auth/me", headers=h).status_code == 401
        fresh = {"Authorization": f"Bearer {ok.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=fresh).status_code == 200
        assert _login(name, "FirstPass123").status_code == 401
        assert _login(name, "NextPass123").status_code == 200
    finally:
        _delete_user(name)


def test_logout_revokes_only_presented_token():
    first = _tok("operator", "operator123")
    second = _tok("operator", "operator123")
    fh = {"Authorization": f"Bearer {first}"}
    assert client.post("/api/auth/logout", headers=fh).status_code == 200
    assert client.get("/api/auth/me", headers=fh).status_code == 401
    sh = {"Authorization": f"Bearer {second}"}
    assert client.get("/api/auth/me", headers=sh).status_code == 200  # sibling unaffected


# --------------------------------------------------- 26 production secrets

def test_production_secret_validation():
    from app.core import config

    original = (settings.IS_PRODUCTION, settings.JWT_SECRET, settings.CORS_ORIGINS)
    try:
        settings.IS_PRODUCTION = True
        settings.JWT_SECRET = "dev-only-change-me-in-production"
        with pytest.raises(RuntimeError):
            config.validate_security_config()
        settings.JWT_SECRET = "x" * 32  # long + non-dev: secret checks pass
        settings.CORS_ORIGINS = ["*"]  # wildcard must still be refused
        with pytest.raises(RuntimeError):
            config.validate_security_config()
    finally:
        settings.IS_PRODUCTION, settings.JWT_SECRET, settings.CORS_ORIGINS = original


def test_wildcard_cors_refused_at_startup():
    from app.core import config

    cors = settings.CORS_ORIGINS
    try:
        settings.CORS_ORIGINS = ["*"]
        with pytest.raises(RuntimeError):
            config.validate_security_config()
    finally:
        settings.CORS_ORIGINS = cors


# ------------------------------------------------ 27 AI advisory invariant

def test_ai_recommendations_cannot_drive_operations():
    """Phase 8 contract + Phase 10 §8: recommendations never execute actions;
    accepting is an explicit, permission-checked human action."""
    # non-privileged roles cannot decide
    for hdr in (VIEWER, ANALYST):
        r = client.post("/api/ai/recommendations/rec_x/decision",
                        json={"decision": "ACCEPTED"}, headers=hdr)
        assert r.status_code == 403, (r.status_code, r.text[:100])
    # AI cannot be used to trigger sim control without simulate permission
    for hdr in (VIEWER, ANALYST):
        assert client.post("/api/simulations", headers=hdr,
                           json={"scenario": "fire", "target_id": "eng"}).status_code == 403
        assert client.post("/api/realtime/reset", headers=hdr).status_code == 403
    # the analyst analysis trigger itself is permission-checked (analyze)
    assert client.post("/api/ai/analyze", json={}, headers=VIEWER).status_code == 403
    # analyst positive control: ANALYST can analyze but never apply
    assert client.post("/api/ai/analyze", json={}, headers=ANALYST).status_code in (200, 429, 500)


# --------------------------------------------- 28-30 action authorizations

def test_export_authorization():
    for url in ("/api/analytics/export?kind=summary",
                "/api/history/export?kind=incidents"):
        assert client.get(url, headers=VIEWER).status_code == 403, url
        assert client.get(url, headers=OPERATOR).status_code == 200, url
        assert client.get(url, headers=ANALYST).status_code == 200, url
    inc = client.get("/api/history/incidents", headers=VIEWER).json()
    if inc.get("incidents"):
        iid = inc["incidents"][0]["id"]
        assert client.get(f"/api/history/incidents/{iid}/export",
                          headers=VIEWER).status_code == 403


def test_simulation_control_authorization():
    forbidden = [
        ("POST", "/api/simulations", {"scenario": "fire", "target_id": "eng"}),
        ("POST", "/api/simulations/sim_seed_fire/start", None),
        ("POST", "/api/simulations/sim_seed_fire/pause", None),
        ("POST", "/api/simulations/sim_seed_fire/reset", None),
        ("POST", "/api/simulations/sim_seed_fire/recover", None),
    ]
    for hdr in (VIEWER, ANALYST):
        for method, url, body in forbidden:
            resp = getattr(client, method.lower())(url, headers=hdr, json=body)
            assert resp.status_code == 403, (url, resp.status_code)


def test_recovery_and_route_authorization():
    for hdr in (VIEWER, ANALYST):
        assert client.post("/api/simulations/sim_seed_fire/recover",
                           headers=hdr).status_code == 403
        assert client.post("/api/routes/calculate",
                           json={"origin": "eng", "destination": "exit_n"},
                           headers=hdr).status_code == 403
        # GET with a mutating query parameter is gated on `apply`
        r = client.get("/api/routes?recompute=true", headers=hdr)
        assert r.status_code == 403, r.status_code


def test_read_permissions_still_work_for_viewer():
    """Regression guard: hardening must not break legitimate read workflows."""
    for url in ("/api/analytics/overview", "/api/history/incidents",
                "/api/campus", "/api/sensors", "/api/realtime/status"):
        assert client.get(url, headers=VIEWER).status_code == 200, url


# ------------------------------------------------------------- bootstrap

def test_bootstrap_refuses_when_admin_exists():
    with pytest.raises(SystemExit) as exc:
        bootstrap_admin.bootstrap("newboss", "VeryStrongPass99")
    assert "already exists" in str(exc.value)


def test_bootstrap_refuses_weak_password_before_any_write():
    with pytest.raises(SystemExit) as exc:
        bootstrap_admin.bootstrap("weakling", "abc")
    assert "at least 8" in str(exc.value)


def test_bootstrap_cli_requires_password_without_tty(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert bootstrap_admin.main(["--username", "someadmin"]) == 2


# -------------------------------------------------------- security headers

def test_security_headers_present():
    r = client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert r.headers.get("permissions-policy")
    assert r.headers.get("x-request-id")


def test_unexpected_error_does_not_leak_exception_class():
    import asyncio

    from fastapi import Request
    from fastapi.responses import JSONResponse

    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [],
             "query_string": b"", "app": app}
    req = Request(scope)
    resp = asyncio.new_event_loop().run_until_complete(
        app.exception_handlers[Exception](req, RuntimeError("db-password=super-secret")))
    assert isinstance(resp, JSONResponse)
    body = resp.body.decode()
    assert "super-secret" not in body and "RuntimeError" not in body
    assert "Internal server error" in body


def test_no_secret_material_in_auth_responses():
    r = _login("admin", "admin123")
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    blob = r.text + me.text
    assert "password_hash" not in blob
    assert settings.JWT_SECRET not in blob
    assert "pbkdf2$" not in blob and "$argon2" not in blob
