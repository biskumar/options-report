import asyncio
import logging
import math

from ib_insync import IB, util as ib_util

from .broadcaster import broadcaster
from .config import Settings

logger = logging.getLogger("ib_service")
ib_util.logToConsole(logging.WARNING)


def _clean(value):
    """ib_insync tickers use float('nan') for "no data yet". NaN survives
    unfiltered into json.dumps and raises ValueError: Out of range float
    values are not JSON compliant -- same failure mode as the earlier
    combo/preview NaN bug, but here it would crash the WebSocket broadcast
    for every connected client the next time any subscribed contract ticks
    with no data, not just one HTTP response. Use for fields that can
    legitimately be negative (greeks)."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _clean_price(value):
    """Same as _clean, plus IB's -1 sentinel for "not available" (a symbol
    lacking a live/delayed data entitlement). A real bid/ask/last is never
    negative. Use for price fields only, never for greeks (delta/theta are
    routinely negative)."""
    value = _clean(value)
    return None if value is not None and value < 0 else value

# IB error codes that mean the socket connection itself is down or failed to
# come up. Most codes >= 1000 are per-request warnings (e.g. 10168 "market
# data not subscribed") or informational farm-connection messages (2100s) --
# those must NOT flip the app into a disconnected-looking state, or a single
# unsubscribed symbol would incorrectly block trading on every other symbol.
_FATAL_ERROR_CODES = {502, 504, 1100, 1300}


class IBConnectionService:
    """Owns a single persistent ib_insync IB() connection for the whole
    app's lifetime, driven entirely through *Async methods so it shares
    FastAPI/uvicorn's event loop instead of ib_insync's own script-style
    loop management. Never call the plain sync ib.connect()/ib.sleep()
    anywhere in this app -- see plan Section 8 risk note."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.ib = IB()
        self.status = "disconnected"  # disconnected | connecting | connected | error
        self.last_error: str | None = None
        self._pnl_subscribed_account: str | None = None
        self._register_event_handlers()

    def _register_event_handlers(self):
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error
        self.ib.orderStatusEvent += self._on_order_status
        self.ib.execDetailsEvent += self._on_exec_details
        self.ib.pendingTickersEvent += self._on_tickers
        self.ib.positionEvent += self._on_position
        self.ib.pnlEvent += self._on_pnl

    async def connect(self):
        if self.ib.isConnected():
            return
        self.status = "connecting"
        await self._broadcast_status()
        try:
            await self.ib.connectAsync(
                self.settings.ib_host,
                self.settings.ib_port,
                clientId=self.settings.ib_client_id,
                timeout=10,
                readonly=False,
            )
            self.ib.reqMarketDataType(1)  # live; IB falls back to delayed (3) automatically if unsubscribed
            self.last_error = None
        except Exception as e:
            self.status = "error"
            self.last_error = "Could not connect to TWS/IB Gateway on port 7496 — start TWS with API enabled, then click Reconnect"
            await self._broadcast_status()
            raise

    async def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()

    def status_dict(self) -> dict:
        return {
            "status": self.status,
            "host": self.settings.ib_host,
            "port": self.settings.ib_port,
            "clientId": self.settings.ib_client_id,
            "lastError": self.last_error,
        }

    async def _broadcast_status(self):
        await broadcaster.publish("connection", self.status_dict())

    # --- event handlers -------------------------------------------------
    # ib_insync fires these synchronously on the same running loop (via
    # connectAsync), so scheduling a task here is safe and non-blocking.

    def _on_connected(self):
        self.status = "connected"
        self.last_error = None
        asyncio.create_task(self._broadcast_status())
        if self.settings.ib_account:
            asyncio.create_task(self._subscribe_pnl(self.settings.ib_account))

    def _on_disconnected(self):
        self.status = "disconnected"
        asyncio.create_task(self._broadcast_status())

    def _on_error(self, reqId, errorCode, errorString, contract):
        if errorCode in _FATAL_ERROR_CODES:
            self.last_error = f"[{errorCode}] {errorString}"
            self.status = "error"
            asyncio.create_task(self._broadcast_status())
        elif errorCode >= 1000:
            logger.warning("IB warning %s: %s", errorCode, errorString)
        else:
            logger.info("IB info %s: %s", errorCode, errorString)

    def _on_order_status(self, trade):
        payload = {
            "orderId": trade.order.orderId,
            "permId": trade.order.permId,
            "status": trade.orderStatus.status,
            "filled": trade.orderStatus.filled,
            "remaining": trade.orderStatus.remaining,
            "avgFillPrice": trade.orderStatus.avgFillPrice,
        }
        asyncio.create_task(broadcaster.publish("order_status", payload))

    def _on_exec_details(self, trade, fill):
        payload = {
            "orderId": trade.order.orderId,
            "execId": fill.execution.execId,
            "shares": fill.execution.shares,
            "price": fill.execution.price,
            "time": str(fill.execution.time),
        }
        asyncio.create_task(broadcaster.publish("execution", payload))

    def _on_tickers(self, tickers):
        for t in tickers:
            payload = {
                "conId": t.contract.conId,
                "symbol": t.contract.symbol,
                "bid": _clean_price(t.bid),
                "ask": _clean_price(t.ask),
                "last": _clean_price(t.last),
            }
            greeks = t.modelGreeks
            if greeks is not None:
                payload["greeks"] = {
                    "delta": _clean(greeks.delta),
                    "gamma": _clean(greeks.gamma),
                    "theta": _clean(greeks.theta),
                    "vega": _clean(greeks.vega),
                    "iv": _clean(greeks.impliedVol),
                }
            asyncio.create_task(broadcaster.publish("quote", payload))

    def _on_position(self, position):
        payload = {
            "account": position.account,
            "conId": position.contract.conId,
            "symbol": position.contract.symbol,
            "position": position.position,
            "avgCost": position.avgCost,
        }
        asyncio.create_task(broadcaster.publish("position", payload))

    def _on_pnl(self, pnl):
        payload = {
            "account": pnl.account,
            "dailyPnL": pnl.dailyPnL,
            "unrealizedPnL": pnl.unrealizedPnL,
            "realizedPnL": pnl.realizedPnL,
        }
        asyncio.create_task(broadcaster.publish("pnl", payload))

    async def _subscribe_pnl(self, account: str):
        if self._pnl_subscribed_account == account:
            return
        self.ib.reqPnL(account)
        self._pnl_subscribed_account = account
