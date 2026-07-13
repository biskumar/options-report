import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("broadcaster")


class Broadcaster:
    """Fan-out hub: one message in, pushed to every connected browser tab
    over its own WebSocket. No inbound routing needed for v1 (all writes
    happen over REST); this is push-only."""

    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def register(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)

    def unregister(self, ws: WebSocket):
        self._clients.discard(ws)

    async def publish(self, msg_type: str, payload: dict):
        data = json.dumps({"type": msg_type, "data": payload}, default=str)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister(ws)


broadcaster = Broadcaster()
