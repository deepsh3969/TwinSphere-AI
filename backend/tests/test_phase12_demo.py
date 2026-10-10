"""Phase 12 — deterministic demo mode: repeatability, isolation, authz, recovery."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.state import get_state
from app.services.demo import full_reset
from app.services import demo_runner

client = TestClient(app)


def _tok(u: str, p: str) -> str:
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(u: str, p: str) -> dict:
    return {"Authorization": f"Bearer {_tok(u, p)}"}


@pytest.fixture(scope="module")
def admin():
    return _h("admin", "admin123")


@pytest.fixture(scope="module")
def operator():
    return _h("operator", "operator123")


@pytest.fixture(scope="module")
def viewer():
    return _h("viewer", "viewer123")


def test_demo_script_endpoint(viewer):
    r = client.get("/api/demo/script", headers=viewer)
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert len(steps) >= 10
    titles = [s["title"] for s in steps]
    assert any("Fire" in t for t in titles)


def test_demo_status_idle_by_default(viewer):
    r = client.get("/api/demo/status", headers=viewer)
    assert r.status_code == 200
    assert r.json()["status"] == "idle"


def test_demo_run_requires_reset_permission(viewer):
    r = client.post("/api/demo/run", headers=viewer)
    assert r.status_code == 403


def test_demo_run_and_complete(operator, viewer):
    r = client.post("/api/demo/run", headers=operator)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["step_index"] >= 10
    assert any("completed" in e for e in body["log"])
    st = client.get("/api/system/status", headers=viewer).json()
    assert st["status"] == "NORMAL"
    full_reset(get_state())


def test_demo_run_is_repeatable(operator, viewer):
    r1 = client.post("/api/demo/run", headers=operator)
    assert r1.status_code == 200
    m1 = client.get("/api/system/status", headers=viewer).json()["metrics"]
    full_reset(get_state())
    r2 = client.post("/api/demo/run", headers=operator)
    assert r2.status_code == 200
    m2 = client.get("/api/system/status", headers=viewer).json()["metrics"]
    assert m1.get("buildings") == m2.get("buildings")
    assert m1.get("zones") == m2.get("zones")
    full_reset(get_state())


def test_demo_double_start_conflicts(operator):
    demo_runner._current = {"id": "x", "step_index": 1, "status": "running",
                            "started_at": 0.0, "log": []}
    try:
        r = client.post("/api/demo/run", headers=operator)
        assert r.status_code == 409
    finally:
        demo_runner._current = None


def test_demo_stop_is_idempotent(operator):
    r1 = client.post("/api/demo/stop", headers=operator)
    assert r1.status_code == 200
    r2 = client.post("/api/demo/stop", headers=operator)
    assert r2.status_code == 200
    assert r2.json()["status"] == "idle"


def test_demo_reset_does_not_delete_users(operator, admin):
    before = client.get("/api/users", headers=admin).json()
    client.post("/api/demo/reset", headers=operator)
    after = client.get("/api/users", headers=admin).json()
    assert before == after


def test_demo_reset_does_not_delete_audit(operator, admin):
    before = client.get("/api/audit?limit=5", headers=admin).json()["records"]
    client.post("/api/demo/reset", headers=operator)
    after = client.get("/api/audit?limit=5", headers=admin).json()["records"]
    assert len(after) >= len(before)


def test_demo_reset_requires_reset_permission(viewer):
    r = client.post("/api/demo/reset", headers=viewer)
    assert r.status_code == 403


def test_demo_hard_reset_requires_manage(operator, admin):
    r = client.post("/api/demo/hard-reset", headers=operator)
    assert r.status_code == 403
    r2 = client.post("/api/demo/hard-reset", headers=admin)
    assert r2.status_code == 200
    full_reset(get_state())
