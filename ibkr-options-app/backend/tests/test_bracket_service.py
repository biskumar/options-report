import math

import pytest

from app.services.bracket_service import _clean_price, validate_bracket_prices


def test_clean_price_handles_none_and_nan():
    assert _clean_price(None) is None
    assert _clean_price(float("nan")) is None


def test_clean_price_rejects_negative_sentinel():
    assert _clean_price(-1.0) is None


def test_clean_price_accepts_zero_and_positive():
    assert _clean_price(0.0) == 0.0
    assert _clean_price(1.43) == 1.43


def test_buy_bracket_valid_ordering():
    # stop < entry < target
    validate_bracket_prices("buy", entry=5.0, target=8.0, stop=3.0)


def test_buy_bracket_rejects_target_below_entry():
    with pytest.raises(ValueError):
        validate_bracket_prices("buy", entry=5.0, target=4.0, stop=3.0)


def test_buy_bracket_rejects_stop_above_entry():
    with pytest.raises(ValueError):
        validate_bracket_prices("buy", entry=5.0, target=8.0, stop=6.0)


def test_sell_bracket_valid_ordering():
    # target < entry < stop
    validate_bracket_prices("sell", entry=5.0, target=3.0, stop=8.0)


def test_sell_bracket_rejects_target_above_entry():
    with pytest.raises(ValueError):
        validate_bracket_prices("sell", entry=5.0, target=6.0, stop=8.0)


def test_sell_bracket_rejects_stop_below_entry():
    with pytest.raises(ValueError):
        validate_bracket_prices("sell", entry=5.0, target=3.0, stop=4.0)


def test_qualify_nan_bid_ask_does_not_produce_nan_mid():
    bid = _clean_price(float("nan"))
    ask = _clean_price(float("nan"))
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
    assert mid is None
    assert not (isinstance(mid, float) and math.isnan(mid))
