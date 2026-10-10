import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from app.core.config import settings

log = logging.getLogger("twinsphere.ws")

# Channels a client may subscribe to -> required permission (Phase 10 §10).
CHANNELS: dict[str, str] = {
    "state": "read",     # sensors, occupancy, risk, incidents, simulations, routes, AI
    "admin": "manage",   # administrative/security streams
}
REVALIDATE_SECONDS = 60.0  # re-check user status from the DB for long-lived sockets


def _has_permission(role: str, permission: str) -> bool:
    from app.core.security import ROLE_PERMISSIONS

    return permission in ROLE_PERMISSIONS.get(role, set())


class WSManager:
    """Authenticated WebSocket registry.

    Connections are only registered through :meth:`connect` *after* the
    handshake authenticated a principal.  Each entry keeps the principal
    snapshot plus its channel subscriptions; broadcasts are filtered by the
    channel's required permission and user status is periodically re-validated
    against the database so disabled/deleted users are dropped.
    """

    def __init__(self) -> None:
        self.connections: dict[WebSocket, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.last_broadcast: float = 0.0
        self._last_revalidate: float = 0.0

    async def connect(self, ws: WebSocket, principal: dict, channels: set[str] | None = None) -> None:
        from app.core import metrics

        # NOTE: the endpoint performs `ws.accept()` as part of the Phase 10
        # auth handshake — accepting again here would be a protocol error.
        async with self._lock:
            self.connections[ws] = {
                "principal": dict(principal),
                "channels": set(channels or {"state"}),
            }
        metrics.inc("ws.connections.total")
        metrics.gauge("ws.connections.active", len(self.connections))

    async def disconnect(self, ws: WebSocket) -> None:
        from app.core import metrics

        async with self._lock:
            self.connections.pop(ws, None)
        metrics.inc("ws.disconnects.total")
        metrics.gauge("ws.connections.active", len(self.connections))

    async def subscribe(self, ws: WebSocket, channel: str) -> bool:
        entry = self.connections.get(ws)
        if entry is None or channel not in CHANNELS:
            return False
        if not _has_permission(entry["principal"].get("role", "VIEWER"), CHANNELS[channel]):
            return False
        entry["channels"].add(channel)
        return True

    async def unsubscribe(self, ws: WebSocket, channel: str) -> bool:
        entry = self.connections.get(ws)
        if entry is None or channel not in entry["channels"]:
            return False
        entry["channels"].discard(channel)
        return True

    async def _revalidate(self) -> None:
        """Drop sockets whose user was deleted or disabled (Phase 10 §10)."""
        now = time.monotonic()
        if now - self._last_revalidate < REVALIDATE_SECONDS:
            return
        self._last_revalidate = now
        try:
            from app.core.database import SessionLocal
            from app.models.entities import User

            with SessionLocal() as db:
                for ws in list(self.connections):
                    entry = self.connections.get(ws)
                    if entry is None:
                        continue
                    user = db.get(User, entry["principal"].get("sub", ""))
                    if user is None or not user.is_active:
                        async with self._lock:
                            self.connections.pop(ws, None)
                        try:
                            await ws.close(code=4401, reason="Session ended")
                        except Exception:
                            pass
        except Exception:  # pragma: no cover — never break broadcasts on revalidation
            log.exception("ws revalidation failed")

    def _recipients(self, channel: str) -> list[WebSocket]:
        need = CHANNELS.get(channel, "read")
        return [ws for ws, e in self.connections.items()
                if channel in e["channels"] and _has_permission(e["principal"].get("role", "VIEWER"), need)]

    async def _fanout(self, message: str, channel: str = "state") -> None:
        await self._revalidate()
        async with self._lock:
            targets = [ws for ws in self._recipients(channel)]
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self.connections.pop(ws, None)

    async def broadcast(self, type_: str, payload: Any, channel: str = "state") -> None:
        """Legacy frame shape kept for Phase 1-3 consumers: {type, payload}."""
        if not settings.WEBSOCKET_ENABLED or not self.connections:
            return
        await self._fanout(json.dumps({"type": type_, "payload": payload}, default=str), channel)

    async def emit(self, event: str, data: Any, channel: str = "state") -> None:
        """Phase 4 typed event envelope (spec §11): versioned, timestamped,
        source-labelled, with `data` (and `payload` alias for legacy dispatch)."""
        if not settings.WEBSOCKET_ENABLED or not self.connections:
            return
        message = json.dumps({
            "type": event,
            "event": event,
            "event_version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "SIMULATED",
            "data": data,
            "payload": data,
        }, default=str)
        await self._fanout(message, channel)

    @property
    def connected(self) -> int:
        return len(self.connections)


manager = WSManager()
