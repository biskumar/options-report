"""Pure leg-construction for common multi-leg strategies -- no IB calls, so
these are fully unit-testable without a TWS connection. This is the single
source of truth for which leg gets BUY vs SELL for each preset; the
Strategy Builder UI calls these (via the /api/orders/combo/preset endpoint)
rather than re-deriving the same logic in JavaScript.

IMPORTANT: BUY/SELL conventions here are internally consistent (each leg's
direction relative to the strategy is unambiguous), but the *overall combo
order's* net debit/credit sign convention (see order_builder.build_combo_order)
is the most bug-prone part of this whole app. Never submit a live combo
order without first hand-checking the computed net price against the
chain's live bid/ask, per the plan's verification checklist."""

from ..models.contracts import ComboLegSpec


def vertical_spread(expiry: str, long_strike: float, short_strike: float, right: str) -> list[ComboLegSpec]:
    """Buy long_strike, sell short_strike, same expiry/right. Whether this
    nets a debit or credit depends on which strike is more expensive --
    the caller decides that by choice of long_strike/short_strike, this
    function makes no debit/credit assumption."""
    return [
        ComboLegSpec(expiry=expiry, strike=long_strike, right=right, action="BUY"),
        ComboLegSpec(expiry=expiry, strike=short_strike, right=right, action="SELL"),
    ]


def straddle(expiry: str, strike: float, side: str = "long") -> list[ComboLegSpec]:
    action = "BUY" if side == "long" else "SELL"
    return [
        ComboLegSpec(expiry=expiry, strike=strike, right="C", action=action),
        ComboLegSpec(expiry=expiry, strike=strike, right="P", action=action),
    ]


def strangle(expiry: str, call_strike: float, put_strike: float, side: str = "long") -> list[ComboLegSpec]:
    action = "BUY" if side == "long" else "SELL"
    return [
        ComboLegSpec(expiry=expiry, strike=call_strike, right="C", action=action),
        ComboLegSpec(expiry=expiry, strike=put_strike, right="P", action=action),
    ]


def iron_condor(
    expiry: str, put_long: float, put_short: float, call_short: float, call_long: float
) -> list[ComboLegSpec]:
    """Classic SHORT iron condor (net credit by construction): sell the
    inner strikes, buy the outer (protective) strikes."""
    if not (put_long < put_short < call_short < call_long):
        raise ValueError("strikes must satisfy put_long < put_short < call_short < call_long")
    return [
        ComboLegSpec(expiry=expiry, strike=put_long, right="P", action="BUY"),
        ComboLegSpec(expiry=expiry, strike=put_short, right="P", action="SELL"),
        ComboLegSpec(expiry=expiry, strike=call_short, right="C", action="SELL"),
        ComboLegSpec(expiry=expiry, strike=call_long, right="C", action="BUY"),
    ]


def butterfly(
    expiry: str, low_strike: float, mid_strike: float, high_strike: float, right: str, side: str = "long"
) -> list[ComboLegSpec]:
    """Long butterfly (net debit) by default: buy 1x low, sell 2x mid, buy
    1x high, same expiry/right. side="short" inverts every leg for a short
    butterfly (net credit)."""
    if not (low_strike < mid_strike < high_strike):
        raise ValueError("strikes must satisfy low_strike < mid_strike < high_strike")
    outer_action = "BUY" if side == "long" else "SELL"
    inner_action = "SELL" if side == "long" else "BUY"
    return [
        ComboLegSpec(expiry=expiry, strike=low_strike, right=right, action=outer_action),
        ComboLegSpec(expiry=expiry, strike=mid_strike, right=right, action=inner_action, ratio=2),
        ComboLegSpec(expiry=expiry, strike=high_strike, right=right, action=outer_action),
    ]


def calendar_spread(near_expiry: str, far_expiry: str, strike: float, right: str, side: str = "long") -> list[ComboLegSpec]:
    """Long calendar (net debit) by default: sell the near-dated option,
    buy the far-dated option, same strike/right. side="short" inverts
    both legs. far_expiry must be strictly after near_expiry."""
    if far_expiry <= near_expiry:
        raise ValueError("far_expiry must be after near_expiry")
    near_action = "SELL" if side == "long" else "BUY"
    far_action = "BUY" if side == "long" else "SELL"
    return [
        ComboLegSpec(expiry=near_expiry, strike=strike, right=right, action=near_action),
        ComboLegSpec(expiry=far_expiry, strike=strike, right=right, action=far_action),
    ]


PRESETS = {
    "vertical": vertical_spread,
    "straddle": straddle,
    "strangle": strangle,
    "iron_condor": iron_condor,
    "butterfly": butterfly,
    "calendar_spread": calendar_spread,
}


def build_preset(
    name: str,
    expiry: str,
    strikes: list[float],
    right: str | None,
    side: str | None,
    expiry2: str | None = None,
) -> list[ComboLegSpec]:
    if name == "vertical":
        if right is None or len(strikes) != 2:
            raise ValueError("vertical preset requires right and exactly 2 strikes [long, short]")
        return vertical_spread(expiry, strikes[0], strikes[1], right)
    if name == "straddle":
        if len(strikes) != 1:
            raise ValueError("straddle preset requires exactly 1 strike")
        return straddle(expiry, strikes[0], side or "long")
    if name == "strangle":
        if len(strikes) != 2:
            raise ValueError("strangle preset requires exactly 2 strikes [call, put]")
        return strangle(expiry, strikes[0], strikes[1], side or "long")
    if name == "iron_condor":
        if len(strikes) != 4:
            raise ValueError("iron_condor preset requires exactly 4 strikes [put_long, put_short, call_short, call_long]")
        return iron_condor(expiry, *strikes)
    if name == "butterfly":
        if right is None or len(strikes) != 3:
            raise ValueError("butterfly preset requires right and exactly 3 strikes [low, mid, high]")
        return butterfly(expiry, strikes[0], strikes[1], strikes[2], right, side or "long")
    if name == "calendar_spread":
        if right is None or len(strikes) != 1 or not expiry2:
            raise ValueError("calendar_spread preset requires right, exactly 1 strike, and expiry2 (the far-dated expiry)")
        return calendar_spread(expiry, expiry2, strikes[0], right, side or "long")
    raise ValueError(f"unknown preset: {name}")
