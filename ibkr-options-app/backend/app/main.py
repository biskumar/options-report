import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .broadcaster import broadcaster
from .config import settings
from .ib_service import IBConnectionService
from .routers import (
    account,
    alerts,
    chain,
    killswitch,
    maxpain,
    orders,
    positions,
    recommendations,
    technicals,
    unusual_whales,
    watchlist,
    ws,
)
from .services.alerts_service import AlertsService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

_last_broadcast_status: str | None = None


async def _heartbeat(ib_service: IBConnectionService):
    """Safety-net poll: ib_insync's connectedEvent/disconnectedEvent cover
    most transitions already, but this catches cases where TWS silently
    drops the socket without firing the event promptly."""
    global _last_broadcast_status
    while True:
        await asyncio.sleep(5)
        actual = "connected" if ib_service.ib.isConnected() else "disconnected"
        if actual != ib_service.status:
            ib_service.status = actual
        if ib_service.status != _last_broadcast_status:
            _last_broadcast_status = ib_service.status
            await broadcaster.publish("connection", ib_service.status_dict())


@asynccontextmanager
async def lifespan(app: FastAPI):
    ib_service = IBConnectionService(settings)
    app.state.ib_service = ib_service
    app.state.alerts_service = AlertsService(ib_service)
    try:
        await ib_service.connect()
    except Exception as e:
        # Don't crash the app if TWS isn't running yet -- the frontend shows
        # "disconnected" and the user can retry via POST /api/account/reconnect
        # once TWS/IB Gateway is up.
        logger.warning("Initial IB connect failed: %s", e)

    heartbeat_task = asyncio.create_task(_heartbeat(ib_service))
    yield
    heartbeat_task.cancel()
    await ib_service.disconnect()


app = FastAPI(title="IBKR Options Trading App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account.router)
app.include_router(positions.router)
app.include_router(chain.router)
app.include_router(orders.router)
app.include_router(killswitch.router)
app.include_router(technicals.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(recommendations.router)
app.include_router(maxpain.router)
app.include_router(unusual_whales.router)
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"ok": True, "allowOrders": settings.allow_orders}
