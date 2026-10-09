import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_ai,
    routes_analytics,
    routes_auth,
    routes_campus,
    routes_evacuation,
    routes_history,
    routes_realtime,
    routes_settings,
    routes_simulations,
    routes_system,
)
from app.core.config import settings
from app.services import ai_service, route_service
from app.services.optimization_service import compute_routes
from app.services.risk_engine import compute_risk
from app.services.runtime import runtime
from app.services.seed import init_db, load_sensor_history, seed_data
from app.services.state import get_state
from app.services.simulation_engine import create_simulation, start_simulation
from app.websocket.manager import manager

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("twinsphere")


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": type(exc).__name__})


for router in (
    routes_system.router, routes_auth.router, routes_campus.router,
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


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str | None = None):
    if not settings.WEBSOCKET_ENABLED:
        await ws.close(code=1013, reason="WebSocket streaming disabled")
        return
    if token:
        try:
            from app.core.security import decode_token
            decode_token(token)
        except Exception:
            await ws.close(code=4401, reason="Invalid token")
            return
    await manager.connect(ws)
    state = get_state()
    try:
        await ws.send_text(__import__("json").dumps(
            {"type": "state", "payload": {**state.snapshot(), "connected_clients": manager.connected}},
            default=str))
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(ws)
