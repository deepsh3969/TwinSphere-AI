"""Phase 11 observability — /api/system/metrics (safe, bounded counters)."""
from fastapi.testclient import TestClient

from app.main import app
from app.core import metrics as m

client = TestClient(app)


def _tok(username: str, password: str) -> str:
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(username: str, password: str) -> dict:
    return {"Authorization": f"Bearer {_tok(username, password)}"}


def test_metrics_endpoint_requires_auth():
    r = client.get("/api/system/metrics")
    assert r.status_code == 401


def test_metrics_snapshot_shape():
    h = _h("viewer", "viewer123")
    r = client.get("/api/system/metrics", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "uptime_s" in body and body["uptime_s"] >= 0
    assert isinstance(body["counters"], dict)


def test_http_requests_are_counted():
    h = _h("viewer", "viewer123")
    client.get("/health", headers=h)
    client.get("/health", headers=h)
    r = client.get("/api/system/metrics", headers=h)
    body = r.json()
    keys = [k for k in body["counters"] if k.startswith("http.GET./health.")]
    assert keys, "expected http.GET./health.* counter"
    total = sum(body["counters"][k] for k in keys)
    assert total >= 2


def test_sim_lifecycle_counters():
    h = _h("operator", "operator123")
    r = client.post("/api/simulations",
                    json={"scenario": "fire", "target_id": "eng"},
                    headers=h)
    sim_id = None
    if r.status_code == 201:
        sim_id = r.json()["id"]
        client.post(f"/api/simulations/{sim_id}/start", headers=h)
        client.post(f"/api/simulations/{sim_id}/reset", headers=h)
    mr = client.get("/api/system/metrics", headers=h)
    counters = mr.json()["counters"]
    assert "simulations.create.ok" in counters or "simulations.create.conflict" in counters
    # leave no active simulation behind so subsequent tests aren't blocked
    from app.services.demo import full_reset
    from app.services.state import get_state
    full_reset(get_state())


def test_ratelimit_block_counter():
    h = _h("viewer", "viewer123")
    from app.core.config import settings
    from app.core.ratelimit import _buckets, _lock, check
    # conftest keeps the limiter off for the suite; exercise it explicitly here.
    settings.RATE_LIMIT_ENABLED = True
    try:
        with _lock:
            import time as _t
            now = _t.time()
            _buckets["login|1.2.3.4"] = [now - 0.1] * 50
        blocked = False
        try:
            check("login", "1.2.3.4")
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException) and exc.status_code == 429:
                blocked = True
        finally:
            with _lock:
                _buckets.pop("login|1.2.3.4", None)
        assert blocked, "expected 429"
        mr = client.get("/api/system/metrics", headers=h)
        assert mr.json()["counters"].get("ratelimit.login.blocked", 0) >= 1
    finally:
        settings.RATE_LIMIT_ENABLED = False
