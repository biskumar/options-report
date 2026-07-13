from fastapi import APIRouter, Request

from ..deps import require_connected
from ..models.domain import PnLSnapshot, Position

router = APIRouter(prefix="/api", tags=["positions"])


@router.get("/positions", response_model=list[Position])
async def positions(request: Request):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    rows = []
    for p in ib.positions():
        c = p.contract
        ticker = ib.ticker(c)
        market_price = ticker.marketPrice() if ticker else None
        market_value = market_price * p.position * (100 if c.secType == "OPT" else 1) if market_price else None
        unrealized = (market_value - p.avgCost * p.position) if market_value is not None else None
        rows.append(
            Position(
                account=p.account,
                conId=c.conId,
                symbol=c.symbol,
                secType=c.secType,
                expiry=getattr(c, "lastTradeDateOrContractMonth", None) or None,
                strike=getattr(c, "strike", None) or None,
                right=getattr(c, "right", None) or None,
                position=p.position,
                avgCost=p.avgCost,
                marketPrice=market_price,
                marketValue=market_value,
                unrealizedPnL=unrealized,
            )
        )
    return rows


@router.get("/pnl", response_model=list[PnLSnapshot])
async def pnl(request: Request):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    accounts = ib.managedAccounts() or ([ib_service.settings.ib_account] if ib_service.settings.ib_account else [])
    snapshots = []
    for account in accounts:
        if not account:
            continue
        await ib_service._subscribe_pnl(account)
        current = next((p for p in ib.pnl() if p.account == account), None)
        if current:
            snapshots.append(
                PnLSnapshot(
                    account=account,
                    dailyPnL=current.dailyPnL,
                    unrealizedPnL=current.unrealizedPnL,
                    realizedPnL=current.realizedPnL,
                )
            )
    return snapshots
