from fastapi import APIRouter, HTTPException, Query

from ..services import legacy_bridge

router = APIRouter(prefix="/api/technicals", tags=["technicals"])


@router.get("/{symbol}")
async def technicals(symbol: str, period: str = Query("6mo"), interval: str = Query("1d")):
    try:
        return await legacy_bridge.get_price_history(symbol.upper(), period, interval)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
