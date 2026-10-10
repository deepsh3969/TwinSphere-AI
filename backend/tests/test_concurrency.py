"""Phase 11 — concurrency, race-condition and consistency regression (§5).

Verifies the single-active-simulation invariant under real thread concurrency:
  * concurrent creates → exactly one 201, others 409 (TOCTOU regression test,
    deterministically orchestrated via a spy lock + gated engine call)
  * concurrent lifecycle transitions (pause/resume burst) → valid status codes
    only, engine event counts matching the 200s, consistent final state
  * concurrent reads → all 200 with stable payload shapes
  * create over a COMPLETED simulation stays allowed under concurrency

Deterministic by design: the race window is opened with a threading.Event gate
around the engine call (no sleeps for correctness; a SpyLock handshake detects
exactly when the second request reaches the critical section).
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from fastapi.testclient import TestClient

from app.api import routes_simulations as rs_mod
from app.main import app
from app.services import simulation_engine as simeng
from app.services.demo import full_reset
from app.services.risk_engine import compute_risk
from app.services.state import get_state

client = TestClient(app)


@lru_cache(maxsize=1)
def _hdr() -> dict:
    r = client.post("/api/auth/login",
                    json={"username": "operator", "password": "operator123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tick(seconds: float, step: float = 10.0) -> None:
    st = get_state()
    elapsed = 0.0
    while elapsed < seconds:
        simeng.tick_simulation(st, step)
        compute_risk(st)
        elapsed += step


class _SpyLock:
    """Drop-in `with` lock that signals when a second thread must wait."""

    def __init__(self):
        self._lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            self.waiting.set()
            self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


def _install_spy(monkeypatch) -> _SpyLock:
    spy = _SpyLock()
    monkeypatch.setattr(rs_mod, "_SIM_LOCK", spy, raising=False)
    return spy


def _race_two(method: str, path1: str, path2: str, body: dict | None,
              spy: _SpyLock, entered: threading.Event, gate: threading.Event,
              payload: dict | None = None):
    """Run two identical-route requests; request 2 must block on the spy lock.

    Returns (status_codes, engine_entries_during_gate).
    """
    codes: dict[str, int] = {}
    entries: list[str] = []

    orig = payload["engine_fn"] if payload else None
    if orig is not None:
        def slow(*a, **k):
            entries.append(threading.current_thread().name)
            entered.set()
            assert gate.wait(10), "race gate never released"
            return orig(*a, **k)
        monkey = payload["monkeypatch"]
        monkey.setattr(payload["engine_module"], payload["engine_attr"], slow)

    def worker(tag: str, path: str):
        c = TestClient(app)
        r = c.request(method, path, json=body, headers=_hdr())
        codes[tag] = r.status_code

    t1 = threading.Thread(target=worker, args=("t1", path1))
    t1.start()
    assert entered.wait(5), "first request never reached the engine"
    t2 = threading.Thread(target=worker, args=("t2", path2))
    t2.start()
    arrived = spy.waiting.wait(3.0)   # fix present: t2 blocks on the lock
    entries_snapshot = len(entries)   # must still be 1 (t2 not in engine)
    gate.set()
    t1.join(10)
    t2.join(10)
    assert not t1.is_alive() and not t2.is_alive(), "worker threads hung"
    return codes, arrived, entries_snapshot


# --------------------------------------------------------------- create race

def test_concurrent_creates_exactly_one_201(monkeypatch):
    full_reset(get_state())
    spy = _install_spy(monkeypatch)
    entered, gate = threading.Event(), threading.Event()

    codes, arrived, entries = _race_two(
        "POST", "/api/simulations", "/api/simulations",
        {"scenario": "fire", "target_id": "eng", "params": {"intensity": 4}},
        spy, entered, gate,
        payload={"engine_fn": simeng.create_simulation,
                 "engine_module": simeng, "engine_attr": "create_simulation",
                 "monkeypatch": monkeypatch})

    assert arrived, "second create must serialize on the simulations lock"
    assert entries == 1, "engine create must not be entered by two threads"
    assert sorted(codes.values()) == [201, 409], codes
    st = get_state()
    assert st.active_sim is not None and st.active_sim.scenario == "fire"
    # exactly one Simulation row was written for this burst
    from app.core.database import SessionLocal
    from app.models.entities import Simulation
    with SessionLocal() as db:
        rows = [r for r in db.query(Simulation).filter(
            Simulation.target_id == "eng", Simulation.scenario == "fire").all()
            if (r.params or {}).get("intensity") == 4]
    assert len(rows) == 1, f"expected a single created sim row, got {len(rows)}"
    full_reset(get_state())


def test_create_over_completed_still_allowed_under_concurrency(monkeypatch):
    st = get_state()
    full_reset(st)
    r = client.post("/api/simulations",
                    json={"scenario": "fire", "target_id": "eng",
                          "params": {"intensity": 3}}, headers=_hdr())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/simulations/{sid}/start", headers=_hdr()).status_code == 200
    assert client.post(f"/api/simulations/{sid}/recover", headers=_hdr()).status_code == 200
    for _ in range(80):
        if st.active_sim is None or st.active_sim.status == "COMPLETED":
            break
        _tick(10, step=5)
    assert st.active_sim.status == "COMPLETED"

    spy = _install_spy(monkeypatch)
    barrier = threading.Barrier(6)
    codes: list[int] = []

    def worker():
        c = TestClient(app)
        barrier.wait()
        resp = c.post("/api/simulations",
                      json={"scenario": "power", "target_id": "clinic"}, headers=_hdr())
        codes.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for _ in range(6):
            pool.submit(worker)
    assert sorted(codes) == [201, 409, 409, 409, 409, 409], codes
    assert get_state().active_sim.scenario == "power"
    full_reset(st)


# ----------------------------------------------------- lifecycle transitions

def test_concurrent_pause_serialized_single_transition(monkeypatch):
    st = get_state()
    full_reset(st)
    r = client.post("/api/simulations",
                    json={"scenario": "fire", "target_id": "eng",
                          "params": {"intensity": 3}}, headers=_hdr())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/simulations/{sid}/start", headers=_hdr()).status_code == 200

    spy = _install_spy(monkeypatch)
    entered, gate = threading.Event(), threading.Event()
    codes, arrived, entries = _race_two(
        "POST", f"/api/simulations/{sid}/pause", f"/api/simulations/{sid}/pause",
        None, spy, entered, gate,
        payload={"engine_fn": simeng.pause_simulation,
                 "engine_module": simeng, "engine_attr": "pause_simulation",
                 "monkeypatch": monkeypatch})

    assert arrived, "second pause must serialize on the simulations lock"
    assert entries == 1, "engine pause must not be entered by two threads"
    assert sorted(codes.values()) == [200, 400], codes
    assert st.active_sim.status == "PAUSED"
    paused_events = [e for e in st.active_sim.events if e["kind"] == "paused"]
    assert len(paused_events) == 1, "exactly one paused event for one transition"
    full_reset(st)


def test_concurrent_pause_resume_burst_consistent():
    st = get_state()
    full_reset(st)
    r = client.post("/api/simulations",
                    json={"scenario": "fire", "target_id": "eng",
                          "params": {"intensity": 3}}, headers=_hdr())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"/api/simulations/{sid}/start", headers=_hdr()).status_code == 200
    baseline = {e["kind"] for e in st.active_sim.events}

    n = 12
    barrier = threading.Barrier(n)
    codes: list[int] = []

    def worker(i: int):
        c = TestClient(app)
        action = "pause" if i % 2 == 0 else "resume"
        barrier.wait()
        resp = c.post(f"/api/simulations/{sid}/{action}", headers=_hdr())
        codes.append((action, resp.status_code))

    with ThreadPoolExecutor(max_workers=n) as pool:
        for i in range(n):
            pool.submit(worker, i)

    assert all(code in (200, 400) for _, code in codes), codes
    pauses = sum(1 for a, c_ in codes if a == "pause" and c_ == 200)
    resumes = sum(1 for a, c_ in codes if a == "resume" and c_ == 200)
    # a valid single-owner transition sequence can never skip or double-toggle
    assert 0 <= pauses - resumes <= 1, (pauses, resumes)
    sim = st.active_sim
    assert sim is not None
    new_kinds = [e["kind"] for e in sim.events if e["kind"] not in baseline]
    assert new_kinds.count("paused") == pauses
    assert new_kinds.count("resumed") == resumes
    expected = "PAUSED" if pauses > resumes else "RUNNING"
    assert sim.status == expected, (sim.status, pauses, resumes)
    full_reset(st)


# ------------------------------------------------------------------- reads

def test_concurrent_reads_stay_consistent():
    st = get_state()
    full_reset(st)
    paths = ["/api/campus", "/api/risk", "/api/simulations",
             "/api/analytics/overview?range=24H", "/api/buildings"]
    barrier = threading.Barrier(10)
    results: dict[str, dict] = {}

    def worker(i: int):
        c = TestClient(app)
        path = paths[i % len(paths)]
        barrier.wait()
        resp = c.get(path, headers=_hdr())
        results[f"{i}:{path}"] = {"code": resp.status_code, "body": resp.json()}

    with ThreadPoolExecutor(max_workers=10) as pool:
        for i in range(10):
            pool.submit(worker, i)

    for key, res in results.items():
        assert res["code"] == 200, (key, res["code"])
    campus = results["0:/api/campus"]["body"]
    assert campus["summary"]["buildings"] == 6
    risk = results["1:/api/risk"]["body"]
    assert 0 <= risk["campus"]["score"] <= 100
    sims = results["2:/api/simulations"]["body"]
    assert "active" in sims and "history" in sims
    ov = results["3:/api/analytics/overview?range=24H"]["body"]
    assert ov["window"]["preset"] == "24H"
    assert len(results["4:/api/buildings"]["body"]) == 6
