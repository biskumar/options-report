#!/usr/bin/env python3
"""
Max Pain Calculator — importable module + standalone CLI.

Max pain = the strike price where option writers (MMs) lose the least money
on expiry. Price gravitates toward this level as expiry approaches.

Usage:
  python3 max_pain.py AAPL
  python3 max_pain.py AAPL 2026-07-13
  python3 max_pain.py AAPL AMZN META 2026-07-13
  python3 max_pain.py AAPL --all-expiries
"""

import sys
import os
import json
import re
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Optional

# ── optional deps (graceful fallback) ───────────────────────────────────────
try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

# ── optioncharts.io scraper ──────────────────────────────────────────────────
_OC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "HX-Request": "true",
    "Referer": "https://optioncharts.io/options/AAPL",
}

def _oc_expiry_param(expiry_str: str, ticker: str) -> str:
    """Convert YYYY-MM-DD expiry to optioncharts.io expiration_dates param."""
    # 3x weekly stocks use weekly format (date:w), others use standard
    suffix = "%3Aw" if ticker.upper() in THREE_X_WEEKLY else ""
    return urllib.parse.quote(expiry_str) + suffix

def get_expected_move_oc(ticker: str, expiry_str: str) -> Optional[dict]:
    """
    Fetch expected move (±1σ range) from optioncharts.io.
    Returns dict with low, high, move_dollar, move_pct, or None on failure.
    """
    try:
        param = _oc_expiry_param(expiry_str, ticker)
        url = (f"https://optioncharts.io/async/options_charts/expected_move"
               f"?expiration_dates={param}&option_type=all&strike_range=all&ticker={ticker}")
        req = urllib.request.Request(url, headers=_OC_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # Extract: <b>$312.2 and <b>$317.74 pattern
        bounds = re.findall(r'<b>\$(\d+\.?\d*)', content)
        # First two bold dollar values in expected move section are low and high
        if len(bounds) >= 2:
            low  = float(bounds[0])
            high = float(bounds[1])
            move = round((high - low) / 2, 2)
            mid  = round((high + low) / 2, 2)
            return {
                "low":        low,
                "high":       high,
                "move_dollar": move,
                "midpoint":   mid,
                "source":     "optioncharts.io",
            }
        return None
    except Exception:
        return None


def get_max_pain_oc(ticker: str, expiry_str: str) -> Optional[dict]:
    """
    Fetch max pain from optioncharts.io (free, no auth required).
    Returns dict with max_pain_strike and strike loss list, or None on failure.
    """
    try:
        param = _oc_expiry_param(expiry_str, ticker)
        url = (f"https://optioncharts.io/async/options_charts/max_pain"
               f"?expiration_dates={param}&option_type=all&strike_range=all&ticker={ticker}")
        req = urllib.request.Request(url, headers=_OC_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # Extract embedded chart_data JSON object
        match = re.search(r'chart_data\s*=\s*(\{[^;]+\})', content, re.DOTALL)
        if not match:
            return None
        raw = match.group(1)
        # Truncate at first }; to get valid JSON
        brace_count, end = 0, 0
        for i, ch in enumerate(raw):
            if ch == '{': brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        data = json.loads(raw[:end])
        return {
            "max_pain":   float(data.get("max_pain_strike", 0)),
            "loss_table": data.get("max_pain_strike_loss_list", [])[:5],
            "source":     "optioncharts.io",
        }
    except Exception:
        return None

# ── expiry schedule ──────────────────────────────────────────────────────────
THREE_X_WEEKLY = {"AAPL","AMZN","AVGO","GOOGL","IBIT","META","MSFT","NVDA","TSLA"}

# ── SPY context ───────────────────────────────────────────────────────────────
def get_spy_context() -> dict:
    """
    Fetch live SPY data and return market bias + key levels.
    Bias rules:
      STRONG BULL : SPY > VWAP AND RSI(14,15m) > 60
      BULL        : SPY > VWAP AND RSI 50-60
      NEUTRAL     : SPY within 0.2% of VWAP OR RSI 45-55
      BEAR        : SPY < VWAP AND RSI 40-50
      STRONG BEAR : SPY < VWAP AND RSI < 40
    """
    try:
        spy = yf.Ticker("SPY")
        # 15-min bars for intraday RSI + VWAP proxy
        hist = spy.history(period="5d", interval="15m")
        if hist.empty:
            return {"error": "No SPY data"}

        # Today's bars only
        today = date.today().isoformat()
        today_bars = hist[hist.index.date == date.today()]
        if today_bars.empty:
            today_bars = hist.tail(26)  # fallback: last 26 bars

        close = today_bars["Close"]
        volume = today_bars["Volume"]
        spot = round(float(close.iloc[-1]), 2)

        # VWAP (session)
        typical = (today_bars["High"] + today_bars["Low"] + today_bars["Close"]) / 3
        vwap = round(float((typical * volume).sum() / volume.sum()), 2) if volume.sum() > 0 else spot

        # RSI-14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = round(float(100 - 100 / (1 + rs.iloc[-1])), 1)

        # Day change %
        prev_close = round(float(hist["Close"].iloc[-27] if len(hist) > 27 else close.iloc[0]), 2)
        day_chg_pct = round((spot - prev_close) / prev_close * 100, 2)

        # Bias
        above_vwap = spot > vwap
        if above_vwap and rsi > 60:
            bias = "STRONG BULL"
            bias_icon = "🟢🟢"
            override = "Max pain PULL DOWN signals weakened — broad rally overrides pinning"
        elif above_vwap and rsi >= 50:
            bias = "BULL"
            bias_icon = "🟢"
            override = "PULL DOWN signals risky — confirm with stock-level chart before puts"
        elif not above_vwap and rsi < 40:
            bias = "STRONG BEAR"
            bias_icon = "🔴🔴"
            override = "Max pain PULL UP signals weakened — broad selloff overrides pinning"
        elif not above_vwap and rsi <= 50:
            bias = "BEAR"
            bias_icon = "🔴"
            override = "PULL UP signals risky — confirm with stock-level chart before calls"
        else:
            bias = "NEUTRAL"
            bias_icon = "⚪"
            override = "Max pain signals valid — no strong market override"

        return {
            "spot":        spot,
            "vwap":        vwap,
            "rsi":         rsi,
            "day_chg_pct": day_chg_pct,
            "above_vwap":  above_vwap,
            "bias":        bias,
            "bias_icon":   bias_icon,
            "override":    override,
        }
    except Exception as e:
        return {"error": str(e)}


def adjusted_signal(direction: str, distance_pct: float, spy_ctx: dict) -> str:
    """
    Combine max pain direction + gap size + SPY bias → final trade signal.

    Gap thresholds:
      Large  : abs(distance_pct) >= 8%  → gravity strong enough to fight SPY trend
      Medium : abs(distance_pct) >= 3%  → moderate gravity
      Small  : abs(distance_pct) <  3%  → weak gravity, SPY dominates
    """
    if "error" in spy_ctx or not direction:
        return direction  # fallback to raw direction

    bias = spy_ctx.get("bias", "NEUTRAL")
    pull = "UP" if "UP" in direction else ("DOWN" if "DOWN" in direction else "PINNED")
    gap  = abs(distance_pct or 0)

    # ── PULL UP ──────────────────────────────────────────────────────────────
    if pull == "UP":
        if bias in ("STRONG BULL", "BULL"):
            return "🚀 STRONG CALL — max pain + SPY both bullish"
        elif bias == "NEUTRAL":
            return "🟢 CALL — max pain bullish, SPY neutral"
        elif bias == "BEAR":
            if gap >= 8:
                return "⚠️  CALL — large gap, enter on SPY bounce only"
            return "⚠️  WEAK CALL — max pain bullish but SPY bearish, small size"
        else:  # STRONG BEAR
            if gap >= 8:
                return "⚠️  WEAK CALL — huge gap but SPY strongly bearish, wait for reversal"
            return "🚫 SKIP — max pain bullish but SPY strongly bearish"

    # ── PULL DOWN ────────────────────────────────────────────────────────────
    elif pull == "DOWN":
        if bias in ("STRONG BEAR", "BEAR"):
            return "🚀 STRONG PUT — max pain + SPY both bearish"
        elif bias == "NEUTRAL":
            return "🔴 PUT — max pain bearish, SPY neutral"
        elif bias == "BULL":
            if gap >= 8:
                return "⚠️  PUT — large gap overrides mild bull, enter on SPY weakness"
            return "⚠️  WEAK PUT — max pain bearish but SPY bullish, small size only"
        else:  # STRONG BULL
            if gap >= 15:
                return "🔴 PUT — extreme gap (>15%), gravity overrides bull trend"
            elif gap >= 8:
                return "⚠️  WEAK PUT — large gap but SPY strongly bullish, wait for SPY dip"
            else:
                return "🚫 SKIP — small gap, SPY strongly bullish overrides"

    # ── PINNED ───────────────────────────────────────────────────────────────
    else:
        if bias == "NEUTRAL":
            return "⚪ PINNED — avoid, expect chop"
        elif bias in ("STRONG BULL", "BULL"):
            return "🟢 PINNED→CALL BIAS — SPY bullish may push above pin"
        else:
            return "🔴 PINNED→PUT BIAS — SPY bearish may push below pin"

def expiry_schedule(ticker: str) -> str:
    return "Mon/Wed/Fri" if ticker.upper() in THREE_X_WEEKLY else "Fridays only"

def days_to_expiry(expiry_str: str) -> int:
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        return (exp - date.today()).days
    except Exception:
        return -1

# ── core calculation ─────────────────────────────────────────────────────────
def _calc_pain_at_strike(strike: float, calls, puts) -> float:
    """Total dollar pain to option writers if stock expires at `strike`."""
    call_pain = sum(
        max(0.0, strike - k) * oi
        for k, oi in zip(calls["strike"], calls["openInterest"])
    )
    put_pain = sum(
        max(0.0, k - strike) * oi
        for k, oi in zip(puts["strike"], puts["openInterest"])
    )
    return call_pain + put_pain

def calc_max_pain(ticker: str, expiry_str: Optional[str] = None,
                  uw_client=None) -> dict:
    """
    Calculate max pain for ticker + expiry.

    Returns dict with keys:
      ticker, expiry, dte, spot, max_pain_yf, max_pain_uw,
      max_pain (consensus), direction, distance_pct,
      call_walls, put_walls, total_call_oi, total_put_oi, pcr,
      expiry_schedule, pain_table (all strikes sorted by pain asc)
    """
    ticker = ticker.upper()

    if not HAS_YF:
        return {"ticker": ticker, "error": "yfinance not installed"}

    tk = yf.Ticker(ticker)
    try:
        spot = round(float(tk.fast_info.last_price), 2)
    except Exception:
        spot = None

    try:
        expirations = tk.options
    except Exception:
        return {"ticker": ticker, "spot": spot, "error": "No options data from yfinance"}

    if not expirations:
        return {"ticker": ticker, "spot": spot, "error": "No expirations available"}

    # Pick the right expiry
    if expiry_str:
        # Find the first expiry >= requested date
        expiry = next((e for e in sorted(expirations) if e >= expiry_str), None)
        if not expiry:
            expiry = expirations[-1]
    else:
        expiry = expirations[0]

    try:
        chain = tk.option_chain(expiry)
    except Exception:
        return {"ticker": ticker, "spot": spot, "expiry": expiry,
                "error": f"Could not fetch chain for {expiry}"}

    calls = chain.calls.fillna(0)
    puts  = chain.puts.fillna(0)

    # Filter to strikes with any meaningful OI
    all_strikes = sorted(set(
        calls[calls["openInterest"] > 0]["strike"].tolist() +
        puts[puts["openInterest"] > 0]["strike"].tolist()
    ))
    if not all_strikes:
        # Fallback: use all strikes even with 0 OI
        all_strikes = sorted(set(
            calls["strike"].tolist() + puts["strike"].tolist()
        ))

    # Calculate pain at every strike
    pain_table = []
    for s in all_strikes:
        pain = _calc_pain_at_strike(s, calls, puts)
        pain_table.append({"strike": s, "pain": pain})
    pain_table.sort(key=lambda x: x["pain"])

    max_pain_yf = pain_table[0]["strike"] if pain_table else None

    # Cross-reference: optioncharts.io (free, no auth)
    max_pain_oc = None
    oc_data = get_max_pain_oc(ticker, expiry)
    if oc_data and oc_data.get("max_pain"):
        max_pain_oc = float(oc_data["max_pain"])

    # Legacy UW client support (kept for backward compat)
    max_pain_uw = None
    if uw_client:
        try:
            mp_data = uw_client.get_max_pain(ticker)
            if mp_data and isinstance(mp_data, dict):
                max_pain_uw = mp_data.get("max_pain")
            elif mp_data and isinstance(mp_data, list):
                row = next((r for r in mp_data if str(r.get("expiry","")).startswith(expiry[:7])), mp_data[0] if mp_data else None)
                max_pain_uw = row.get("max_pain") if row else None
        except Exception:
            pass

    # Consensus max pain — average all available sources
    sources_available = [(max_pain_yf, "yf"), (max_pain_oc, "OC"), (max_pain_uw, "UW")]
    valid = [(v, lbl) for v, lbl in sources_available if v is not None]
    if len(valid) > 1:
        max_pain = round(sum(v for v, _ in valid) / len(valid), 2)
        parts = "+".join(f"{lbl}=${v}" for v, lbl in valid)
        source = f"avg({parts})"
    elif valid:
        max_pain, lbl = valid[0]
        source = f"{lbl}=${max_pain}"
    else:
        max_pain = None
        source = "no data"

    # Direction signal
    direction = signal = ""
    distance_pct = None
    if spot and max_pain:
        diff = max_pain - spot
        distance_pct = round(diff / spot * 100, 2)
        if abs(diff) < 1.0:
            direction = "⚪ PINNED"
            signal = f"Price within $1 of max pain ${max_pain} — expect sideways chop"
        elif diff > 0:
            direction = "🟢 PULL UP"
            signal = f"Price ${abs(diff):.2f} ({abs(distance_pct):.1f}%) BELOW max pain ${max_pain} → upward gravity"
        else:
            direction = "🔴 PULL DOWN"
            signal = f"Price ${abs(diff):.2f} ({abs(distance_pct):.1f}%) ABOVE max pain ${max_pain} → downward gravity"

    # Gamma walls (top OI strikes)
    call_walls = (calls[calls["openInterest"] > 0]
                  .nlargest(3, "openInterest")[["strike","openInterest","impliedVolatility"]]
                  .to_dict("records"))
    put_walls  = (puts[puts["openInterest"] > 0]
                  .nlargest(3, "openInterest")[["strike","openInterest","impliedVolatility"]]
                  .to_dict("records"))

    total_call_oi = int(calls["openInterest"].sum())
    total_put_oi  = int(puts["openInterest"].sum())
    pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else None

    dte = days_to_expiry(expiry)

    return {
        "ticker":          ticker,
        "expiry":          expiry,
        "dte":             dte,
        "spot":            spot,
        "max_pain_yf":     max_pain_yf,
        "max_pain_oc":     max_pain_oc,
        "max_pain_uw":     max_pain_uw,
        "max_pain":        max_pain,
        "max_pain_source": source,
        "direction":       direction,
        "signal":          signal,
        "distance_pct":    distance_pct,
        "call_walls":      call_walls,
        "put_walls":       put_walls,
        "total_call_oi":   total_call_oi,
        "total_put_oi":    total_put_oi,
        "pcr":             pcr,
        "expiry_schedule": expiry_schedule(ticker),
        "pain_table":      pain_table[:5],   # top 5 lowest-pain strikes
    }

# ── batch helper ─────────────────────────────────────────────────────────────
def calc_max_pain_batch(tickers: list, expiry_str: Optional[str] = None,
                        uw_client=None) -> dict:
    """Run calc_max_pain for multiple tickers. Fetches SPY once, injects into each result."""
    spy_ctx = get_spy_context()
    results = {}
    for t in tickers:
        r = calc_max_pain(t, expiry_str, uw_client)
        r["spy_ctx"]       = spy_ctx
        r["final_signal"]  = adjusted_signal(
            r.get("direction",""), r.get("distance_pct", 0), spy_ctx
        )
        results[t] = r
    return results

# ── display ──────────────────────────────────────────────────────────────────
def _print_spy_header(spy_ctx: dict):
    """Print SPY context block once at the top of output."""
    if not spy_ctx or "error" in spy_ctx:
        print(f"\n  ⚠️  SPY context unavailable: {spy_ctx.get('error','unknown')}")
        return
    print(f"\n{'━'*60}")
    print(f"  SPY MARKET CONTEXT")
    print(f"{'━'*60}")
    print(f"  SPY Price  : ${spy_ctx['spot']}  ({spy_ctx['day_chg_pct']:+.2f}% today)")
    print(f"  VWAP       : ${spy_ctx['vwap']}  "
          f"({'ABOVE ✅' if spy_ctx['above_vwap'] else 'BELOW 🔴'})")
    print(f"  RSI (15m)  : {spy_ctx['rsi']}")
    print(f"  Bias       : {spy_ctx['bias_icon']} {spy_ctx['bias']}")
    print(f"  Override   : {spy_ctx['override']}")
    print(f"{'━'*60}\n")


def print_result(r: dict, verbose: bool = False, show_spy: bool = False):
    if "error" in r:
        print(f"  ❌  {r.get('ticker','?')}: {r['error']}")
        return

    if show_spy and r.get("spy_ctx"):
        _print_spy_header(r["spy_ctx"])

    dte_str = f"{r['dte']}DTE" if r.get("dte") is not None else ""
    print(f"\n{'═'*60}")
    print(f"  {r['ticker']}  │  Expiry: {r['expiry']} ({dte_str})  │  {r['expiry_schedule']}")
    print(f"{'═'*60}")
    print(f"  Current Price  : ${r.get('spot','?')}")
    print(f"  Max Pain (yf)  : ${r.get('max_pain_yf','?')}")
    if r.get('max_pain_uw'):
        print(f"  Max Pain (UW)  : ${r.get('max_pain_uw','?')}")
    print(f"  Max Pain Cons. : ${r.get('max_pain','?')}  ← {r.get('max_pain_source','')}")
    print(f"  MP Direction   : {r.get('direction','')}  {r.get('signal','')}")
    if r.get("final_signal"):
        print(f"  FINAL SIGNAL   : {r['final_signal']}")
    print(f"  PCR            : {r.get('pcr','?')}  "
          f"(Call OI: {r.get('total_call_oi',0):,}  Put OI: {r.get('total_put_oi',0):,})")

    if r.get("call_walls"):
        walls = "  |  ".join(
            f"${w['strike']} OI:{int(w['openInterest']):,}"
            for w in r["call_walls"]
        )
        print(f"  Call Walls     : {walls}")
    if r.get("put_walls"):
        walls = "  |  ".join(
            f"${w['strike']} OI:{int(w['openInterest']):,}"
            for w in r["put_walls"]
        )
        print(f"  Put  Walls     : {walls}")

    if verbose and r.get("pain_table"):
        print(f"\n  Top 5 lowest-pain strikes (expiry magnets):")
        for i, row in enumerate(r["pain_table"], 1):
            marker = " ◄ MAX PAIN" if row["strike"] == r.get("max_pain_yf") else ""
            print(f"    {i}. ${row['strike']:<8}  pain={row['pain']:,.0f}{marker}")

def print_summary_table(results: dict):
    """One-line per ticker summary table with SPY-adjusted final signal."""
    # Print SPY header once
    first = next(iter(results.values()), {})
    if first.get("spy_ctx"):
        _print_spy_header(first["spy_ctx"])

    print(f"{'Ticker':<7} {'Expiry':<12} {'Price':>8} {'MaxPain':>8} "
          f"{'Dist%':>7} {'PCR':>5} {'DTE':>4}  {'FINAL SIGNAL'}")
    print("─" * 90)
    for t, r in results.items():
        if "error" in r:
            print(f"{t:<7} {'ERROR':>12}")
            continue
        print(
            f"{r['ticker']:<7} {r['expiry']:<12} "
            f"${r.get('spot',0):>7.2f} "
            f"${r.get('max_pain',0):>7.2f} "
            f"{r.get('distance_pct',0):>+6.1f}% "
            f"{r.get('pcr',0):>5.2f} "
            f"{r.get('dte',0):>4}d"
            f"  {r.get('final_signal','')}"
        )

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    verbose     = "--verbose" in args or "-v" in args
    all_expiries = "--all-expiries" in args
    json_out    = "--json" in args
    use_uw      = "--uw" in args
    args = [a for a in args if not a.startswith("--") and a != "-v"]

    # Pull UW client if requested
    uw_client = None
    if use_uw:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from unusualwhales import UWClient
            uw_client = UWClient()
        except Exception as e:
            print(f"⚠️  Could not load UW client: {e}")

    # Parse tickers vs expiry
    expiry_str = None
    if args and len(args[-1]) == 10 and args[-1][4] == '-':
        expiry_str = args[-1]
        tickers = [a.upper() for a in args[:-1]]
    else:
        tickers = [a.upper() for a in args]

    if not tickers:
        print("Provide at least one ticker.")
        sys.exit(1)

    if all_expiries:
        # Show max pain across all available expiries for first ticker
        t = tickers[0]
        tk = yf.Ticker(t)
        print(f"\nMax pain across all expiries for {t}:")
        for exp in tk.options[:6]:
            r = calc_max_pain(t, exp, uw_client)
            print_result(r, verbose=False)
        print()
        return

    results = calc_max_pain_batch(tickers, expiry_str, uw_client)

    if json_out:
        print(json.dumps(results, indent=2, default=str))
        return

    if len(tickers) == 1:
        print_result(list(results.values())[0], verbose=verbose, show_spy=True)
    else:
        # Print SPY header once, then each ticker, then summary table
        first = next(iter(results.values()), {})
        if first.get("spy_ctx"):
            _print_spy_header(first["spy_ctx"])
        for r in results.values():
            print_result(r, verbose=verbose, show_spy=False)
        print_summary_table(results)
    print()

if __name__ == "__main__":
    main()
