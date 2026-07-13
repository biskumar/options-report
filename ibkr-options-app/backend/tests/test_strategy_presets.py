import pytest

from app.services.strategy_presets import (
    build_preset,
    butterfly,
    calendar_spread,
    iron_condor,
    straddle,
    strangle,
    vertical_spread,
)


def test_vertical_spread_actions():
    legs = vertical_spread("20260718", 200, 210, "C")
    assert legs[0].strike == 200 and legs[0].action == "BUY"
    assert legs[1].strike == 210 and legs[1].action == "SELL"
    assert all(leg.right == "C" for leg in legs)


def test_straddle_long():
    legs = straddle("20260718", 200, side="long")
    assert legs[0].right == "C" and legs[0].action == "BUY"
    assert legs[1].right == "P" and legs[1].action == "BUY"
    assert legs[0].strike == legs[1].strike == 200


def test_straddle_short():
    legs = straddle("20260718", 200, side="short")
    assert all(leg.action == "SELL" for leg in legs)


def test_strangle_actions():
    legs = strangle("20260718", call_strike=220, put_strike=180, side="long")
    assert legs[0].right == "C" and legs[0].strike == 220 and legs[0].action == "BUY"
    assert legs[1].right == "P" and legs[1].strike == 180 and legs[1].action == "BUY"


def test_iron_condor_is_net_credit_by_construction():
    legs = iron_condor("20260718", put_long=180, put_short=190, call_short=210, call_long=220)
    by_strike = {leg.strike: leg for leg in legs}
    assert by_strike[180].right == "P" and by_strike[180].action == "BUY"
    assert by_strike[190].right == "P" and by_strike[190].action == "SELL"
    assert by_strike[210].right == "C" and by_strike[210].action == "SELL"
    assert by_strike[220].right == "C" and by_strike[220].action == "BUY"


def test_iron_condor_rejects_unordered_strikes():
    with pytest.raises(ValueError):
        iron_condor("20260718", put_long=190, put_short=180, call_short=210, call_long=220)


def test_build_preset_vertical():
    legs = build_preset("vertical", "20260718", [200, 210], "C", None)
    assert len(legs) == 2


def test_build_preset_vertical_requires_right():
    with pytest.raises(ValueError):
        build_preset("vertical", "20260718", [200, 210], None, None)


def test_build_preset_straddle_requires_one_strike():
    with pytest.raises(ValueError):
        build_preset("straddle", "20260718", [200, 210], None, "long")


def test_build_preset_iron_condor_requires_four_strikes():
    with pytest.raises(ValueError):
        build_preset("iron_condor", "20260718", [180, 190, 210], None, None)


def test_build_preset_unknown_name():
    with pytest.raises(ValueError):
        build_preset("not_a_real_preset", "20260718", [200], None, None)


def test_butterfly_long_is_net_debit_by_construction():
    legs = butterfly("20260718", low_strike=190, mid_strike=200, high_strike=210, right="C", side="long")
    by_strike = {leg.strike: leg for leg in legs}
    assert by_strike[190].action == "BUY" and by_strike[190].ratio == 1
    assert by_strike[200].action == "SELL" and by_strike[200].ratio == 2
    assert by_strike[210].action == "BUY" and by_strike[210].ratio == 1
    assert all(leg.right == "C" for leg in legs)


def test_butterfly_short_inverts_every_leg():
    legs = butterfly("20260718", low_strike=190, mid_strike=200, high_strike=210, right="P", side="short")
    by_strike = {leg.strike: leg for leg in legs}
    assert by_strike[190].action == "SELL"
    assert by_strike[200].action == "BUY" and by_strike[200].ratio == 2
    assert by_strike[210].action == "SELL"


def test_butterfly_rejects_unordered_strikes():
    with pytest.raises(ValueError):
        butterfly("20260718", low_strike=200, mid_strike=190, high_strike=210, right="C")


def test_calendar_spread_long_sells_near_buys_far():
    legs = calendar_spread(near_expiry="20260718", far_expiry="20260815", strike=200, right="C", side="long")
    by_expiry = {leg.expiry: leg for leg in legs}
    assert by_expiry["20260718"].action == "SELL"
    assert by_expiry["20260815"].action == "BUY"
    assert all(leg.strike == 200 for leg in legs)


def test_calendar_spread_short_inverts_both_legs():
    legs = calendar_spread(near_expiry="20260718", far_expiry="20260815", strike=200, right="P", side="short")
    by_expiry = {leg.expiry: leg for leg in legs}
    assert by_expiry["20260718"].action == "BUY"
    assert by_expiry["20260815"].action == "SELL"


def test_calendar_spread_rejects_far_expiry_not_after_near():
    with pytest.raises(ValueError):
        calendar_spread(near_expiry="20260815", far_expiry="20260718", strike=200, right="C")


def test_build_preset_butterfly():
    legs = build_preset("butterfly", "20260718", [190, 200, 210], "C", "long")
    assert len(legs) == 3


def test_build_preset_butterfly_requires_three_strikes():
    with pytest.raises(ValueError):
        build_preset("butterfly", "20260718", [190, 210], "C", "long")


def test_build_preset_calendar_spread():
    legs = build_preset("calendar_spread", "20260718", [200], "C", "long", expiry2="20260815")
    assert len(legs) == 2


def test_build_preset_calendar_spread_requires_expiry2():
    with pytest.raises(ValueError):
        build_preset("calendar_spread", "20260718", [200], "C", "long")
