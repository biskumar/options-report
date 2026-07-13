import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from ..deps import require_connected
from ..killswitch import kill_switch
from ..models.contracts import (
    BracketLegPreview,
    BracketOrderRequest,
    BracketPreviewResponse,
    BracketSubmitRequest,
    BracketSubmitResponse,
    ComboLegPreview,
    ComboLegSpec,
    ComboPresetRequest,
    ComboPresetResponse,
    ComboPreviewRequest,
    ComboPreviewResponse,
    ComboQuoteRequest,
    ComboQuoteResponse,
    OrderLegPreview,
    OrderPreviewRequest,
    OrderPreviewResponse,
    OrderRow,
    OrderSubmitRequest,
    OrderSubmitResponse,
)
from ..services import bracket_service, combo_service, order_builder, strategy_presets
from ..services.contract_builder import build_option
from ..services.preview_store import TTL_SECONDS, preview_store

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _clean_price(value):
    """Same NaN/-1 sentinel handling as combo_service._clean_price -- an
    account without live data entitlement for a symbol returns NaN bid/ask
    here too, which otherwise crashes JSON serialization with ValueError:
    Out of range float values are not JSON compliant."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return None if value < 0 else value


@router.post("/preview", response_model=OrderPreviewResponse)
async def preview_order(request: Request, body: OrderPreviewRequest):
    """Qualifies the real contract and fetches a live quote so the
    confirmation modal renders backend-validated data, not raw frontend
    input. Does NOT touch the kill switch -- reviewing/building an order is
    always allowed, only submission is gated."""
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    contract = build_option(body.symbol.upper(), body.expiry, body.strike, body.right)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        raise HTTPException(status_code=422, detail="could not qualify this option contract with IBKR")

    tickers = await ib.reqTickersAsync(contract)
    bid = _clean_price(tickers[0].bid) if tickers else None
    ask = _clean_price(tickers[0].ask) if tickers else None
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None

    ref_price = body.limitPrice if body.orderType in ("limit", "stop_limit") else mid
    est_cost = ref_price * body.quantity * 100 if ref_price is not None else None
    if est_cost is not None and body.side == "sell":
        est_cost = -est_cost

    spec = {
        "orderKind": "single",
        "symbol": body.symbol.upper(),
        "expiry": body.expiry,
        "strike": body.strike,
        "right": body.right,
        "side": body.side,
        "quantity": body.quantity,
        "orderType": body.orderType,
        "limitPrice": body.limitPrice,
        "stopPrice": body.stopPrice,
    }
    preview_id = preview_store.put(spec)

    return OrderPreviewResponse(
        previewId=preview_id,
        legs=[
            OrderLegPreview(
                symbol=body.symbol.upper(),
                expiry=body.expiry,
                strike=body.strike,
                right=body.right,
                side=body.side,
                quantity=body.quantity,
                bid=bid,
                ask=ask,
                mid=mid,
            )
        ],
        orderType=body.orderType,
        limitPrice=body.limitPrice,
        stopPrice=body.stopPrice,
        estCost=est_cost,
        dryRun=not ib_service.settings.allow_orders,
        expiresAt=(datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)).isoformat(),
    )


@router.post("/combo/preset", response_model=ComboPresetResponse)
async def combo_preset(body: ComboPresetRequest):
    """Pure computation, no IB connection required -- lets the Strategy
    Builder UI populate a leg editor from a preset pick without a network
    round trip to TWS."""
    try:
        legs = strategy_presets.build_preset(body.name, body.expiry, body.strikes, body.right, body.side, body.expiry2)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ComboPresetResponse(legs=legs)


@router.post("/combo/quote", response_model=ComboQuoteResponse)
async def combo_quote(request: Request, body: ComboQuoteRequest):
    """Read-only live net-mid lookup for a set of legs, deliberately
    separate from /combo/preview -- this does NOT create a preview_id or
    touch the preview store, so it's safe to call repeatedly (e.g. every
    time the leg editor changes) without leaving throwaway previews
    behind or implying anything is about to be submitted. Lets the UI show
    "here's the live net mid" next to the limit price field *before* the
    user commits to a number, instead of only finding out after clicking
    Preview."""
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    try:
        resolved = await combo_service.qualify_legs(ib, body.symbol.upper(), body.legs)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    net_mid = combo_service.compute_net_mid(resolved)
    return ComboQuoteResponse(
        legs=[
            ComboLegPreview(**r["leg"].model_dump(), bid=r["bid"], ask=r["ask"], mid=r["mid"], conId=r["contract"].conId)
            for r in resolved
        ],
        netMid=net_mid,
    )


@router.post("/combo/preview", response_model=ComboPreviewResponse)
async def preview_combo(request: Request, body: ComboPreviewRequest):
    """Same backend-validated preview contract as the single-leg flow
    (see preview_order docstring above), extended to multiple legs."""
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    try:
        resolved = await combo_service.qualify_legs(ib, body.symbol.upper(), body.legs)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    net_mid = combo_service.compute_net_mid(resolved)
    ref_price = body.limitPrice if body.orderType == "limit" else net_mid
    est_cost = ref_price * body.quantity * 100 if ref_price is not None else None

    spec = {
        "orderKind": "combo",
        "symbol": body.symbol.upper(),
        "legs": [leg.model_dump() for leg in body.legs],
        "quantity": body.quantity,
        "orderType": body.orderType,
        "limitPrice": body.limitPrice,
    }
    preview_id = preview_store.put(spec)

    return ComboPreviewResponse(
        previewId=preview_id,
        symbol=body.symbol.upper(),
        quantity=body.quantity,
        legs=[
            ComboLegPreview(**r["leg"].model_dump(), bid=r["bid"], ask=r["ask"], mid=r["mid"], conId=r["contract"].conId)
            for r in resolved
        ],
        orderType=body.orderType,
        limitPrice=body.limitPrice,
        netMid=net_mid,
        estCost=est_cost,
        dryRun=not ib_service.settings.allow_orders,
        expiresAt=(datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)).isoformat(),
    )


@router.post("/bracket/preview", response_model=BracketPreviewResponse)
async def preview_bracket(request: Request, body: BracketOrderRequest):
    """Entry (limit) + take-profit (limit) + stop-loss (stop), previewed
    as one linked group. Same backend-validated preview contract as the
    other order flows -- also rejects an inverted bracket (e.g. a BUY
    with the stop above the entry) before it ever reaches qualify/quote,
    let alone a live account."""
    try:
        bracket_service.validate_bracket_prices(body.side, body.entryLimitPrice, body.targetLimitPrice, body.stopPrice)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    contract = build_option(body.symbol.upper(), body.expiry, body.strike, body.right)
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        raise HTTPException(status_code=422, detail="could not qualify this option contract with IBKR")

    bid, ask, mid = await bracket_service.resolve_quote(ib, contract)

    entry_action = "BUY" if body.side == "buy" else "SELL"
    exit_action = "SELL" if body.side == "buy" else "BUY"
    est_cost = body.entryLimitPrice * body.quantity * 100
    if body.side == "sell":
        est_cost = -est_cost

    spec = {
        "orderKind": "bracket",
        "symbol": body.symbol.upper(),
        "expiry": body.expiry,
        "strike": body.strike,
        "right": body.right,
        "side": body.side,
        "quantity": body.quantity,
        "entryLimitPrice": body.entryLimitPrice,
        "targetLimitPrice": body.targetLimitPrice,
        "stopPrice": body.stopPrice,
    }
    preview_id = preview_store.put(spec)

    return BracketPreviewResponse(
        previewId=preview_id,
        symbol=body.symbol.upper(),
        expiry=body.expiry,
        strike=body.strike,
        right=body.right,
        quantity=body.quantity,
        legs=[
            BracketLegPreview(role="entry", action=entry_action, orderType="LMT", price=body.entryLimitPrice),
            BracketLegPreview(role="target", action=exit_action, orderType="LMT", price=body.targetLimitPrice),
            BracketLegPreview(role="stop", action=exit_action, orderType="STP", price=body.stopPrice),
        ],
        bid=bid,
        ask=ask,
        mid=mid,
        estCost=est_cost,
        dryRun=not ib_service.settings.allow_orders,
        expiresAt=(datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)).isoformat(),
    )


@router.post("/bracket/submit", response_model=BracketSubmitResponse)
async def submit_bracket(request: Request, body: BracketSubmitRequest):
    if kill_switch.engaged:
        raise HTTPException(status_code=423, detail="Trading is disabled: kill switch engaged")

    spec = preview_store.pop(body.previewId)
    if spec is None or spec.get("orderKind") != "bracket":
        raise HTTPException(status_code=410, detail="Preview expired or already used -- request a new preview")

    ib_service = request.app.state.ib_service
    if not ib_service.settings.allow_orders:
        return BracketSubmitResponse(orderIds=None, status="DRY_RUN", dryRun=True)

    # Defensive re-check: never rely solely on the check above.
    if kill_switch.engaged:
        raise HTTPException(status_code=423, detail="Trading is disabled: kill switch engaged")

    require_connected(ib_service)
    ib = ib_service.ib

    contract = build_option(spec["symbol"], spec["expiry"], spec["strike"], spec["right"])
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        raise HTTPException(status_code=422, detail="could not qualify contract at submit time")

    bracket = bracket_service.build_bracket_orders(
        ib, spec["side"], spec["quantity"], spec["entryLimitPrice"], spec["targetLimitPrice"], spec["stopPrice"]
    )
    trades = [ib.placeOrder(contract, order) for order in bracket]
    return BracketSubmitResponse(
        orderIds=[t.order.orderId for t in trades],
        status=trades[0].orderStatus.status or "Submitted",
        dryRun=False,
    )


@router.post("/submit", response_model=OrderSubmitResponse)
async def submit_order(request: Request, body: OrderSubmitRequest):
    if kill_switch.engaged:
        raise HTTPException(status_code=423, detail="Trading is disabled: kill switch engaged")

    spec = preview_store.pop(body.previewId)
    if spec is None:
        raise HTTPException(status_code=410, detail="Preview expired or already used -- request a new preview")

    ib_service = request.app.state.ib_service
    if not ib_service.settings.allow_orders:
        return OrderSubmitResponse(orderId=None, status="DRY_RUN", dryRun=True)

    # Defensive re-check: never rely solely on the check above.
    if kill_switch.engaged:
        raise HTTPException(status_code=423, detail="Trading is disabled: kill switch engaged")

    require_connected(ib_service)
    ib = ib_service.ib

    if spec["orderKind"] == "combo":
        legs = [ComboLegSpec(**leg) for leg in spec["legs"]]
        try:
            resolved = await combo_service.qualify_legs(ib, spec["symbol"], legs)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        contract = combo_service.build_combo_contract(spec["symbol"], resolved)
        order = order_builder.build_combo_order(spec["orderType"], spec["quantity"], spec["limitPrice"])
    else:
        contract = build_option(spec["symbol"], spec["expiry"], spec["strike"], spec["right"])
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            raise HTTPException(status_code=422, detail="could not qualify contract at submit time")
        order = order_builder.build_single_leg_order(
            spec["side"], spec["quantity"], spec["orderType"], spec["limitPrice"], spec["stopPrice"]
        )

    trade = ib.placeOrder(contract, order)
    return OrderSubmitResponse(orderId=trade.order.orderId, status=trade.orderStatus.status or "Submitted", dryRun=False)


@router.get("", response_model=list[OrderRow])
async def list_orders(request: Request):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    rows = []
    for t in ib.trades():
        rows.append(
            OrderRow(
                orderId=t.order.orderId,
                permId=t.order.permId,
                symbol=t.contract.symbol,
                action=t.order.action,
                orderType=t.order.orderType,
                totalQuantity=t.order.totalQuantity,
                lmtPrice=t.order.lmtPrice or None,
                status=t.orderStatus.status,
                filled=t.orderStatus.filled,
                remaining=t.orderStatus.remaining,
                avgFillPrice=t.orderStatus.avgFillPrice or None,
            )
        )
    return rows


@router.post("/{order_id}/cancel")
async def cancel_order(request: Request, order_id: int):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    ib = ib_service.ib

    trade = next((t for t in ib.trades() if t.order.orderId == order_id), None)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")

    ib.cancelOrder(trade.order)
    return {"orderId": order_id, "status": "CancelRequested"}
