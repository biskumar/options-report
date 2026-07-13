"""
Ticker Options Analyzer — Unusual Whales pre-market/flow/signal-quality checklist.

Single-ticker deep dive:
    python3 ticker_option_analyzer.py AAPL
    python3 ticker_option_analyzer.py TSLA --min-premium 100000 --dte-max 3

Watchlist scan (lighter subset, US_watchlist.json):
    python3 ticker_option_analyzer.py --watchlist --top 15

Post-trade review (reads back today's logged pre-market levels):
    python3 ticker_option_analyzer.py --review
    python3 ticker_option_analyzer.py --review --date 2026-07-10

Trading style baked into the scoring/output: single-leg call/put buys only —
multi-leg (spread) flow is shown as a reference level (short strike = likely
resistance/support), never surfaced as a trade idea. No PCR/IV directional
rule labels — IV rank is only ever one input to the 0-6 confluence score.
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import date, datetime
from pathlib import Path

import yfinance as yf
from colorama import Fore, Style, init
from tabulate import tabulate

from unusualwhales import UWClient, UWError

warnings.filterwarnings("ignore")
init(autoreset=True)

WATCHLIST_FILE = Path(__file__).parent / "US_watchlist.json"
LOG_DIR = Path(__file__).parent / "option_analyzer_logs"

DEFAULT_MIN_PREMIUM = 250_000
DEFAULT_DTE_MIN = 0
DEFAULT_DTE_MAX = 5
NEAR_LEVEL_PCT = 0.01  # dark pool print within 1% of a GEX level counts as "near"

# SEC Form 4 transaction codes, see https://www.sec.gov/about/forms/form4data.pdf
_INSIDER_CODES = {
    "P": "BUY", "S": "SELL", "A": "GRANT/AWARD", "M": "OPTION EXERCISE",
    "F": "TAX WITHHOLDING", "G": "GIFT", "C": "CONVERSION", "D": "DISPOSITION TO ISSUER",
}


# ============================================================
# HELPERS
# ============================================================
def _fmt_money(v):
    if v is None:
        return "?"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    return f"${v/1_000:.0f}K"


def _fmt_px(v):
    return f"${v:,.2f}" if v is not None else "?"


def _load_watchlist() -> list[str]:
    data = json.loads(WATCHLIST_FILE.read_text())
    return [t["symbol"] for t in data.get("tickers", [])]


def _gex_levels(gex: dict) -> dict:
    """Normalize the two possible get_gex() response shapes into one flat dict of named levels."""
    levels = {}
    for key in ("call_wall", "put_wall", "gamma_flip", "gamma_magnet", "top_pin_strike", "gex_flip_strike"):
        v = gex.get(key)
        if v:
            levels[key] = float(v)
    return levels


def _near_any_level(price: float, levels: dict, pct: float = NEAR_LEVEL_PCT):
    for name, lvl in levels.items():
        if lvl and abs(price - lvl) / lvl <= pct:
            return name, lvl
    return None, None


def _spot_price(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="1m")
        return float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        return None


def _top_near_money(strikes: list[dict], spot: float | None, field: str, band: float = 0.25) -> dict:
    """
    Largest-|field| strike, restricted to a +/-band around spot when spot is
    known. Deep ITM strikes can carry huge legacy/synthetic-long OI that
    dominates a naive max(abs(net_delta)) pick without reflecting live
    dealer-hedging pressure near the current price.
    """
    candidates = strikes
    if spot:
        near = [s for s in strikes if abs(s["strike"] - spot) / spot <= band]
        if near:
            candidates = near
    return max(candidates, key=lambda x: abs(x[field])) if candidates else {}


# ============================================================
# SINGLE-TICKER REPORT
# ============================================================
def analyze_ticker(client: UWClient, ticker: str, expiry: str | None, min_premium: int,
                    dte_min: int, dte_max: int) -> dict:
    ticker = ticker.upper()
    report: dict = {"ticker": ticker, "timestamp": datetime.now().isoformat()}

    # ---- Pre-market levels ----
    try:
        gex = client.get_gex(ticker, expiry)
    except UWError as e:
        gex = {"error": str(e)}
    try:
        greeks = client.get_greek_exposure_strike(ticker)
    except UWError as e:
        greeks = {"error": str(e)}
    try:
        darkpool = client.get_darkpool_prints(ticker, min_premium=200_000)
    except UWError as e:
        darkpool = {"error": str(e)}
    try:
        congress = client.get_congress_trades(ticker)
    except UWError as e:
        congress = []
    try:
        insider = client.get_insider_trades(ticker)
    except UWError as e:
        insider = []
    try:
        iv_rank = client.get_iv_rank(ticker)
    except UWError as e:
        iv_rank = {"error": str(e)}
    try:
        flow = client.get_flow(ticker, expiry)
    except UWError as e:
        flow = {"error": str(e)}

    spot = _spot_price(ticker)
    levels = _gex_levels(gex) if not gex.get("error") else {}
    top_dex = top_vanna = {}
    if not greeks.get("error"):
        top_dex = _top_near_money(greeks["strikes"], spot, "net_delta")
        top_vanna = _top_near_money(greeks["strikes"], spot, "net_vanna")
        if top_dex.get("strike"):
            levels["top_dex_strike"] = top_dex["strike"]
        if top_vanna.get("strike"):
            levels["top_vanna_strike"] = top_vanna["strike"]

    dp_flags = []
    if not darkpool.get("error"):
        for p in darkpool.get("prints", [])[:15]:
            name, lvl = _near_any_level(p["price"], levels)
            if name:
                dp_flags.append({**p, "near_level": name, "level_price": lvl})

    # ---- Flow tab (filtered) ----
    try:
        alerts = client.get_flow_alerts(ticker, min_premium=min_premium, limit=50)
    except UWError as e:
        alerts = []
    qualifying = [
        a for a in alerts
        if (a["sweep"] or a["block"])
        and a["dte"] is not None and dte_min <= a["dte"] <= dte_max
    ]
    single_leg = [a for a in qualifying if not a["spread"]]
    spreads = [a for a in qualifying if a["spread"]]

    call_alerts = [a for a in qualifying if a["type"] == "CALL"]
    put_alerts = [a for a in qualifying if a["type"] == "PUT"]
    call_premium = sum(a["premium"] for a in call_alerts)
    put_premium = sum(a["premium"] for a in put_alerts)
    call_sweeps = sum(1 for a in call_alerts if a["sweep"])
    put_sweeps = sum(1 for a in put_alerts if a["sweep"])

    flow_dir = "bull" if call_premium > put_premium else "bear" if put_premium > call_premium else "neutral"

    # ---- Signal quality score (0-6) ----
    score = 0
    checks = {}

    checks["repeated_sweeps"] = call_sweeps >= 2 or put_sweeps >= 2
    if checks["repeated_sweeps"]:
        score += 1

    call_wall, put_wall = levels.get("call_wall"), levels.get("put_wall")
    underlying = spot or (qualifying[0].get("underlying_price") if qualifying else None)
    if underlying and call_wall and put_wall:
        # confluence check: bullish flow should not be piling into calls above the call wall (resistance),
        # bearish flow should not be piling into puts below the put wall (support)
        if flow_dir == "bull":
            checks["gex_confluence"] = underlying < call_wall
        elif flow_dir == "bear":
            checks["gex_confluence"] = underlying > put_wall
        else:
            checks["gex_confluence"] = False
    else:
        checks["gex_confluence"] = False
    if checks["gex_confluence"]:
        score += 1

    checks["dark_pool_confluence"] = len(dp_flags) > 0
    if checks["dark_pool_confluence"]:
        score += 1

    iv_rank_val = iv_rank.get("iv_rank", 0) if not iv_rank.get("error") else 0
    checks["iv_rank_over_60"] = iv_rank_val > 60
    if checks["iv_rank_over_60"]:
        score += 1

    checks["dte_2_to_5"] = any(a["dte"] is not None and 2 <= a["dte"] <= 5 for a in qualifying)
    if checks["dte_2_to_5"]:
        score += 1

    checks["single_leg_available"] = len(single_leg) > 0
    if checks["single_leg_available"]:
        score += 1

    # ---- Red flags ----
    red_flags = []
    if len(qualifying) < 2:
        red_flags.append("Isolated / no repeat activity — fewer than 2 qualifying alerts in the window")
    low_conviction = [a for a in qualifying if a["trade_count"] <= 1 and a["premium"] < min_premium * 2]
    if low_conviction:
        red_flags.append(f"{len(low_conviction)} alert(s) are single low-count prints with no follow-through")
    if flow_dir != "neutral" and not checks["gex_confluence"] and not checks["dark_pool_confluence"]:
        red_flags.append(f"{flow_dir.capitalize()} flow contradicts/ignores GEX levels with no dark pool confirmation")
    if underlying and qualifying:
        far_otm = [a for a in qualifying if a.get("strike") and
                   abs(float(a["strike"]) - underlying) / underlying > 0.10]
        if far_otm and iv_rank_val < 40:
            red_flags.append(f"{len(far_otm)} far-OTM strike(s) (>10%) combined with low IV rank ({iv_rank_val:.0f}) — low conviction / possible cheap hedge")

    report.update({
        "gex": gex, "greeks": greeks, "spot": spot, "top_dex": top_dex, "top_vanna": top_vanna,
        "darkpool": darkpool, "dp_flags": dp_flags,
        "congress": congress, "insider": insider, "iv_rank": iv_rank, "flow": flow,
        "levels": levels, "alerts": qualifying, "single_leg": single_leg, "spreads": spreads,
        "call_premium": call_premium, "put_premium": put_premium,
        "call_sweeps": call_sweeps, "put_sweeps": put_sweeps, "flow_dir": flow_dir,
        "score": score, "checks": checks, "red_flags": red_flags,
        "min_premium": min_premium, "dte_min": dte_min, "dte_max": dte_max,
    })
    return report


def print_report(r: dict):
    ticker = r["ticker"]
    print(f"\n{Fore.CYAN}{'='*72}")
    print(f"  {ticker}  —  Options Analyzer  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*72}{Style.RESET_ALL}")

    # --- Pre-market levels ---
    print(f"\n{Fore.YELLOW}── PRE-MARKET LEVELS ──{Style.RESET_ALL}")
    gex = r["gex"]
    if gex.get("error"):
        print(f"  GEX:        ERROR — {gex['error']}")
    else:
        print(f"  GEX regime: {gex.get('regime', '?')}")
        print(f"  Call wall:  {_fmt_px(gex.get('call_wall'))}   Put wall: {_fmt_px(gex.get('put_wall'))}   "
              f"Gamma flip: {_fmt_px(gex.get('gamma_flip'))}   Magnet: {_fmt_px(gex.get('gamma_magnet'))}")

    greeks = r["greeks"]
    if not greeks.get("error"):
        dex, vanna = r.get("top_dex", {}), r.get("top_vanna", {})
        if dex:
            direction = "bullish (dealers likely buy on dips)" if dex["net_delta"] > 0 else "bearish (dealers likely sell rallies)"
            print(f"  Top DEX:    ${dex['strike']:g}  (net delta {dex['net_delta']:+,.0f} — {direction})")
        if vanna:
            print(f"  Top Vanna:  ${vanna['strike']:g}  (net vanna {vanna['net_vanna']:+,.0f} — vol-sensitive hedging)")

    dp = r["darkpool"]
    if dp.get("error"):
        print(f"  Dark pool:  ERROR — {dp['error']}")
    else:
        print(f"  Dark pool:  {len(dp.get('prints', []))} block print(s) ≥$200K on {dp.get('session_date', '?')}")
        if r["dp_flags"]:
            for f in r["dp_flags"][:5]:
                print(f"    {Fore.MAGENTA}⚠ {_fmt_px(f['price'])} x {f['size']:,} ({_fmt_money(f['premium'])}) "
                      f"near {f['near_level']} @ {_fmt_px(f['level_price'])}{Style.RESET_ALL}")
        else:
            print(f"    No prints within {NEAR_LEVEL_PCT*100:.0f}% of a GEX level")

    if r["congress"]:
        print(f"  Congress:   {len(r['congress'])} filing(s) in last 60d")
        for c in r["congress"][:3]:
            print(f"    {c['name']} ({c['member_type']}) — {c['txn_type']} {c['amounts']}, filed {c['filed_at_date']}")
    else:
        print("  Congress:   None filed recently")

    if r["insider"]:
        print(f"  Insider:    {len(r['insider'])} filing(s) in last 90d")
        for i in r["insider"][:3]:
            code = _INSIDER_CODES.get(i["transaction_code"], i["transaction_code"])
            print(f"    {i['owner_name']} ({i['title']}) — {code} {i['amount']} @ {_fmt_px(i['price'])}, filed {i['filing_date']}")
    else:
        print("  Insider:    None filed recently")

    print(f"\n  {Fore.WHITE}{Style.BRIGHT}KEY LEVELS (write these down):{Style.RESET_ALL}")
    for name, lvl in r["levels"].items():
        print(f"    {name:<18} {_fmt_px(lvl)}")

    # --- Flow tab ---
    print(f"\n{Fore.YELLOW}── FLOW TAB (sweep/block, ≥{_fmt_money(r['min_premium'])}, "
          f"DTE {r['dte_min']}-{r['dte_max']}) ──{Style.RESET_ALL}")
    print(f"  Calls: {_fmt_money(r['call_premium'])} premium, {r['call_sweeps']} sweep(s)   |   "
          f"Puts: {_fmt_money(r['put_premium'])} premium, {r['put_sweeps']} sweep(s)   |   "
          f"Net: {Fore.GREEN if r['flow_dir']=='bull' else Fore.RED if r['flow_dir']=='bear' else Fore.WHITE}{r['flow_dir'].upper()}{Style.RESET_ALL}")

    if r["single_leg"]:
        print(f"\n  {'Type':<5} {'Strike':<8} {'Expiry':<12} {'DTE':<4} {'Side':<5} {'Premium':<9} Flags")
        print(f"  {'-'*65}")
        for a in r["single_leg"][:10]:
            flags = ("🔥" if a["sweep"] else "") + ("🧱" if a["block"] else "") + \
                    (" NEW-POS" if a["new_positioning"] else "")
            print(f"  {a['type']:<5} ${str(a['strike']):<7} {str(a['expiry']):<12} {a['dte']:<4} "
                  f"{a['side']:<5} {_fmt_money(a['premium']):<9} {flags}")
    else:
        print("  No qualifying single-leg sweep/block flow in this window.")

    if r["spreads"]:
        print(f"\n  {Fore.BLUE}Spread flow (reference only — short strike = likely target/resistance, not tradeable):{Style.RESET_ALL}")
        for a in r["spreads"][:5]:
            print(f"    {a['type']} ${a['strike']} {a['expiry']} — {_fmt_money(a['premium'])}")

    # --- Signal quality score ---
    print(f"\n{Fore.YELLOW}── SIGNAL QUALITY SCORE: {r['score']}/6 ──{Style.RESET_ALL}")
    labels = {
        "repeated_sweeps": "Repeated sweeps stacking same direction",
        "gex_confluence": "Flow direction aligns with GEX levels",
        "dark_pool_confluence": "Dark pool confirms same zone/direction",
        "iv_rank_over_60": "IV rank > 60",
        "dte_2_to_5": "DTE in 2-5 day range",
        "single_leg_available": "Single-leg (non-spread) flow available",
    }
    for key, label in labels.items():
        mark = f"{Fore.GREEN}✓{Style.RESET_ALL}" if r["checks"][key] else f"{Fore.RED}✗{Style.RESET_ALL}"
        print(f"  {mark} {label}")

    # --- Red flags ---
    if r["red_flags"]:
        print(f"\n{Fore.RED}── RED FLAGS ──{Style.RESET_ALL}")
        for f in r["red_flags"]:
            print(f"  ⚠ {f}")

    print(f"\n{Fore.CYAN}{'='*72}{Style.RESET_ALL}\n")


# ============================================================
# POST-TRADE LOG
# ============================================================
def log_report(r: dict):
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{date.today().isoformat()}.json"
    data = json.loads(log_path.read_text()) if log_path.exists() else {}
    data[r["ticker"]] = {
        "timestamp": r["timestamp"],
        "levels": r["levels"],
        "score": r["score"],
        "flow_dir": r["flow_dir"],
        "red_flags": r["red_flags"],
    }
    log_path.write_text(json.dumps(data, indent=2))


def review(date_str: str | None):
    d = date_str or date.today().isoformat()
    log_path = LOG_DIR / f"{d}.json"
    if not log_path.exists():
        print(f"No log found for {d} ({log_path})")
        return
    data = json.loads(log_path.read_text())
    print(f"\n{Fore.CYAN}── POST-TRADE REVIEW — {d} ──{Style.RESET_ALL}\n")
    rows = []
    for ticker, entry in data.items():
        try:
            hist = yf.Ticker(ticker).history(period="1d", interval="1m")
            current = float(hist["Close"].iloc[-1]) if not hist.empty else None
        except Exception:
            current = None
        levels_str = ", ".join(f"{k}={v:g}" for k, v in entry["levels"].items())
        rows.append([ticker, entry["score"], entry["flow_dir"], _fmt_px(current), levels_str])
    print(tabulate(rows, headers=["Ticker", "Score", "Flow", "Now", "Flagged Levels"], tablefmt="simple"))
    print()


# ============================================================
# WATCHLIST MODE (lighter subset)
# ============================================================
def watchlist_scan(client: UWClient, top_n: int, min_premium: int):
    tickers = _load_watchlist()
    rows = []
    for t in tickers:
        try:
            gex = client.get_gex(t)
        except UWError:
            gex = {"error": True}
        try:
            iv = client.get_iv_rank(t)
        except UWError:
            iv = {"error": True}
        try:
            alerts = client.get_flow_alerts(t, min_premium=min_premium, limit=30)
        except UWError:
            alerts = []

        qualifying = [a for a in alerts if a["sweep"] or a["block"]]
        call_prem = sum(a["premium"] for a in qualifying if a["type"] == "CALL")
        put_prem = sum(a["premium"] for a in qualifying if a["type"] == "PUT")
        flow_dir = "bull" if call_prem > put_prem else "bear" if put_prem > call_prem else "-"

        score = 0
        if len(qualifying) >= 2:
            score += 1
        if not iv.get("error") and iv.get("iv_rank", 0) > 60:
            score += 1
        if any(not a["spread"] for a in qualifying):
            score += 1
        if flow_dir != "-":
            score += 1

        rows.append([
            t, score, flow_dir, _fmt_money(call_prem), _fmt_money(put_prem),
            f"{iv.get('iv_rank', 0):.0f}" if not iv.get("error") else "?",
            gex.get("regime", "?")[:30] if not gex.get("error") else "?",
        ])

    rows.sort(key=lambda x: x[1], reverse=True)
    print(f"\n{Fore.CYAN}── WATCHLIST SCAN (top {top_n} by score) ──{Style.RESET_ALL}\n")
    print(tabulate(rows[:top_n], headers=["Ticker", "Score", "Flow", "Call$", "Put$", "IVRank", "GEX Regime"],
                    tablefmt="simple"))
    print()


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Ticker Options Analyzer (Unusual Whales)")
    parser.add_argument("ticker", nargs="?", help="Stock ticker (e.g. AAPL)")
    parser.add_argument("--expiry", help="Expiry date YYYY-MM-DD")
    parser.add_argument("--min-premium", type=int, default=DEFAULT_MIN_PREMIUM)
    parser.add_argument("--dte-min", type=int, default=DEFAULT_DTE_MIN)
    parser.add_argument("--dte-max", type=int, default=DEFAULT_DTE_MAX)
    parser.add_argument("--watchlist", action="store_true", help="Scan US_watchlist.json instead of a single ticker")
    parser.add_argument("--top", type=int, default=15, help="Top N tickers in watchlist mode")
    parser.add_argument("--review", action="store_true", help="Show post-trade review for a logged date")
    parser.add_argument("--date", help="Date YYYY-MM-DD for --review (default: today)")
    parser.add_argument("--no-log", action="store_true", help="Don't write to the post-trade log")
    args = parser.parse_args()

    if args.review:
        review(args.date)
        return

    try:
        client = UWClient()
    except UWError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)

    if args.watchlist:
        watchlist_scan(client, args.top, args.min_premium)
        return

    if not args.ticker:
        parser.error("ticker is required unless --watchlist or --review is given")

    report = analyze_ticker(client, args.ticker, args.expiry, args.min_premium, args.dte_min, args.dte_max)
    print_report(report)
    if not args.no_log:
        log_report(report)


if __name__ == "__main__":
    main()
