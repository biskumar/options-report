from fastapi import APIRouter, HTTPException, Query, Request

from ..deps import require_connected
from ..models.domain import ChainResponse
from ..services import chain_service

router = APIRouter(prefix="/api/chain", tags=["chain"])


@router.get("/expiries")
async def expiries(request: Request, symbol: str = Query(...)):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    try:
        return await chain_service.get_expiries(ib_service.ib, symbol.upper())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("", response_model=ChainResponse)
async def chain(request: Request, symbol: str = Query(...), expiry: str = Query(...)):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    try:
        return await chain_service.get_full_chain(ib_service.ib, symbol.upper(), expiry)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/greeks")
async def greeks(
    request: Request,
    symbol: str = Query(...),
    expiry: str = Query(...),
    strike: float = Query(...),
    right: str = Query(..., pattern="^[CP]$"),
):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    try:
        return await chain_service.get_greeks(ib_service.ib, symbol.upper(), expiry, strike, right)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
