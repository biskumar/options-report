"""Bridges to the repo-root analysis scripts (outside this app's own
package). Both underlying calls are slow/blocking (network fetch to
yfinance, or a multi-minute multi-symbol scan) so everything here must run
via run_in_executor, never awaited directly on the event loop.

Note on stock_analyzer.fetch_technicals(): that function is hardcoded to
NSE symbols (appends ".NS"), which doesn't fit this app's US-symbol options
chain/order flow. get_price_history() below reimplements the same
indicator formulas (EMA21/50/200, RSI14, Bollinger 20/2, ATR14) for a plain
US ticker via yfinance directly, and returns the full time series (needed
for charting) rather than stock_analyzer's latest-value-only snapshot."""

import asyncio
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[4]

_watchlist_cache: dict = {"results": None, "fetchedAt": 0}
_WATCHLIST_TTL_SECONDS = 15 * 60
_watchlist_lock = asyncio.Lock()

_history_cache: dict[tuple, tuple[float, dict]] = {}
_HISTORY_TTL_SECONDS = 60


def _compute_price_history(symbol: str, period: str, interval: str) -> dict:
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"no price history for {symbol}")

    c, h, l = df["Close"], df["High"], df["Low"]

    ema21 = c.ewm(span=21, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi = 100 - (100 / (1 + gain / loss))

    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_up = bb_mid + 2 * bb_std
    bb_dn = bb_mid - 2 * bb_std

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    def series(s):
        return [round(float(v), 4) if pd.notna(v) else None for v in s]

    bars = [
        {
            "time": ts.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        }
        for ts, row in df.iterrows()
    ]

    return {
        "symbol": symbol,
        "bars": bars,
        "ema21": series(ema21),
        "ema50": series(ema50),
        "ema200": series(ema200),
        "rsi": series(rsi),
        "bbUpper": series(bb_up),
        "bbLower": series(bb_dn),
        "atr": series(atr),
    }


async def get_price_history(symbol: str, period: str = "6mo", interval: str = "1d") -> dict:
    key = (symbol, period, interval)
    now = time.time()
    cached = _history_cache.get(key)
    if cached and (now - cached[0]) < _HISTORY_TTL_SECONDS:
        return cached[1]

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _compute_price_history, symbol, period, interval)
    _history_cache[key] = (now, result)
    return result


def _run_morning_scan_blocking() -> list[dict]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import india_morning_scan

    return india_morning_scan.run_morning_scan()


async def get_watchlist(force_refresh: bool = False) -> dict:
    """india_morning_scan.run_morning_scan() is a slow, multi-minute batch
    job over ~60 NSE symbols with its own time.sleep() calls -- never call
    it synchronously per-request. Cache the result with a TTL; the
    frontend just reads the cache and can request a forced refresh.

    The lock below is essential, not just tidy: without it, several
    requests arriving while the cache is cold/stale (e.g. two browser tabs
    both loading the Watchlist page) would each kick off their own
    multi-minute scan concurrently. Each scan is CPU-heavy (pandas over
    ~60 symbols), and running several at once starves the single asyncio
    event loop of GIL time badly enough to make the whole app -- including
    completely unrelated endpoints -- unresponsive for minutes."""
    now = time.time()
    is_stale = _watchlist_cache["results"] is None or (now - _watchlist_cache["fetchedAt"]) > _WATCHLIST_TTL_SECONDS
    if force_refresh or is_stale:
        async with _watchlist_lock:
            # Re-check after acquiring the lock: another request may have
            # already refreshed the cache while we were waiting our turn.
            now = time.time()
            still_stale = (
                _watchlist_cache["results"] is None
                or (now - _watchlist_cache["fetchedAt"]) > _WATCHLIST_TTL_SECONDS
            )
            if force_refresh or still_stale:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(None, _run_morning_scan_blocking)
                _watchlist_cache["results"] = results
                _watchlist_cache["fetchedAt"] = time.time()

    return {
        "results": _watchlist_cache["results"],
        "fetchedAt": _watchlist_cache["fetchedAt"],
    }
