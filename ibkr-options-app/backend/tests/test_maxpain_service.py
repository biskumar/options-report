from app.services.maxpain_service import calc_pain_table, classify_direction


def test_calc_pain_table_single_strike_no_oi_is_zero():
    table = calc_pain_table([100.0], {}, {})
    assert table == [{"strike": 100.0, "pain": 0.0}]


def test_calc_pain_table_identifies_lowest_pain_strike():
    # One call written at 100 (OI=10) and one put written at 100 (OI=10):
    # writers lose the least if it expires exactly at 100 (both worthless).
    strikes = [90.0, 100.0, 110.0]
    call_oi = {100.0: 10}
    put_oi = {100.0: 10}
    table = calc_pain_table(strikes, call_oi, put_oi)
    by_strike = {row["strike"]: row["pain"] for row in table}
    assert by_strike[100.0] == 0.0
    # at 90: put ITM by 10 * OI 10 = 100 pain; call OTM = 0
    assert by_strike[90.0] == 100.0
    # at 110: call ITM by 10 * OI 10 = 100 pain; put OTM = 0
    assert by_strike[110.0] == 100.0
    min_pain = min(table, key=lambda x: x["pain"])
    assert min_pain["strike"] == 100.0


def test_calc_pain_table_weights_by_open_interest():
    # Heavy call OI at 100 should pull max pain down toward/below 100
    # relative to lighter put OI at 110.
    strikes = [95.0, 100.0, 105.0, 110.0]
    call_oi = {100.0: 1000}
    put_oi = {110.0: 10}
    table = calc_pain_table(strikes, call_oi, put_oi)
    min_pain = min(table, key=lambda x: x["pain"])
    assert min_pain["strike"] == 100.0


def test_classify_direction_pinned_within_threshold():
    result = classify_direction(spot=100.0, max_pain=100.3)
    assert result["direction"] == "PINNED"
    assert result["distancePct"] == 0.3


def test_classify_direction_pull_up_when_max_pain_above_spot():
    result = classify_direction(spot=100.0, max_pain=110.0)
    assert result["direction"] == "PULL_UP"
    assert result["distancePct"] == 10.0
    assert "below max pain" in result["signal"]


def test_classify_direction_pull_down_when_max_pain_below_spot():
    result = classify_direction(spot=100.0, max_pain=90.0)
    assert result["direction"] == "PULL_DOWN"
    assert result["distancePct"] == -10.0
    assert "above max pain" in result["signal"]


def test_classify_direction_pinned_threshold_scales_with_spot():
    # For a $1000 underlying, 0.5% is $5 -- $3 away should still be PINNED.
    result = classify_direction(spot=1000.0, max_pain=1003.0)
    assert result["direction"] == "PINNED"
