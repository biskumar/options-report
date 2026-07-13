"""Contract construction helpers. Same Option()/Stock() argument shapes as
options_report.py's get_greeks_ibkr/get_full_chain_ibkr (lines ~1626-1755),
reimplemented here to run against a shared persistent IB connection instead
of a short-lived per-call one."""

from ib_insync import Option, Stock


def build_stock(symbol: str) -> Stock:
    return Stock(symbol, "SMART", "USD")


def build_option(symbol: str, expiry: str, strike: float, right: str) -> Option:
    return Option(symbol, expiry, strike, right, "SMART", currency="USD")
