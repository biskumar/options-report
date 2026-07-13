"""Option chain + Greeks fetch, adapted from options_report.py's
get_full_chain_ibkr/get_greeks_ibkr (lines ~1626-1755) to run against the
app's shared persistent IB connection via *Async calls, instead of opening
a fresh connection per call like the original script does."""

import asyncio
import math

from ib_insync import IB, Option, Stock, Ticker

from .contract_builder import build_option, build_stock


def _clean(value):
    """ib_insync tickers use float('nan') for "no data yet", not None. NaN
    is truthy in Python, so unguarded `if value` / int(value) calls on a
    NaN field raise ValueError("cannot convert float NaN to integer") or
    silently produce a NaN that breaks downstream comparisons and JSON
    output. Route every numeric ticker field through this first."""
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _clean_price(value):
    """Price fields (bid/ask/last/close) specifically use IB's -1 sentinel
    for "not available" (distinct from the NaN default _clean() handles) --
    this shows up whenever the account lacks a live/delayed data
    entitlement for the symbol. A real bid/ask/last is never negative, so
    treat any negative value the same as "no data" rather than displaying
    it or averaging it into a nonsensical negative mid price."""
    value = _clean(value)
    return None if value is not None and value < 0 else value


def _build_row(ticker: Ticker) -> dict:
    mg = ticker.modelGreeks
    bid, ask = _clean_price(ticker.bid), _clean_price(ticker.ask)
    mid = round((bid + ask) / 2, 2) if bid is not None and ask is not None else None
    volume = _clean(ticker.volume)
    delta = _clean(mg.delta) if mg else None
    gamma = _clean(mg.gamma) if mg else None
    theta = _clean(mg.theta) if mg else None
    vega = _clean(mg.vega) if mg else None
    iv = _clean(mg.impliedVol) if mg else None

    return {
        "strike": ticker.contract.strike,
        "right": ticker.contract.right,
        "bid": round(bid, 2) if bid is not None else None,
        "ask": round(ask, 2) if ask is not None else None,
        "mid": mid,
        "volume": int(volume) if volume else 0,
        "impliedVolatility": round(iv * 100, 1) if iv else None,
        "delta": round(delta, 4) if delta is not None else None,
        "gamma": round(gamma, 4) if gamma is not None else None,
        "theta": round(theta, 4) if theta is not None else None,
        "vega": round(vega, 4) if vega is not None else None,
    }


async def _get_spot(ib: IB, stock: Stock) -> float | None:
    """Live/delayed tick data (last/close via reqTickers) requires a market
    data subscription this account may not have (see the "[10168] market
    data not subscribed" warning surfaced elsewhere in the app). Historical
    daily bars are a separate entitlement that's normally available
    regardless, so fall back to yesterday's close from reqHistoricalData
    rather than failing the whole chain lookup outright."""
    tickers = await ib.reqTickersAsync(stock)
    if tickers:
        spot = _clean_price(tickers[0].last) or _clean_price(tickers[0].close)
        if spot is not None:
            return spot

    bars = await ib.reqHistoricalDataAsync(
        stock, endDateTime="", durationStr="5 D", barSizeSetting="1 day", whatToShow="TRADES", useRTH=True
    )
    if bars:
        return _clean_price(bars[-1].close)
    return None


async def get_expiries(ib: IB, symbol: str) -> dict:
    stock = build_stock(symbol)
    qualified = await ib.qualifyContractsAsync(stock)
    if not qualified:
        raise ValueError(f"could not qualify stock contract for {symbol}")
    con_id = qualified[0].conId
    params = await ib.reqSecDefOptParamsAsync(symbol, "", "STK", con_id)
    if not params:
        raise ValueError(f"no option parameters found for {symbol}")
    expirations = sorted({e for p in params for e in p.expirations})
    strikes = sorted({s for p in params for s in p.strikes})
    return {"symbol": symbol, "expiries": expirations, "strikes": strikes}


def select_strike_window(strikes: list[float], spot: float, window: int) -> list[float]:
    """Strikes centered on the one closest to spot, `window` on each side.
    Pure and IB-free so it's unit-testable without mocking the whole async
    chain-fetch pipeline."""
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo, hi = max(0, atm_idx - window), min(len(strikes), atm_idx + window + 1)
    return strikes[lo:hi]


async def get_full_chain(ib: IB, symbol: str, expiry: str, strike_window: int = 10) -> dict:
    stock = build_stock(symbol)
    qualified = await ib.qualifyContractsAsync(stock)
    if not qualified:
        raise ValueError(f"could not qualify stock contract for {symbol}")
    con_id = qualified[0].conId

    params = await ib.reqSecDefOptParamsAsync(symbol, "", "STK", con_id)
    matching = [p for p in params if expiry in p.expirations]
    if not matching:
        raise ValueError(f"no strikes found for {symbol} expiry {expiry}")
    # Multiple entries can match the same expiry (different tradingClass/
    # exchange combos), each with its own partial strike list -- e.g. one
    # entry might only list strikes far OTM. Union across all of them, the
    # same way get_expiries() already does, instead of trusting matching[0]
    # to have the full ladder.
    strikes = sorted({s for p in matching for s in p.strikes})

    spot = await _get_spot(ib, stock)
    if spot is None:
        raise ValueError(f"could not get a spot price for {symbol}")

    selected_strikes = select_strike_window(strikes, spot, strike_window)

    contracts = [
        Option(symbol, expiry, s, r, "SMART", currency="USD")
        for s in selected_strikes
        for r in ("C", "P")
    ]
    await ib.qualifyContractsAsync(*contracts)
    tickers = await ib.reqTickersAsync(*contracts)

    calls, puts = [], []
    for t in tickers:
        row = _build_row(t)
        (calls if t.contract.right == "C" else puts).append(row)

    for c in contracts:
        ib.cancelMktData(c)

    return {
        "symbol": symbol,
        "expiry": expiry,
        "spot": round(spot, 2),
        "calls": sorted(calls, key=lambda r: r["strike"]),
        "puts": sorted(puts, key=lambda r: r["strike"]),
    }


async def get_greeks(ib: IB, symbol: str, expiry: str, strike: float, right: str, timeout: float = 6.0) -> dict:
    contract = build_option(symbol, expiry, strike, right)
    await ib.qualifyContractsAsync(contract)
    ticker = ib.reqMktData(contract, genericTickList="106", snapshot=False)

    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if ticker.modelGreeks is not None and ticker.modelGreeks.delta is not None:
            break
        await asyncio.sleep(0.5)

    mg = ticker.modelGreeks
    delta = _clean(mg.delta) if mg else None
    gamma = _clean(mg.gamma) if mg else None
    theta = _clean(mg.theta) if mg else None
    vega = _clean(mg.vega) if mg else None
    iv = _clean(mg.impliedVol) if mg else None

    result = {
        "symbol": symbol,
        "expiry": expiry,
        "strike": strike,
        "right": right,
        "bid": _clean_price(ticker.bid),
        "ask": _clean_price(ticker.ask),
        "delta": round(delta, 4) if delta is not None else None,
        "gamma": round(gamma, 4) if gamma is not None else None,
        "theta": round(theta, 4) if theta is not None else None,
        "vega": round(vega, 4) if vega is not None else None,
        "impliedVolatility": round(iv * 100, 1) if iv else None,
    }
    ib.cancelMktData(contract)
    return result
