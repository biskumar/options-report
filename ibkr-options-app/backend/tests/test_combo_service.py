import math

from app.models.contracts import ComboLegSpec
from app.services.combo_service import _clean_price, compute_net_mid


def _resolved(action, mid, ratio=1):
    return {"leg": ComboLegSpec(expiry="20260718", strike=200, right="C", action=action, ratio=ratio), "mid": mid}


def test_net_mid_debit_vertical():
    # buy the cheaper (higher mid) leg, sell the further OTM (lower mid) leg
    # -> net debit (positive)
    legs = [_resolved("BUY", 5.0), _resolved("SELL", 2.0)]
    assert compute_net_mid(legs) == 3.0


def test_net_mid_credit_vertical():
    # sell the more expensive leg, buy the cheaper one -> net credit (negative)
    legs = [_resolved("SELL", 5.0), _resolved("BUY", 2.0)]
    assert compute_net_mid(legs) == -3.0


def test_net_mid_iron_condor_credit():
    # short iron condor: buy both wings cheap, sell both inner strikes rich
    legs = [
        _resolved("BUY", 0.5),   # put_long
        _resolved("SELL", 1.5),  # put_short
        _resolved("SELL", 1.5),  # call_short
        _resolved("BUY", 0.5),   # call_long
    ]
    assert compute_net_mid(legs) == -2.0


def test_net_mid_returns_none_if_any_leg_missing_quote():
    legs = [_resolved("BUY", 5.0), _resolved("SELL", None)]
    assert compute_net_mid(legs) is None


def test_net_mid_respects_ratio():
    legs = [_resolved("BUY", 2.0, ratio=2), _resolved("SELL", 1.0, ratio=1)]
    assert compute_net_mid(legs) == 3.0  # 2*2.0 - 1*1.0


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


def test_qualify_legs_nan_bid_ask_does_not_produce_nan_mid():
    # Reproduces the reported bug: an account without live option data for
    # the symbol returns NaN bid/ask from ib_insync. Unfiltered, `mid =
    # (nan + nan) / 2` is NaN, and FastAPI's default JSON encoder raises
    # ValueError: "Out of range float values are not JSON compliant: nan"
    # when trying to serialize it -- which surfaced to the browser as a
    # bare "Failed to fetch" with no useful error message at all.
    bid = _clean_price(float("nan"))
    ask = _clean_price(float("nan"))
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
    assert mid is None
    assert not (isinstance(mid, float) and math.isnan(mid))
