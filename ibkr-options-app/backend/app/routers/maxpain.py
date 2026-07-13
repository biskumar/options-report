from fastapi import APIRouter, HTTPException, Query, Request

from ..deps import require_connected
from ..services import maxpain_service

router = APIRouter(prefix="/api/maxpain", tags=["maxpain"])


@router.get("")
async def maxpain(
    request: Request,
    symbol: str = Query(...),
    expiry: str = Query(...),
    strike_window: int = Query(20, ge=1, le=100),
):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    try:
        return await maxpain_service.calc_max_pain(ib_service.ib, symbol.upper(), expiry, strike_window)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
