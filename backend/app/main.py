import asyncio
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_ai,
    routes_analytics,
    routes_audit,
    routes_auth,
    routes_campus,
    routes_evacuation,
    routes_history,
    routes_realtime,
    routes_settings,
    routes_simulations,
    routes_system,
    routes_users,
)
from app.core.config import settings, validate_security_config
from app.services import ai_service, route_service
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.runtime import runtime
from app.services.seed import init_db, load_sensor_history, seed_data
from app.services.state import get_state
from app.services.simulation_engine import create_simulation, start_simulation
from app.websocket.manager import CHANNELS, manager

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("twinsphere")

# Refuse to boot on unsafe production configuration (Phase 10 §13) —
# development keeps the default secret with a warning.
validate_security_config()

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initialising database…")
    init_db()
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        seed_data(db)
    state = get_state()
    log.info("Warming digital twin state…")
    ai_service.warm_series(state)
    load_sensor_history(state)
    ai_service.refresh_anomalies(state)
    ai_service.refresh_predictions(state)
    compute_routes(state)
    compute_risk(state)
    route_service.ensure_initial(state)
    state.analyst = await ai_service.run_analyst(state)
    await runtime.start()
    log.info("TwinSphere AI backend ready (clock %s:00)", int(state.clock_hour))
    yield
    await runtime.stop()


app = FastAPI(
    title="TwinSphere AI",
    description="AI-Powered Smart Campus Digital Twin & Simulation Platform",
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS (Phase 10 §12): explicit origins only — a wildcard with credentials is
# rejected by validate_security_config(); an empty list simply emits no
# CORS headers (same-origin deployments, e.g. nginx, are unaffected).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=bool(settings.CORS_ORIGINS),
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Phase 10 §12 — request ids, body-size limit, security headers."""
    incoming = request.headers.get("x-request-id", "")
    request.state.request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
    # Reject oversized payloads before any route/parser sees them (§14).
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > settings.MAX_REQUEST_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    response = await call_next(request)
    # Phase 11 observability — bounded counters keyed by route *template*
    # (falls back to a coarse "unmatched" bucket) so path params cannot
    # explode cardinality.
    from app.core import metrics

    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or "unmatched"
    metrics.inc(f"http.{request.method}.{route_path}.{response.status_code}")
    response.headers["X-Request-ID"] = request.state.request_id
    if settings.SECURITY_HEADERS_ENABLED:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy",
                                    "camera=(), microphone=(), geolocation=(), payment=()")
        if settings.HSTS_ENABLED and request.headers.get("x-forwarded-proto", "") == "https":
            response.headers.setdefault("Strict-Transport-Security",
                                        "max-age=31536000; includeSubDomains")
        ctype = response.headers.get("content-type", "")
        if ctype.startswith("text/html"):
            # Vite/nginx-served SPA: no inline scripts required by the build.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; font-src 'self' data:; "
                "connect-src 'self' ws://localhost:* wss://localhost:*; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
            )
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Log full detail server-side; never disclose exception classes to clients.
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


for router in (
    routes_system.router, routes_auth.router, routes_users.router,
    routes_audit.router, routes_campus.router,
    routes_ai.router, routes_simulations.router, routes_analytics.router,
    routes_settings.router, routes_realtime.router,
    # Phase 7: registered after routes_campus so legacy /api/routes* stay intact
    routes_evacuation.router,
    # Phase 9: history + replay (separate prefix /api/history)
    routes_history.router,
):
    app.include_router(router)


@app.get("/")
def root():
    return {"service": "TwinSphere AI", "version": settings.VERSION, "docs": "/docs"}


WS_MAX_MESSAGE_BYTES = 16 * 1024


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Authenticated WebSocket (Phase 10 §10).

    Handshake: after ``accept`` the client must send
    ``{"type":"auth","token":"<jwt>"}`` within WS_AUTH_TIMEOUT_S — tokens are
    never accepted from the query string.  Only then is the socket registered
    and the initial state frame delivered.  Inbound messages are validated
    (size + schema) and ``subscribe`` is checked against CHANNELS permissions.
    """
    if not settings.WEBSOCKET_ENABLED:
        await ws.close(code=1013, reason="WebSocket streaming disabled")
        return
    # Never accept long-lived credentials in URLs (Phase 10 §10).
    if "token" in (ws.query_params or {}):
        await ws.close(code=4401, reason="Send credentials via auth message, not URL")
        return
    client = ws.client.host if ws.client else "anon"
    from app.core.ratelimit import check as rate_check

    try:
        rate_check("ws", client)
    except Exception:
        await ws.close(code=4429, reason="Too many connection attempts")
        return

    await ws.accept()
    principal = None
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=settings.WS_AUTH_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        try:
            await ws.close(code=4401, reason="Authentication required")
        except Exception:
            pass
        return
    except Exception:
        try:
            await ws.close(code=1011, reason="Handshake error")
        except Exception:
            pass
        return

    try:
        from app.core.database import SessionLocal
        from app.core.security import authenticate_token

        msg = json.loads(raw)
        if not isinstance(msg, dict) or msg.get("type") != "auth" or not isinstance(msg.get("token"), str):
            raise ValueError("auth message required")
        with SessionLocal() as db:
            principal = authenticate_token(msg["token"], db)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close(code=4401, reason="Invalid token")
        except Exception:
            pass
        return

    await manager.connect(ws, principal)
    state = get_state()
    try:
        await ws.send_text(json.dumps(
            {"type": "state", "payload": {**state.snapshot(), "connected_clients": manager.connected}},
            default=str))
        while True:
            data = await ws.receive_text()
            if len(data.encode()) > WS_MAX_MESSAGE_BYTES:
                await ws.close(code=1009, reason="Message too large")
                break
            if data == "ping":
                await ws.send_text('{"type":"pong"}')
                continue
            try:
                msg = json.loads(data)
            except Exception:
                await ws.send_text('{"type":"error","error":"invalid_json"}')
                continue
            if not isinstance(msg, dict):
                await ws.send_text('{"type":"error","error":"invalid_message"}')
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                await ws.send_text('{"type":"pong"}')
            elif mtype in ("subscribe", "unsubscribe"):
                channel = msg.get("channel")
                if not isinstance(channel, str) or channel not in CHANNELS:
                    await ws.send_text('{"type":"error","error":"unknown_channel"}')
                    continue
                if mtype == "subscribe":
                    ok = await manager.subscribe(ws, channel)
                else:
                    ok = await manager.unsubscribe(ws, channel)
                await ws.send_text(json.dumps(
                    {"type": "subscription", "channel": channel, "ok": ok}))
            else:
                await ws.send_text('{"type":"error","error":"unknown_type"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("websocket terminated", exc_info=True)
    finally:
        await manager.disconnect(ws)
