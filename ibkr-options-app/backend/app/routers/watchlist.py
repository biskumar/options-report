from fastapi import APIRouter, Query, Request

from ..services import legacy_bridge, us_watchlist_service

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("")
async def watchlist(refresh: bool = Query(False)):
    """Wraps india_morning_scan.run_morning_scan() -- a slow, multi-minute
    batch job over ~60 NSE symbols -- via a server-side TTL cache (see
    legacy_bridge.get_watchlist). The first call after a cold start or
    cache expiry will take a while; the UI should show a loading state
    rather than assuming this responds instantly."""
    return await legacy_bridge.get_watchlist(force_refresh=refresh)


@router.get("/us/tickers")
async def us_watchlist_tickers():
    """Static symbol/name list only, no IB call -- for populating a ticker
    selector (e.g. the Chain page dropdown) without triggering a live quote
    fetch for all 37 symbols just to show their names."""
    return us_watchlist_service.load_static_list()


@router.get("/us")
async def us_watchlist(request: Request):
    """The 37 US tickers from the repo-root US_watchlist.json, enriched
    with a live quote snapshot when IBKR is connected. Falls back to the
    static list (no prices) when disconnected -- unlike the NSE scan above,
    this is fast either way since it's not a multi-minute batch job."""
    ib_service = request.app.state.ib_service
    return await us_watchlist_service.get_us_watchlist(ib_service.ib)
