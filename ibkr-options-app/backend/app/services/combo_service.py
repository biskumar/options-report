"""IB-interactive combo (multi-leg) helpers: qualifying each leg's contract
against IBKR, fetching live per-leg quotes, and building the Bag contract
submitted as a single combo order. Pure leg-direction logic (which preset
puts BUY vs SELL on which leg) lives in strategy_presets.py instead."""

import math

from ib_insync import IB, Bag, ComboLeg

from ..models.contracts import ComboLegSpec
from .contract_builder import build_option


def _clean_price(value):
    """ib_insync ticker fields use NaN for "no data yet" and -1 as IB's
    sentinel for "price not available" (e.g. this account lacking a live
    data entitlement for the symbol) -- both are distinct from a real
    quote. Left unfiltered, NaN blows up JSON serialization entirely
    (json.dumps raises ValueError: Out of range float values are not JSON
    compliant), which is why "Preview combo order" silently failed instead
    of showing an error. A real price is never negative either."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return None if value < 0 else value


async def qualify_legs(ib: IB, symbol: str, legs: list[ComboLegSpec]) -> list[dict]:
    contracts = [build_option(symbol, leg.expiry, leg.strike, leg.right) for leg in legs]
    qualified = await ib.qualifyContractsAsync(*contracts)
    if len(qualified) != len(contracts):
        raise ValueError("could not qualify all legs with IBKR -- check strikes/expiry/right")

    tickers = await ib.reqTickersAsync(*qualified)
    ticker_by_conid = {t.contract.conId: t for t in tickers}

    resolved = []
    for leg, contract in zip(legs, qualified):
        ticker = ticker_by_conid.get(contract.conId)
        bid = _clean_price(ticker.bid) if ticker else None
        ask = _clean_price(ticker.ask) if ticker else None
        mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
        resolved.append({"leg": leg, "contract": contract, "bid": bid, "ask": ask, "mid": mid})
    return resolved


def compute_net_mid(resolved_legs: list[dict]) -> float | None:
    """Net mid price using the same signed convention as the combo order's
    lmtPrice: BUY legs add cost, SELL legs subtract it. Positive = net
    debit, negative = net credit."""
    total = 0.0
    for r in resolved_legs:
        if r["mid"] is None:
            return None
        sign = 1 if r["leg"].action == "BUY" else -1
        total += sign * r["mid"] * r["leg"].ratio
    return round(total, 4)


def build_combo_contract(symbol: str, resolved_legs: list[dict]) -> Bag:
    combo_legs = [
        ComboLeg(conId=r["contract"].conId, ratio=r["leg"].ratio, action=r["leg"].action, exchange="SMART")
        for r in resolved_legs
    ]
    return Bag(symbol=symbol, exchange="SMART", currency="USD", comboLegs=combo_legs)
