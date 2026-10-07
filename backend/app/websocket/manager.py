import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from app.core.config import settings

log = logging.getLogger("twinsphere.ws")


class WSManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.last_broadcast: float = 0.0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.connections.discard(ws)

    async def _fanout(self, message: str) -> None:
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self.connections)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self.connections.discard(ws)

    async def broadcast(self, type_: str, payload: Any) -> None:
        """Legacy frame shape kept for Phase 1-3 consumers: {type, payload}."""
        if not settings.WEBSOCKET_ENABLED or not self.connections:
            return
        await self._fanout(json.dumps({"type": type_, "payload": payload}, default=str))

    async def emit(self, event: str, data: Any) -> None:
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
        await self._fanout(message)

    @property
    def connected(self) -> int:
        return len(self.connections)


manager = WSManager()
