from fastapi import HTTPException


def require_connected(ib_service):
    """Fast, non-blocking guard for data/order endpoints. Deliberately does
    NOT attempt to reconnect inline (that would mean every request blocks
    for the full connect timeout while TWS is down) -- reconnection only
    happens via the background heartbeat or an explicit
    POST /api/account/reconnect call."""
    if not ib_service.ib.isConnected():
        raise HTTPException(
            status_code=503,
            detail="Not connected to IBKR -- start TWS/IB Gateway, then POST /api/account/reconnect",
        )
