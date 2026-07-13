import pytest

from app.services.order_builder import build_combo_order, build_single_leg_order


def test_market_buy():
    o = build_single_leg_order("buy", 2, "market")
    assert o.action == "BUY"
    assert o.orderType == "MKT"
    assert o.totalQuantity == 2


def test_market_sell():
    o = build_single_leg_order("sell", 3, "market")
    assert o.action == "SELL"
    assert o.orderType == "MKT"


def test_limit_buy_sets_price():
    o = build_single_leg_order("buy", 1, "limit", limit_price=2.5)
    assert o.orderType == "LMT"
    assert o.lmtPrice == 2.5
    assert o.action == "BUY"


def test_limit_sell_is_day_only():
    # A limit order closing a position must be explicitly good-for-the-day,
    # not left to IB's implicit blank-tif default.
    o = build_single_leg_order("sell", 5, "limit", limit_price=3.2)
    assert o.action == "SELL"
    assert o.tif == "DAY"


def test_all_single_leg_order_types_are_day_only():
    assert build_single_leg_order("buy", 1, "market").tif == "DAY"
    assert build_single_leg_order("sell", 1, "stop", stop_price=1.1).tif == "DAY"
    assert build_single_leg_order("buy", 1, "stop_limit", limit_price=2.0, stop_price=1.8).tif == "DAY"


def test_limit_requires_price():
    with pytest.raises(ValueError):
        build_single_leg_order("buy", 1, "limit")


def test_stop_sets_price():
    o = build_single_leg_order("sell", 1, "stop", stop_price=1.1)
    assert o.orderType == "STP"
    assert o.auxPrice == 1.1


def test_stop_requires_price():
    with pytest.raises(ValueError):
        build_single_leg_order("sell", 1, "stop")


def test_stop_limit_sets_both_prices():
    o = build_single_leg_order("buy", 1, "stop_limit", limit_price=2.0, stop_price=1.8)
    assert o.orderType == "STP LMT"
    assert o.lmtPrice == 2.0
    assert o.auxPrice == 1.8


def test_stop_limit_requires_both_prices():
    with pytest.raises(ValueError):
        build_single_leg_order("buy", 1, "stop_limit", limit_price=2.0)


def test_unknown_order_type_rejected():
    with pytest.raises(ValueError):
        build_single_leg_order("buy", 1, "trailing_stop")


def test_combo_order_action_is_always_buy():
    # ib_insync/TWS convention: BUY on the Bag regardless of debit/credit;
    # the lmtPrice sign carries debit(+)/credit(-).
    o = build_combo_order("limit", 1, limit_price=1.5)
    assert o.action == "BUY"
    assert o.orderType == "LMT"
    assert o.lmtPrice == 1.5
    assert o.tif == "DAY"


def test_combo_order_credit_uses_negative_price():
    o = build_combo_order("limit", 2, limit_price=-0.75)
    assert o.action == "BUY"
    assert o.lmtPrice == -0.75
    assert o.totalQuantity == 2


def test_combo_order_market():
    o = build_combo_order("market", 1)
    assert o.orderType == "MKT"
    assert o.action == "BUY"


def test_combo_order_limit_requires_price():
    with pytest.raises(ValueError):
        build_combo_order("limit", 1)


def test_combo_order_rejects_stop_types():
    with pytest.raises(ValueError):
        build_combo_order("stop", 1, limit_price=1.0)
