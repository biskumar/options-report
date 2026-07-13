from app.services.us_watchlist_service import _clean_price


def test_clean_price_handles_none_and_nan():
    assert _clean_price(None) is None
    assert _clean_price(float("nan")) is None


def test_clean_price_rejects_negative_sentinel():
    # IB returns -1 for "not available" on bid/ask/last/close when the
    # account lacks a market data entitlement for the symbol -- this used
    # to show up as e.g. "last": -1.0 in the US Watchlist instead of "--".
    assert _clean_price(-1.0) is None


def test_clean_price_accepts_zero_and_positive():
    assert _clean_price(0.0) == 0.0
    assert _clean_price(123.45) == 123.45
