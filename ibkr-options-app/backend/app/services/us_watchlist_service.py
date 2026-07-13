"""Reads the repo-root US_watchlist.json (37 US tickers the user tracks for
options trading) and, when connected, enriches it with a live one-shot
quote per symbol. Market data is explicitly cancelled after the snapshot is
collected so this doesn't leave 37 persistent streaming subscriptions
sitting on the account's market-data-line budget."""

import json
import math
from pathlib import Path

from ib_insync import IB

from .contract_builder import build_stock

REPO_ROOT = Path(__file__).resolve().parents[4]
_WATCHLIST_FILE = REPO_ROOT / "US_watchlist.json"


def _clean(value):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _clean_price(value):
    """IB uses -1 as a sentinel for "price not available" on bid/ask/last/
    close (distinct from the NaN _clean() handles) -- ticker.marketPrice()
    can pass this straight through when there's no valid last trade either.
    A real price is never negative, so treat negative values as unavailable
    rather than showing e.g. "$-1.00" or computing a bogus % change from it."""
    value = _clean(value)
    return None if value is not None and value < 0 else value


def load_static_list() -> list[dict]:
    with open(_WATCHLIST_FILE) as f:
        data = json.load(f)
    return data["tickers"]


async def get_us_watchlist(ib: IB) -> list[dict]:
    tickers = load_static_list()

    if not ib.isConnected():
        return [{"symbol": t["symbol"], "name": t["name"], "last": None, "change": None, "changePct": None} for t in tickers]

    contracts = [build_stock(t["symbol"]) for t in tickers]
    qualified = await ib.qualifyContractsAsync(*contracts)
    live_tickers = await ib.reqTickersAsync(*qualified)
    by_symbol = {lt.contract.symbol: lt for lt in live_tickers}

    rows = []
    for t in tickers:
        lt = by_symbol.get(t["symbol"])
        last = _clean_price(lt.marketPrice()) if lt else None
        close = _clean_price(lt.close) if lt else None
        change = round(last - close, 2) if last is not None and close is not None else None
        change_pct = round(change / close * 100, 2) if change is not None and close else None
        rows.append({
            "symbol": t["symbol"],
            "name": t["name"],
            "last": round(last, 2) if last is not None else None,
            "change": change,
            "changePct": change_pct,
        })

    for c in qualified:
        ib.cancelMktData(c)

    return rows
