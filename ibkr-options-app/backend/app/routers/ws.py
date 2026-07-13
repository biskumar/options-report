from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..broadcaster import broadcaster
from ..killswitch import kill_switch

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await broadcaster.register(websocket)

    # The heartbeat/event handlers only broadcast on a *change* in status,
    # so a client connecting after the status has already settled (e.g. a
    # fresh page load well after TWS connected) would otherwise never learn
    # the current state and would sit on the default "disconnected" banner
    # indefinitely. Send this one client an immediate snapshot on connect.
    ib_service = websocket.app.state.ib_service
    await websocket.send_json({"type": "connection", "data": ib_service.status_dict()})
    await websocket.send_json({"type": "killswitch", "data": kill_switch.as_dict()})

    try:
        while True:
            # Frontend never needs to send anything in v1 (all writes are
            # REST); this just keeps the connection alive so disconnects
            # are detected promptly.
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.unregister(websocket)
