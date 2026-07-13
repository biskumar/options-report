import math

from app.routers.orders import _clean_price


def test_clean_price_handles_none_and_nan():
    assert _clean_price(None) is None
    assert _clean_price(float("nan")) is None


def test_clean_price_rejects_negative_sentinel():
    # IB returns -1 for "not available" on bid/ask when the account lacks
    # a market data entitlement for the symbol.
    assert _clean_price(-1.0) is None


def test_clean_price_accepts_zero_and_positive():
    assert _clean_price(0.0) == 0.0
    assert _clean_price(1.43) == 1.43


def test_single_leg_mid_from_nan_bid_ask_does_not_produce_nan():
    # Reproduces the reported bug: /api/orders/preview crashed with
    # ValueError: Out of range float values are not JSON compliant: nan
    # for a symbol without live option data, because bid/ask were used
    # unfiltered when computing mid.
    bid = _clean_price(float("nan"))
    ask = _clean_price(float("nan"))
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
    assert mid is None
    assert not (isinstance(mid, float) and math.isnan(mid))
