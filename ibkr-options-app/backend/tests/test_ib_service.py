import math

from app.ib_service import _clean, _clean_price


def test_clean_handles_none_and_nan():
    assert _clean(None) is None
    assert _clean(float("nan")) is None


def test_clean_preserves_negative_values():
    # Greeks like delta/theta are routinely negative -- must not be
    # treated as "no data" the way a negative price would be.
    assert _clean(-0.35) == -0.35


def test_clean_price_handles_none_and_nan():
    assert _clean_price(None) is None
    assert _clean_price(float("nan")) is None


def test_clean_price_rejects_negative_sentinel():
    assert _clean_price(-1.0) is None


def test_clean_price_accepts_zero_and_positive():
    assert _clean_price(0.0) == 0.0
    assert _clean_price(1.43) == 1.43


def test_ticker_payload_with_nan_does_not_produce_nan():
    # Reproduces the bug this fixes: a subscribed contract with no live
    # data ticks NaN bid/ask/greeks into _on_tickers. Unfiltered, that NaN
    # would crash json.dumps for the WebSocket broadcast -- every
    # connected client, not just one HTTP response.
    payload = {
        "bid": _clean_price(float("nan")),
        "ask": _clean_price(float("nan")),
        "last": _clean_price(-1.0),
        "greeks": {
            "delta": _clean(float("nan")),
            "theta": _clean(-0.02),
        },
    }
    assert payload["bid"] is None
    assert payload["ask"] is None
    assert payload["last"] is None
    assert payload["greeks"]["delta"] is None
    assert payload["greeks"]["theta"] == -0.02
    for v in [payload["bid"], payload["ask"], payload["last"], payload["greeks"]["delta"], payload["greeks"]["theta"]]:
        assert not (isinstance(v, float) and math.isnan(v))
