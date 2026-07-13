from ib_insync import LimitOrder, MarketOrder, Order, StopLimitOrder, StopOrder

# ib_insync/TWS combo (Bag) convention: the parent order's action is always
# "BUY" regardless of whether the strategy nets a debit or credit -- the
# *sign* of lmtPrice carries that information (positive = net debit paid,
# negative = net credit received). Each leg's own BUY/SELL direction is set
# independently on its ComboLeg (see combo_service.build_combo_contract).
# This is the single most bug-prone convention in the app -- never place a
# live combo order without hand-verifying the computed net price against
# the chain's live bid/ask first (see plan verification checklist).
COMBO_ORDER_ACTION = "BUY"


def build_single_leg_order(
    side: str,
    quantity: int,
    order_type: str,
    limit_price: float | None = None,
    stop_price: float | None = None,
) -> Order:
    action = "BUY" if side == "buy" else "SELL"

    # tif="DAY" is set explicitly on every order rather than left blank --
    # IB's API treats a blank tif as DAY by default, but a closing sell
    # order needs to be *verifiably* good-for-the-day-only, not silently
    # dependent on an implicit default that could change per account/order
    # type.
    if order_type == "market":
        return MarketOrder(action, quantity, tif="DAY")
    if order_type == "limit":
        if limit_price is None:
            raise ValueError("limit_price is required for a limit order")
        return LimitOrder(action, quantity, limit_price, tif="DAY")
    if order_type == "stop":
        if stop_price is None:
            raise ValueError("stop_price is required for a stop order")
        return StopOrder(action, quantity, stop_price, tif="DAY")
    if order_type == "stop_limit":
        if limit_price is None or stop_price is None:
            raise ValueError("limit_price and stop_price are required for a stop-limit order")
        return StopLimitOrder(action, quantity, limit_price, stop_price, tif="DAY")

    raise ValueError(f"unknown order_type: {order_type}")


def build_combo_order(order_type: str, quantity: int, limit_price: float | None = None) -> Order:
    if order_type not in ("market", "limit"):
        raise ValueError(f"combo orders only support market/limit, got: {order_type}")

    order = Order()
    order.action = COMBO_ORDER_ACTION
    order.orderType = "MKT" if order_type == "market" else "LMT"
    order.totalQuantity = quantity
    order.tif = "DAY"
    if order_type == "limit":
        if limit_price is None:
            raise ValueError("limit_price is required for a limit combo order")
        order.lmtPrice = limit_price
    order.transmit = True
    return order
