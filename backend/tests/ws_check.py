"""WebSocket verification (Phases 4, 5, 6, 7, 8 & 11): state push, ping/pong,
typed live events, event envelopes, auth handling, AI cycle events
(ai.anomaly, ai.prediction, risk.update), simulation/route/evacuation
lifecycle events, analyst.* decision-support events, and Phase 11
resilience (rapid connect/disconnect, reconnect, multi-client fan-out,
idempotent subscribe)."""
from __future__ import annotations

import json as _json
import sys
import time as _time

from fastapi.testclient import TestClient

from app.main import app

PASSED = 0
FAILED = 0

TYPED_EVENTS = (
    "sensor.batch_update", "occupancy.update", "building.update",
    "simulation.status", "system.status",
)


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"PASS {name}")
    else:
        FAILED += 1
        print(f"FAIL {name} {detail}")


def _recv(ws, timeout: float) -> dict | None:
    """Receive one frame with a timeout.

    Starlette >=0.37 buffers frames on an anyio memory stream; drain it from
    the session portal with `move_on_after` so a missing event fails the check
    instead of hanging the script. Falls back to the legacy queue/receive paths.
    """
    send_rx = getattr(ws, "_send_rx", None)
    portal = getattr(ws, "portal", None)
    if send_rx is not None and portal is not None:
        import anyio

        async def _inner():
            with anyio.move_on_after(timeout):
                return await send_rx.receive()
            return None

        try:
            msg = portal.call(_inner)
        except Exception:  # noqa: BLE001
            return None
    else:
        # legacy starlette: frames land on ws._send_queue
        q = getattr(ws, "_send_queue", None)
        if q is not None:
            try:
                msg = q.get(timeout=max(0.05, timeout))
            except Exception:  # noqa: BLE001
                return None
        else:  # last resort: blocking receive (no timeout)
            try:
                msg = ws.receive()
            except Exception:  # noqa: BLE001
                return None
    if not isinstance(msg, dict) or msg.get("type") != "websocket.send":
        return None
    text = msg.get("text")
    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _collect(ws, want: set[str], timeout: float, sink: list[dict]) -> None:
    """Read frames until every type in `want` has been seen or timeout."""
    seen = {f.get("type") for f in sink}
    deadline = _time.monotonic() + timeout
    while not want <= seen:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            return
        msg = _recv(ws, min(1.0, remaining))
        if msg is None:
            continue
        sink.append(msg)
        seen.add(msg.get("type"))


def _drain(ws, seconds: float, sink: list[dict], until=None) -> None:
    """Read frames arriving within `seconds`, stopping early once `until(sink)`
    is satisfied (short per-read timeout so an empty stream never hangs)."""
    deadline = _time.monotonic() + seconds
    while _time.monotonic() < deadline:
        if until is not None and until(sink):
            return
        msg = _recv(ws, min(0.4, deadline - _time.monotonic()))
        if msg is not None:
            sink.append(msg)


def main() -> int:
    global PASSED, FAILED
    with TestClient(app) as client:
        login = client.post("/api/auth/login",
                            json={"username": "operator", "password": "operator123"})
        ohdr = {"Authorization": f"Bearer {login.json().get('access_token')}"}
        otok = login.json().get("access_token")
        try:
            with client.websocket_connect("/ws") as ws:
                # Phase 10 §10 — first frame must be the auth message
                ws.send_text(_json.dumps({"type": "auth", "token": otok}))
                frames: list[dict] = []

                _collect(ws, {"state"}, 5.0, frames)
                first = frames[0] if frames else {}
                check("ws initial state", first.get("type") == "state",
                      f"got {first.get('type')}")
                payload = first.get("payload", {})
                check("ws state has buildings", len(payload.get("buildings", [])) > 0)
                check("ws state has metrics", "metrics" in payload)
                check("ws state has sim status", payload.get("sim_status") in
                      ("RUNNING", "PAUSED", "STOPPED"), payload.get("sim_status"))

                ws.send_text("ping")
                _collect(ws, {"pong"}, 6.0, frames)
                check("ws ping/pong", any(f.get("type") == "pong" for f in frames))

                # one runtime sensor tick emits all typed Phase 4 events (2s default)
                _collect(ws, set(TYPED_EVENTS), 12.0, frames)
                types = {f.get("type") for f in frames}
                for evt in TYPED_EVENTS:
                    check(f"ws event {evt}", evt in types, f"missing; seen {sorted(types)}")

                envelope = next((f for f in frames if f.get("type") == "sensor.batch_update"), None)
                ok_env = bool(envelope) and envelope.get("event_version") == 1 \
                    and envelope.get("source") == "SIMULATED" \
                    and bool(envelope.get("timestamp")) \
                    and isinstance(envelope.get("data"), dict) \
                    and isinstance(envelope.get("data", {}).get("sensors"), list) \
                    and envelope.get("data", {}).get("count", 0) >= 1
                check("sensor.batch_update envelope + payload", ok_env, str(envelope)[:160])

                occ = next((f for f in frames if f.get("type") == "occupancy.update"), None)
                occ_data = (occ or {}).get("data", {})
                check("occupancy.update payload",
                      "occupancy" in occ_data and "occupancy_pct" in occ_data
                      and isinstance(occ_data.get("buildings"), list)
                      and len(occ_data.get("buildings", [])) == 6, str(occ_data)[:160])

                bld = next((f for f in frames if f.get("type") == "building.update"), None)
                bld_data = (bld or {}).get("data", {})
                check("building.update payload",
                      isinstance(bld_data.get("buildings"), list)
                      and len(bld_data.get("buildings", [])) == 6
                      and "temperature" in (bld_data.get("buildings") or [{}])[0],
                      str(bld_data)[:160])

                sim = next((f for f in frames if f.get("type") == "simulation.status"), None)
                sim_data = (sim or {}).get("data", {})
                check("simulation.status payload",
                      sim_data.get("status") in ("RUNNING", "PAUSED", "STOPPED")
                      and "speed" in sim_data and "simulation_time" in sim_data
                      and "last_tick" in sim_data, str(sim_data)[:160])

                sysf = next((f for f in frames if f.get("type") == "system.status"), None)
                sys_data = (sysf or {}).get("data", {})
                check("system.status payload",
                      all(k in sys_data for k in ("backend", "database", "websocket",
                                                  "simulator", "connected_clients")),
                      str(sys_data)[:160])

                # Phase 5 — AI cycle events arrive after AI_ANALYSIS_INTERVAL_SECONDS
                _collect(ws, {"ai.anomaly", "ai.prediction", "risk.update"}, 25.0, frames)
                ai_types = {f.get("type") for f in frames}
                for evt in ("ai.anomaly", "ai.prediction", "risk.update"):
                    check(f"ws event {evt}", evt in ai_types,
                          f"missing; seen {sorted(ai_types)}")

                aia = next((f for f in frames if f.get("type") == "ai.anomaly"), None)
                check("ai.anomaly envelope",
                      bool(aia) and aia.get("event_version") == 1
                      and bool(aia.get("timestamp"))
                      and isinstance(aia.get("data"), dict), str(aia)[:160])
                ad = (aia or {}).get("data", {})
                check("ai.anomaly payload",
                      isinstance(ad.get("anomalies"), list)
                      and isinstance(ad.get("sensor_status"), dict)
                      and ad.get("data_quality") in ("OK", "LIMITED", "INSUFFICIENT")
                      and isinstance(ad.get("count"), int), str(ad)[:160])

                aip = next((f for f in frames if f.get("type") == "ai.prediction"), None)
                pd = (aip or {}).get("data", {})
                check("ai.prediction payload",
                      isinstance(pd.get("predictions"), list)
                      and isinstance(pd.get("horizons"), list)
                      and len(pd.get("horizons", [])) >= 1
                      and isinstance(pd.get("count"), int), str(pd)[:160])

                rup = next((f for f in frames if f.get("type") == "risk.update"), None)
                rd = (rup or {}).get("data", {})
                check("risk.update payload",
                      isinstance(rd.get("campus"), dict)
                      and isinstance(rd.get("buildings"), dict)
                      and bool(rd.get("raw_level")), str(rd)[:160])

                # Phase 6 — simulation.* lifecycle + telemetry events (§27/§28)
                p6 = client.post("/api/simulations", headers=ohdr, json={
                    "scenario": "fire", "target_id": "eng",
                    "params": {"intensity": 4, "wind": "E",
                               "ignition_zone": "eng_faculty"}})
                check("phase6 ws create", p6.status_code == 201,
                      (p6.status_code, p6.text[:200]))
                p6id = p6.json().get("id", "")
                p6s = client.post(f"/api/simulations/{p6id}/start", headers=ohdr)
                check("phase6 ws start", p6s.status_code == 200, p6s.text[:200])

                _collect(ws, {"simulation.created", "simulation.started",
                              "simulation.tick", "simulation.risk_update",
                              "simulation.zone_update"}, 16.0, frames)
                p6_types = {f.get("type") for f in frames}
                for evt in ("simulation.created", "simulation.started", "simulation.tick",
                            "simulation.risk_update", "simulation.zone_update"):
                    check(f"ws event {evt}", evt in p6_types,
                          f"missing; seen {sorted(p6_types)}")

                stick = next((f for f in frames
                              if f.get("type") == "simulation.tick"
                              and (f.get("data") or {}).get("id") == p6id), None)
                sd = (stick or {}).get("data", {})
                check("simulation.tick payload",
                      sd.get("status") in ("RUNNING", "AWAITING_RECOVERY", "RECOVERING")
                      and isinstance(sd.get("people_at_risk"), int)
                      and isinstance(sd.get("affected_zones"), int)
                      and "risk" in sd and "speed" in sd
                      and sd.get("id") == p6id, str(sd)[:200])
                check("simulation.tick envelope",
                      bool(stick) and stick.get("event_version") == 1
                      and bool(stick.get("timestamp"))
                      and stick.get("source"), str(stick)[:160])

                zupd = next((f for f in frames if f.get("type") == "simulation.zone_update"), None)
                zd = (zupd or {}).get("data", {})
                check("simulation.zone_update payload",
                      zd.get("simulation_id") == p6id
                      and isinstance(zd.get("changed"), list)
                      and len(zd.get("changed", [])) >= 1
                      and "status" in zd["changed"][0], str(zd)[:200])

                # Phase 7 — route.* + evacuation.* typed events while the
                # incident is live (runtime revalidate every sensor tick)
                _collect(ws, {"evacuation.started", "evacuation.updated",
                              "route.calculated", "route.updated",
                              "route.invalidated", "route.recalculated",
                              "bottleneck.detected"}, 16.0, frames)
                p7_types = {f.get("type") for f in frames}
                p7_seen = sorted(t for t in p7_types
                                 if t.split(".")[0] in
                                 ("route", "evacuation", "bottleneck"))
                check("ws route/evacuation events", len(p7_seen) >= 2,
                      f"seen {p7_seen}")
                check("ws auto evacuation plan event",
                      "route.calculated" in p7_types
                      or "evacuation.started" in p7_types,
                      f"seen {p7_seen}")
                r7 = next((f for f in frames
                           if f.get("type", "").split(".")[0]
                           in ("route", "evacuation")), None)
                check("route event envelope",
                      bool(r7) and r7.get("event_version") == 1
                      and bool(r7.get("timestamp"))
                      and isinstance(r7.get("data"), dict), str(r7)[:160])
                r7d = (r7 or {}).get("data", {})
                check("route event payload",
                      "route_id" in r7d or "status" in r7d
                      or "bottleneck" in r7d or "location_id" in r7d,
                      str(r7d)[:160])

                # Phase 8 — analyst.* events while the incident is live: a
                # REST-triggered run queues typed events for the next flush.
                adm = client.post("/api/auth/login",
                                  json={"username": "admin", "password": "admin123"})
                ahdr8 = {"Authorization": f"Bearer {adm.json().get('access_token')}"}
                a8 = client.post("/api/ai/analyze",
                                 json={"question": "what is happening?"},
                                 headers=ahdr8)
                check("phase8 ws analyze", a8.status_code == 200,
                      (a8.status_code, a8.text[:200]))
                _collect(ws, {"analyst.analysis_started",
                              "analyst.analysis_completed",
                              "analyst.recommendation_created"}, 12.0, frames)
                a8_types = {f.get("type") for f in frames}
                for evt in ("analyst.analysis_started", "analyst.analysis_completed",
                            "analyst.recommendation_created"):
                    check(f"ws event {evt}", evt in a8_types,
                          f"missing; seen {sorted(a8_types)}")
                a8c = next((f for f in frames
                            if f.get("type") == "analyst.analysis_completed"), None)
                a8cd = (a8c or {}).get("data", {})
                check("analyst.analysis_completed payload",
                      bool(a8c) and a8c.get("event_version") == 1
                      and bool(a8c.get("timestamp"))
                      and isinstance(a8cd.get("analysis_id"), str)
                      and "context_summary" not in a8cd,
                      str(a8c)[:200])

                p6p = client.post(f"/api/simulations/{p6id}/pause", headers=ohdr)
                check("phase6 ws pause", p6p.status_code == 200, p6p.text[:200])
                _collect(ws, {"simulation.paused"}, 5.0, frames)
                check("ws event simulation.paused",
                      any(f.get("type") == "simulation.paused" for f in frames))
                p6r = client.post(f"/api/simulations/{p6id}/reset", headers=ohdr)
                check("phase6 ws reset", p6r.status_code == 200, p6r.text[:200])
                _collect(ws, {"simulation.reset"}, 5.0, frames)
                check("ws event simulation.reset",
                      any(f.get("type") == "simulation.reset" for f in frames))

                # legacy frames still flow alongside typed events: the tick's
                # `state` frame follows its telemetry events — drain briefly.
                _drain(ws, 5.0, frames,
                       until=lambda fs: sum(1 for f in fs if f.get("type") == "state") >= 2)
                check("legacy state frames still broadcast",
                      sum(1 for f in frames if f.get("type") == "state") >= 2)
        except Exception as exc:  # noqa: BLE001
            check("ws connection", False, repr(exc))

        # ------------ Phase 10 §10: authentication & authorization checks ---
        rejected = False
        try:
            with client.websocket_connect("/ws?token=not-a-real-token") as ws:
                try:
                    msg = ws.receive()
                    rejected = isinstance(msg, dict) and msg.get("type") == "websocket.close"
                except Exception:  # noqa: BLE001
                    rejected = True
        except Exception:  # noqa: BLE001
            rejected = True
        check("ws refuses tokens in query string", rejected)

        try:
            with client.websocket_connect("/ws") as ws:
                # no auth message: server waits, then closes with 4401
                msg = ws.receive()
                closed = isinstance(msg, dict) and msg.get("type") == "websocket.close"
                check("ws rejects unauthenticated connection", closed, str(msg)[:120])
        except Exception:  # noqa: BLE001
            check("ws rejects unauthenticated connection", True)

        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_text(_json.dumps({"type": "auth", "token": "garbage"}))
                msg = ws.receive()
                closed = isinstance(msg, dict) and msg.get("type") == "websocket.close"
                check("ws rejects invalid auth token", closed, str(msg)[:120])
        except Exception:  # noqa: BLE001
            check("ws rejects invalid auth token", True)

        def _recv_until(ws, pred, limit: int = 8):
            for _ in range(limit):
                frame = ws.receive_json()
                if pred(frame):
                    return frame
            return None

        try:
            r = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer123"})
            vtok = r.json().get("access_token")
            with client.websocket_connect("/ws") as ws:
                ws.send_text(_json.dumps({"type": "auth", "token": vtok}))
                first = ws.receive_json()
                check("ws accepts valid auth message", first.get("type") == "state",
                      str(first)[:120])
                ws.send_text(_json.dumps({"type": "subscribe", "channel": "state"}))
                sub = _recv_until(ws, lambda f: f.get("type") == "subscription")
                check("ws viewer subscribes read channel", bool(sub and sub.get("ok")), str(sub))
                ws.send_text(_json.dumps({"type": "subscribe", "channel": "admin"}))
                sub2 = _recv_until(ws, lambda f: f.get("type") == "subscription")
                check("ws viewer denied admin channel", bool(sub2) and sub2.get("ok") is False,
                      str(sub2))
                ws.send_text(_json.dumps({"type": "subscribe", "channel": "nope"}))
                bad = _recv_until(ws, lambda f: f.get("type") in ("error", "subscription"))
                check("ws unknown channel rejected",
                      bool(bad) and bad.get("type") == "error", str(bad))
                ws.send_text(_json.dumps({"type": "not_a_real_type"}))
                err = _recv_until(ws, lambda f: f.get("type") == "error")
                check("ws unknown message type rejected",
                      bool(err) and err.get("error") == "unknown_type", str(err))
                ws.send_text("this is not json")
                err2 = _recv_until(ws, lambda f: f.get("type") == "error")
                check("ws malformed json rejected",
                      bool(err2) and err2.get("error") == "invalid_json", str(err2))
        except Exception as exc:  # noqa: BLE001
            check("ws viewer auth/subscribe flow", False, repr(exc))

        try:
            r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
            atok = r.json().get("access_token")
            with client.websocket_connect("/ws") as ws:
                ws.send_text(_json.dumps({"type": "auth", "token": atok}))
                ws.receive_json()
                ws.send_text(_json.dumps({"type": "subscribe", "channel": "admin"}))
                sub = _recv_until(ws, lambda f: f.get("type") == "subscription")
                check("ws admin subscribes admin channel", bool(sub and sub.get("ok")), str(sub))
        except Exception as exc:  # noqa: BLE001
            check("ws admin auth/subscribe flow", False, repr(exc))

        # ---------------- Phase 11 §7: resilience & fan-out -------------------
        r = client.post("/api/auth/login", json={"username": "operator",
                                                 "password": "operator123"})
        otok2 = r.json().get("access_token")

        try:
            for _ in range(8):  # rapid connect → auth → close cycles
                with client.websocket_connect("/ws") as ws:
                    ws.send_text(_json.dumps({"type": "auth", "token": otok2}))
                    frame = ws.receive_json()
                    assert frame.get("type") == "state", str(frame)[:120]
            check("ws rapid connect/disconnect cycles", True)
        except Exception as exc:  # noqa: BLE001
            check("ws rapid connect/disconnect cycles", False, repr(exc))

        try:
            # abrupt close (context exit without goodbye), then reconnect
            with client.websocket_connect("/ws") as ws:
                ws.send_text(_json.dumps({"type": "auth", "token": otok2}))
                ws.receive_json()
            with client.websocket_connect("/ws") as ws:
                ws.send_text(_json.dumps({"type": "auth", "token": otok2}))
                frame = ws.receive_json()
                check("ws reconnect after abrupt close", frame.get("type") == "state",
                      str(frame)[:120])
        except Exception as exc:  # noqa: BLE001
            check("ws reconnect after abrupt close", False, repr(exc))

        try:
            with client.websocket_connect("/ws") as ws1:
                with client.websocket_connect("/ws") as ws2:
                    ws1.send_text(_json.dumps({"type": "auth", "token": otok2}))
                    ws2.send_text(_json.dumps({"type": "auth", "token": otok2}))
                    ws1.receive_json()
                    ws2.receive_json()
                    f1: list[dict] = []
                    f2: list[dict] = []
                    _drain(ws1, 8.0, f1,
                           until=lambda fs: any(x.get("type") == "state" for x in fs))
                    _drain(ws2, 8.0, f2,
                           until=lambda fs: any(x.get("type") == "state" for x in fs))
                    check("ws both clients receive broadcast",
                          any(x.get("type") == "state" for x in f1)
                          and any(x.get("type") == "state" for x in f2),
                          f"frames={len(f1)}/{len(f2)}")
        except Exception as exc:  # noqa: BLE001
            check("ws both clients receive broadcast", False, repr(exc))

        try:
            with client.websocket_connect("/ws") as ws:
                ws.send_text(_json.dumps({"type": "auth", "token": otok2}))
                ws.receive_json()
                ws.send_text(_json.dumps({"type": "subscribe", "channel": "state"}))
                s1 = _recv_until(ws, lambda f: f.get("type") == "subscription")
                ws.send_text(_json.dumps({"type": "subscribe", "channel": "state"}))
                s2 = _recv_until(ws, lambda f: f.get("type") == "subscription")
                check("ws double subscribe idempotent",
                      bool(s1 and s1.get("ok")) and bool(s2 and s2.get("ok")),
                      str((s1, s2)))
        except Exception as exc:  # noqa: BLE001
            check("ws double subscribe idempotent", False, repr(exc))

    print(f"\n{PASSED}/{PASSED + FAILED} websocket checks passed")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
