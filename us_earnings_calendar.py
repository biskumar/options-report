"""
Extract the upcoming earnings-results calendar for every ticker in US_watchlist.json.

Usage:
    python3 us_earnings_calendar.py
"""
import json
from datetime import datetime, date

import yfinance as yf

WATCHLIST_FILE = "US_watchlist.json"
OUTPUT_JSON = "us_earnings_calendar.json"


def get_next_earnings_date(ticker: str):
    """Return the next (or most recent) earnings date for a ticker, or None."""
    tk = yf.Ticker(ticker)

    # Try calendar first (gives next confirmed earnings date).
    # yfinance >=1.x returns a plain dict; older versions return a DataFrame.
    try:
        cal = tk.calendar
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if isinstance(raw, (list, tuple)) and raw:
                raw = raw[0]
            if raw:
                d = raw.date() if hasattr(raw, "date") else raw
                if d >= date.today():
                    return d
        elif cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
            d = raw.date() if hasattr(raw, "date") else raw
            if d and d >= date.today():
                return d
    except Exception:
        pass

    # Fallback: earnings_dates (historical + estimate) — pick nearest future date
    try:
        ed_df = tk.earnings_dates
        if ed_df is not None and not ed_df.empty:
            idx = ed_df.index
            if hasattr(idx, "tz_localize"):
                try:
                    idx = idx.tz_localize(None)
                except Exception:
                    idx = idx.tz_convert(None)
            future = [i.date() for i in idx if i.replace(tzinfo=None) > datetime.now()]
            if future:
                return min(future)
    except Exception:
        pass

    return None


def main():
    with open(WATCHLIST_FILE) as f:
        watchlist = json.load(f)

    tickers = watchlist["tickers"]
    today = date.today()
    results = []

    for t in tickers:
        symbol = t["symbol"]
        name = t["name"]
        print(f"Fetching earnings date for {symbol} ({name})...")
        earnings_date = get_next_earnings_date(symbol)
        days_away = (earnings_date - today).days if earnings_date else None
        results.append({
            "symbol": symbol,
            "name": name,
            "earnings_date": earnings_date.isoformat() if earnings_date else None,
            "days_away": days_away,
        })

    # Sort: known dates first (soonest first), unknowns last
    results.sort(key=lambda r: (r["earnings_date"] is None, r["earnings_date"] or ""))

    with open(OUTPUT_JSON, "w") as f:
        json.dump({"generated": today.isoformat(), "earnings": results}, f, indent=2)

    # Print table
    print(f"\n{'Symbol':<8}{'Name':<24}{'Earnings Date':<16}{'Days Away':<10}")
    print("-" * 58)
    for r in results:
        ed = r["earnings_date"] or "Unknown"
        da = str(r["days_away"]) if r["days_away"] is not None else "-"
        print(f"{r['symbol']:<8}{r['name']:<24}{ed:<16}{da:<10}")

    print(f"\nSaved to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
