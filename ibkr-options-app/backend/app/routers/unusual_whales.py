from fastapi import APIRouter, HTTPException, Query

from ..services import unusual_whales_service, us_watchlist_service

router = APIRouter(prefix="/api/unusualwhales", tags=["unusualwhales"])


@router.get("/watchlist")
async def watchlist(min_premium: int = Query(unusual_whales_service.DEFAULT_MIN_PREMIUM, ge=0)):
    """Deliberately uncached (unlike /api/watchlist/us's IBKR quote scan) --
    the whole point of this screen is fresh flow/IV/GEX on every page
    load. Doesn't require an IBKR connection; this is Unusual Whales data
    only."""
    tickers = [t["symbol"] for t in us_watchlist_service.load_static_list()]
    try:
        return await unusual_whales_service.scan_watchlist(tickers, min_premium)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
