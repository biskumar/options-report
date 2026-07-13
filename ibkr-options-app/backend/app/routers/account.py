from fastapi import APIRouter, Request

from ..deps import require_connected
from ..killswitch import kill_switch
from ..models.domain import AccountSummary, ConnectionStatus

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/status", response_model=dict)
async def status(request: Request):
    ib_service = request.app.state.ib_service
    return {
        "connection": ib_service.status_dict(),
        "killSwitch": kill_switch.as_dict(),
    }


@router.post("/reconnect", response_model=ConnectionStatus)
async def reconnect(request: Request):
    ib_service = request.app.state.ib_service
    try:
        await ib_service.connect()
    except Exception:
        pass  # status_dict() already reflects the error; frontend shows the banner
    return ib_service.status_dict()


@router.get("/summary", response_model=list[AccountSummary])
async def summary(request: Request):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib
    values = await ib.accountSummaryAsync()

    by_account: dict[str, dict] = {}
    tag_map = {
        "NetLiquidation": "netLiquidation",
        "BuyingPower": "buyingPower",
        "TotalCashValue": "totalCashValue",
        "GrossPositionValue": "grossPositionValue",
    }
    for v in values:
        if v.tag not in tag_map:
            continue
        acct = by_account.setdefault(v.account, {"account": v.account})
        try:
            acct[tag_map[v.tag]] = float(v.value)
        except ValueError:
            pass

    return [AccountSummary(**acct) for acct in by_account.values()]
