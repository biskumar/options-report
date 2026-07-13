"""Max pain: the strike where option writers (market makers) lose the
least money at expiry. Price tends to gravitate toward this level as
expiry approaches, since MMs who wrote most of the open contracts have an
incentive to pin it there.

Ported from the standalone max_pain.py script's core pain formula, but
sourced entirely from live IBKR data via ib_insync instead of that
script's yfinance/optioncharts.io scraping -- this app has exactly one
data source (TWS) everywhere else, and per-contract open interest turns
out to be available from IBKR without a live quote entitlement (see
_fetch_open_interest), so there's no need for an external source here."""

import asyncio

from ib_insync import IB, Option

from .chain_service import _clean, _get_spot, select_strike_window
from .contract_builder import build_stock


def calc_pain_table(strikes: list[float], call_oi: dict[float, int], put_oi: dict[float, int]) -> list[dict]:
    """Pure, IB-free: total $ pain to option writers if the underlying
    expires at each candidate strike, given open interest per strike.
    Calls lose value to writers as spot rises past the strike; puts lose
    value to writers as spot falls below it -- so at hypothetical expiry
    strike K, writers are on the hook for (K - call_strike) per ITM call
    contract and (put_strike - K) per ITM put contract, times that
    contract's open interest. The strike with the lowest total is where
    writers collectively lose the least."""
    table = []
    for k in strikes:
        call_pain = sum(max(0.0, k - s) * oi for s, oi in call_oi.items())
        put_pain = sum(max(0.0, s - k) * oi for s, oi in put_oi.items())
        table.append({"strike": k, "pain": call_pain + put_pain})
    return table


def classify_direction(spot: float, max_pain: float) -> dict:
    """Pure: compare spot to max pain and describe the expected pull.
    PINNED threshold is whichever is larger of $0.50 or 0.5% of spot, so
    it scales sensibly across both low- and high-priced underlyings."""
    diff = max_pain - spot
    distance_pct = round(diff / spot * 100, 2) if spot else None
    threshold = max(spot * 0.005, 0.5)
    if abs(diff) < threshold:
        direction = "PINNED"
        signal = f"Price within ${abs(diff):.2f} of max pain ${max_pain:.2f} -- expect sideways chop into expiry"
    elif diff > 0:
        direction = "PULL_UP"
        signal = f"Price ${abs(diff):.2f} ({abs(distance_pct):.1f}%) below max pain ${max_pain:.2f} -- upward gravity into expiry"
    else:
        direction = "PULL_DOWN"
        signal = f"Price ${abs(diff):.2f} ({abs(distance_pct):.1f}%) above max pain ${max_pain:.2f} -- downward gravity into expiry"
    return {"direction": direction, "distancePct": distance_pct, "signal": signal}


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _fetch_open_interest(ib: IB, contracts: list) -> dict:
    """Open interest (generic tick 101) is delivered per-contract without
    requiring a live/delayed quote entitlement -- unlike bid/ask/greeks,
    which this account frequently lacks for many symbols. Requested in
    batches so a wide strike ladder (2 contracts per strike) doesn't
    exceed the account's concurrent market-data-line limit."""
    call_oi: dict[float, int] = {}
    put_oi: dict[float, int] = {}
    for batch in _chunk(contracts, 50):
        tickers = [ib.reqMktData(c, genericTickList="101", snapshot=False) for c in batch]
        await asyncio.sleep(2)
        for t in tickers:
            strike = t.contract.strike
            if t.contract.right == "C":
                oi = _clean(t.callOpenInterest)
                call_oi[strike] = int(oi) if oi else 0
            else:
                oi = _clean(t.putOpenInterest)
                put_oi[strike] = int(oi) if oi else 0
        for c in batch:
            ib.cancelMktData(c)
    return call_oi, put_oi


async def calc_max_pain(ib: IB, symbol: str, expiry: str, strike_window: int = 20) -> dict:
    stock = build_stock(symbol)
    qualified = await ib.qualifyContractsAsync(stock)
    if not qualified:
        raise ValueError(f"could not qualify stock contract for {symbol}")
    con_id = qualified[0].conId

    params = await ib.reqSecDefOptParamsAsync(symbol, "", "STK", con_id)
    matching = [p for p in params if expiry in p.expirations]
    if not matching:
        raise ValueError(f"no strikes found for {symbol} expiry {expiry}")
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
    call_oi, put_oi = await _fetch_open_interest(ib, contracts)

    pain_table = calc_pain_table(selected_strikes, call_oi, put_oi)
    min_pain = min(pain_table, key=lambda x: x["pain"]) if pain_table else None
    max_pain = min_pain["strike"] if min_pain else None

    total_call_oi = sum(call_oi.values())
    total_put_oi = sum(put_oi.values())
    pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

    call_walls = sorted(
        ({"strike": s, "openInterest": oi} for s, oi in call_oi.items() if oi > 0),
        key=lambda x: -x["openInterest"],
    )[:3]
    put_walls = sorted(
        ({"strike": s, "openInterest": oi} for s, oi in put_oi.items() if oi > 0),
        key=lambda x: -x["openInterest"],
    )[:3]

    result = {
        "symbol": symbol,
        "expiry": expiry,
        "spot": round(spot, 2),
        "maxPain": max_pain,
        "totalCallOI": total_call_oi,
        "totalPutOI": total_put_oi,
        "pcr": pcr,
        "callWalls": call_walls,
        "putWalls": put_walls,
        "painTable": pain_table,
    }
    if max_pain is not None:
        result.update(classify_direction(spot, max_pain))
    return result
