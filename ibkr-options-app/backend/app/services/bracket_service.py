"""Bracket order helpers: a single entry (limit) order linked to a
take-profit (limit) and a stop-loss (stop) exit, submitted together so TWS
treats them as one linked group -- filling either exit cancels the other.
Built on ib_insync's own IB.bracketOrder(), which already handles the
orderId/parentId chaining and the transmit=False/False/True sequencing
that makes the three legs land atomically instead of one at a time."""

import math

from ib_insync import IB, BracketOrder


def _clean_price(value):
    """Same NaN/-1 sentinel handling as combo_service._clean_price -- an
    account without live data entitlement for a symbol returns NaN bid/ask
    here too."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return None if value < 0 else value


async def resolve_quote(ib: IB, contract) -> tuple[float | None, float | None, float | None]:
    """Live (bid, ask, mid) for the already-qualified entry contract, NaN/-1
    sanitized. mid is None (not the entry price) unless a real bid/ask is
    available -- callers use the user's own entryLimitPrice for est. cost,
    this is display-only."""
    tickers = await ib.reqTickersAsync(contract)
    bid = _clean_price(tickers[0].bid) if tickers else None
    ask = _clean_price(tickers[0].ask) if tickers else None
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
    return bid, ask, mid


def validate_bracket_prices(side: str, entry: float, target: float, stop: float) -> None:
    """Catches an inverted bracket before it reaches a live account. For a
    BUY (open long): stop < entry < target. For a SELL (open short): the
    exits are mirrored, so target < entry < stop."""
    if side == "buy":
        if not (stop < entry < target):
            raise ValueError(
                f"invalid BUY bracket: requires stop ({stop}) < entry ({entry}) < target ({target})"
            )
    else:
        if not (target < entry < stop):
            raise ValueError(
                f"invalid SELL bracket: requires target ({target}) < entry ({entry}) < stop ({stop})"
            )


def build_bracket_orders(
    ib: IB,
    side: str,
    quantity: int,
    entry_price: float,
    target_price: float,
    stop_price: float,
) -> BracketOrder:
    action = "BUY" if side == "buy" else "SELL"
    # tif="DAY" is forwarded via **kwargs to all three orders -- same
    # explicit good-for-the-day-only convention as every other order this
    # app places (see order_builder.py).
    return ib.bracketOrder(action, quantity, entry_price, target_price, stop_price, tif="DAY")
