import asyncio
from unittest.mock import AsyncMock

from app.services.chain_service import _build_row, _clean, _get_spot, select_strike_window


class FakeGreeks:
    def __init__(self, delta=None, gamma=None, theta=None, vega=None, impliedVol=None):
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.impliedVol = impliedVol


class FakeContract:
    def __init__(self, strike, right):
        self.strike = strike
        self.right = right


class FakeTicker:
    def __init__(self, strike=200, right="C", bid=None, ask=None, volume=None, modelGreeks=None, last=None, close=None):
        self.contract = FakeContract(strike, right)
        self.bid = bid
        self.ask = ask
        self.volume = volume
        self.modelGreeks = modelGreeks
        self.last = last
        self.close = close


def test_clean_handles_nan_and_none():
    assert _clean(None) is None
    assert _clean(float("nan")) is None
    assert _clean(5.0) == 5.0
    assert _clean(0.0) == 0.0


def test_build_row_with_nan_volume_does_not_raise():
    # This is the exact failure mode reported: ib_insync sets volume to
    # float('nan') when no trade data has arrived yet -- NaN is truthy in
    # Python, so `int(t.volume) if t.volume else 0` used to raise
    # ValueError: cannot convert float NaN to integer.
    ticker = FakeTicker(bid=1.5, ask=1.7, volume=float("nan"))
    row = _build_row(ticker)
    assert row["volume"] == 0
    assert row["bid"] == 1.5
    assert row["ask"] == 1.7
    assert row["mid"] == 1.6


def test_build_row_with_real_volume():
    ticker = FakeTicker(bid=1.5, ask=1.7, volume=42.0)
    row = _build_row(ticker)
    assert row["volume"] == 42


def test_build_row_with_nan_bid_ask_yields_none_mid():
    ticker = FakeTicker(bid=float("nan"), ask=float("nan"), volume=0)
    row = _build_row(ticker)
    assert row["bid"] is None
    assert row["ask"] is None
    assert row["mid"] is None


def test_build_row_with_missing_greeks():
    ticker = FakeTicker(bid=1.0, ask=1.2, volume=5, modelGreeks=None)
    row = _build_row(ticker)
    assert row["delta"] is None
    assert row["impliedVolatility"] is None


def test_build_row_with_nan_greeks():
    ticker = FakeTicker(
        bid=1.0, ask=1.2, volume=5,
        modelGreeks=FakeGreeks(delta=float("nan"), gamma=0.01, theta=-0.02, vega=0.05, impliedVol=float("nan")),
    )
    row = _build_row(ticker)
    assert row["delta"] is None
    assert row["gamma"] == 0.01
    assert row["impliedVolatility"] is None


def test_build_row_with_real_greeks():
    ticker = FakeTicker(
        bid=1.0, ask=1.2, volume=5,
        modelGreeks=FakeGreeks(delta=0.45, gamma=0.02, theta=-0.03, vega=0.08, impliedVol=0.32),
    )
    row = _build_row(ticker)
    assert row["delta"] == 0.45
    assert row["impliedVolatility"] == 32.0


class FakeBar:
    def __init__(self, close):
        self.close = close


def test_get_spot_uses_live_ticker_when_available():
    ib = AsyncMock()
    ib.reqTickersAsync.return_value = [FakeTicker(last=123.45)]
    spot = asyncio.run(_get_spot(ib, object()))
    assert spot == 123.45
    ib.reqHistoricalDataAsync.assert_not_called()


def test_get_spot_falls_back_to_historical_when_no_subscription():
    # Reproduces the account-lacks-a-market-data-subscription case: both
    # last and close come back as NaN/unset from reqTickers (this is what
    # caused "could not get a spot price" for every US symbol on an
    # account without live/delayed US stock data entitlements).
    ib = AsyncMock()
    ib.reqTickersAsync.return_value = [FakeTicker(last=float("nan"), close=None)]
    ib.reqHistoricalDataAsync.return_value = [FakeBar(close=100.0), FakeBar(close=101.5)]
    spot = asyncio.run(_get_spot(ib, object()))
    assert spot == 101.5


def test_get_spot_returns_none_when_nothing_available():
    ib = AsyncMock()
    ib.reqTickersAsync.return_value = [FakeTicker(last=None, close=None)]
    ib.reqHistoricalDataAsync.return_value = []
    spot = asyncio.run(_get_spot(ib, object()))
    assert spot is None


def test_select_strike_window_centers_on_closest_to_spot():
    strikes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0]
    window = select_strike_window(strikes, spot=141.0, window=2)
    # closest to 141 is 140 (index 4); +/-2 -> indices 2..6
    assert window == [120.0, 130.0, 140.0, 150.0, 160.0]


def test_select_strike_window_clamps_at_low_edge():
    strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
    window = select_strike_window(strikes, spot=100.0, window=2)
    assert window == [100.0, 110.0, 120.0]


def test_select_strike_window_clamps_at_high_edge():
    strikes = [100.0, 110.0, 120.0, 130.0, 140.0]
    window = select_strike_window(strikes, spot=140.0, window=2)
    assert window == [120.0, 130.0, 140.0]


def test_select_strike_window_reproduces_sparse_matching_entry_bug():
    # Reproduces the real bug this fixes: reqSecDefOptParamsAsync can
    # return multiple entries matching the same expiry, each with a
    # partial strike list (e.g. one exchange/tradingClass combo only
    # lists far-OTM strikes). get_full_chain used to trust matching[0]
    # alone, which could be the sparse one -- selecting strikes nowhere
    # near spot even though a full ladder existed in another entry.
    sparse_entry_strikes = {185.0, 190.0, 195.0}
    full_entry_strikes = {135.0, 140.0, 145.0, 150.0, 185.0, 190.0, 195.0}
    unioned = sorted(sparse_entry_strikes | full_entry_strikes)
    window = select_strike_window(unioned, spot=142.71, window=1)
    assert window == [140.0, 145.0, 150.0]
