#!/usr/bin/env python3
"""
0DTE Options Trading Setup Report Generator
Usage:  python options_report.py MSFT
        python options_report.py CSCO --date 2026-06-09
        python options_report.py NVDA --expiry 2026-06-20 --output ~/Desktop/nvda_report.html
"""

import argparse
import json
import math
import os
import sys
import webbrowser
from datetime import date, datetime, timedelta

# FOMC decision dates 2026 (day of rate announcement)
FOMC_DATES_2026 = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 11, 4),
    date(2026, 12, 16),
]

import numpy as np
import pandas as pd
import yfinance as yf
from typing import Optional, List

# ── Sector ETF mapping ───────────────────────────────────────────────────────
SECTOR_ETF_MAP: dict = {
    'AAPL':'XLK','MSFT':'XLK','NVDA':'XLK','AMD':'XLK','INTC':'XLK','ORCL':'XLK','QCOM':'XLK','CRM':'XLK',
    'GOOGL':'XLC','GOOG':'XLC','META':'XLC','NFLX':'XLC','DIS':'XLC','CMCSA':'XLC','CHTR':'XLC','T':'XLC','VZ':'XLC',
    'AMZN':'XLY','TSLA':'XLY','NKE':'XLY','HD':'XLY','MCD':'XLY','SBUX':'XLY','LOW':'XLY','TGT':'XLY',
    'JPM':'XLF','BAC':'XLF','GS':'XLF','MS':'XLF','WFC':'XLF','C':'XLF','BRK-B':'XLF','AXP':'XLF','V':'XLF','MA':'XLF',
    'XOM':'XLE','CVX':'XLE','COP':'XLE','SLB':'XLE','EOG':'XLE',
    'JNJ':'XLV','UNH':'XLV','PFE':'XLV','MRK':'XLV','ABBV':'XLV','LLY':'XLV','TMO':'XLV','ABT':'XLV',
    'PG':'XLP','KO':'XLP','PEP':'XLP','WMT':'XLP','COST':'XLP','PM':'XLP','MO':'XLP',
    'CAT':'XLI','HON':'XLI','GE':'XLI','BA':'XLI','RTX':'XLI','UNP':'XLI','MMM':'XLI','LMT':'XLI',
    'NEE':'XLU','DUK':'XLU','SO':'XLU','AEP':'XLU','EXC':'XLU',
    'SPG':'XLRE','AMT':'XLRE','PLD':'XLRE','CCI':'XLRE','EQIX':'XLRE',
    'LIN':'XLB','APD':'XLB','NEM':'XLB','FCX':'XLB','DD':'XLB',
}

# ── optional: use pandas_ta if available, else fall back to manual ──────────
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False

# ── optional: IBKR TWS API via ib_insync ────────────────────────────────────
try:
    from ib_insync import IB, Option, Stock, util as ib_util
    HAS_IB = True
except (ImportError, RuntimeError):
    HAS_IB = False


# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA FETCHING
# ─────────────────────────────────────────────────────────────────────────────

import pytz as _pytz_mod

def market_session() -> str:
    """
    Return current US market session:
      'premarket'  — 04:00–09:29 ET
      'open'       — 09:30–15:59 ET
      'afterhours' — 16:00–20:00 ET
      'closed'     — outside all above
    """
    try:
        et = _pytz_mod.timezone("America/New_York")
    except Exception:
        # pytz not installed — fall back to UTC offset −5 approximation
        from datetime import timezone, timedelta as _td
        et = timezone(_td(hours=-5))
    now_et = datetime.now(et)
    t = now_et.time()
    from datetime import time as _time
    if _time(4, 0) <= t < _time(9, 30):
        return "premarket"
    elif _time(9, 30) <= t < _time(16, 0):
        return "open"
    elif _time(16, 0) <= t <= _time(20, 0):
        return "afterhours"
    return "closed"


def fetch_intraday(ticker: str, trading_date: date) -> pd.DataFrame:
    """
    Download 1-min bars for the given trading date.
    - Pre-market  → include pre/post data, filter 04:00–09:29 ET
    - Market open → regular session bars only (period='1d')
    - After-hours → regular session bars (full day)
    - Historical  → standard date-range pull
    """
    today = date.today()
    session = market_session() if trading_date == today else "historical"

    if session == "premarket":
        # Use prepost=True and return only pre-market bars
        end = trading_date + timedelta(days=1)
        df = yf.download(
            tickers=ticker,
            start=trading_date.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1m",
            prepost=True,
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        try:
            import pytz
            et = pytz.timezone("America/New_York")
            df.index = df.index.tz_convert(et) if df.index.tzinfo else df.index.tz_localize("UTC").tz_convert(et)
        except Exception:
            pass
        from datetime import time as _time
        pre = df[df.index.time < _time(9, 30)]
        if not pre.empty:
            print(f"    📊 Pre-market session: {len(pre)} bars | "
                  f"High=${float(pre['High'].max()):.2f} Low=${float(pre['Low'].min()):.2f} "
                  f"Last=${float(pre['Close'].iloc[-1]):.2f}")
            return pre
        # Fall through to regular if pre is empty
        print("    ⚠  No pre-market bars yet — using regular session data")

    if session in ("open", "afterhours") or trading_date == today:
        df = yf.download(
            tickers=ticker,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
        )
    else:
        end = trading_date + timedelta(days=1)
        df = yf.download(
            tickers=ticker,
            start=trading_date.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1m",
            progress=False,
            auto_adjust=True,
        )

    if df.empty:
        raise ValueError(f"No intraday data returned for {ticker} on {trading_date}. "
                         "Market may be closed or ticker invalid.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df


def fetch_prior_close(ticker: str, trading_date: date) -> float:
    """Fetch the prior session's closing price."""
    start = trading_date - timedelta(days=7)
    hist = yf.download(
        tickers=ticker,
        start=start.strftime("%Y-%m-%d"),
        end=trading_date.strftime("%Y-%m-%d"),
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)
    if hist.empty:
        return float("nan")
    return float(hist["Close"].iloc[-1])


def fetch_premarket(ticker: str, trading_date: date):
    """Return (premarket_high, premarket_low) or (nan, nan)."""
    try:
        end = trading_date + timedelta(days=1)
        df = yf.download(
            tickers=ticker,
            start=trading_date.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1m",
            prepost=True,
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        # Pre-market is before 09:30 ET
        pre = df[df.index.time < pd.Timestamp("09:30").time()]
        if pre.empty:
            return float("nan"), float("nan")
        return float(pre["High"].max()), float(pre["Low"].min())
    except Exception:
        return float("nan"), float("nan")


def compute_vwap(df: pd.DataFrame) -> float:
    """Session VWAP from intraday bars (cumulative typical-price × volume)."""
    try:
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()
        return round(float(vwap.iloc[-1]), 2)
    except Exception:
        return float("nan")


def _bs_gamma(S: float, K: float, T: float, sigma: float, r: float = 0.05) -> float:
    """Black-Scholes gamma using manual normal PDF (no scipy dependency)."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        npdf = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
        return npdf / (S * sigma * math.sqrt(T))
    except Exception:
        return 0.0


def get_uw_flow(ticker: str, expiry_str: Optional[str], api_key: str) -> dict:
    """
    Fetch recent options flow from Unusual Whales API.
    Returns aggregated bull/bear premium, sweep count, and net flow signal.

    API docs: https://unusualwhales.com/api-docs
    Auth: Bearer token (--uw-key flag)
    """
    try:
        import urllib.request
        import urllib.error

        url = f"https://api.unusualwhales.com/api/stock/{ticker.upper()}/flow"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        # UW returns {"data": [...]} — each item is a flow alert
        rows = data.get("data", [])
        if not rows:
            return {"error": "No flow data returned"}

        # Filter to target expiry if specified
        if expiry_str:
            rows = [r for r in rows if r.get("expiry_date", "").startswith(expiry_str)]

        bull_premium = 0.0   # call buys (ask side) + put sells (bid side)
        bear_premium = 0.0   # put buys (ask side) + call sells (bid side)
        sweep_bull   = 0
        sweep_bear   = 0
        unusual_bull = 0
        unusual_bear = 0
        total_rows   = 0
        top_flows    = []

        for r in rows:
            opt_type  = (r.get("type") or r.get("option_type") or "").upper()   # CALL / PUT
            side      = (r.get("side") or "").upper()                            # ASK=buy / BID=sell
            premium   = float(r.get("premium") or r.get("total_premium") or 0)
            is_sweep  = bool(r.get("is_sweep") or r.get("sweep"))
            is_unu    = bool(r.get("is_unusual") or r.get("unusual"))
            strike    = r.get("strike") or r.get("strike_price", "?")
            expiry    = r.get("expiry_date") or r.get("expiry", "?")

            # Determine directional bias
            # Call-buy = bullish, Put-buy = bearish
            # Call-sell = bearish hedge, Put-sell = bullish (selling protection)
            is_bull = (opt_type == "CALL" and side == "ASK") or (opt_type == "PUT" and side == "BID")
            is_bear = (opt_type == "PUT"  and side == "ASK") or (opt_type == "CALL" and side == "BID")

            if is_bull:
                bull_premium += premium
                if is_sweep: sweep_bull += 1
                if is_unu:   unusual_bull += 1
            elif is_bear:
                bear_premium += premium
                if is_sweep: sweep_bear += 1
                if is_unu:   unusual_bear += 1

            total_rows += 1
            if premium > 50_000 and total_rows <= 30:   # keep top big-money prints
                top_flows.append({
                    "type":    opt_type,
                    "strike":  strike,
                    "expiry":  expiry,
                    "side":    "BUY" if side == "ASK" else "SELL",
                    "premium": premium,
                    "sweep":   is_sweep,
                    "unusual": is_unu,
                    "bull":    is_bull,
                })

        total_premium = bull_premium + bear_premium
        if total_premium == 0:
            return {"error": "Flow found but no premium data"}

        bull_pct = round(bull_premium / total_premium * 100, 1)
        bear_pct = round(bear_premium / total_premium * 100, 1)
        net_pct  = round(bull_pct - bear_pct, 1)   # positive = net bullish

        if net_pct >= 15:
            signal = f"Strongly bullish flow (+{net_pct}% net call premium)"
            cls    = "bull"
        elif net_pct >= 5:
            signal = f"Mildly bullish flow (+{net_pct}% net call premium)"
            cls    = "bull"
        elif net_pct <= -15:
            signal = f"Strongly bearish flow ({net_pct}% net put premium)"
            cls    = "bear"
        elif net_pct <= -5:
            signal = f"Mildly bearish flow ({net_pct}% net put premium)"
            cls    = "bear"
        else:
            signal = f"Mixed/neutral flow ({net_pct:+.1f}% net)"
            cls    = "neutral"

        # Sort top flows by premium descending
        top_flows.sort(key=lambda x: x["premium"], reverse=True)

        return {
            "bull_premium":  bull_premium,
            "bear_premium":  bear_premium,
            "bull_pct":      bull_pct,
            "bear_pct":      bear_pct,
            "net_pct":       net_pct,
            "sweep_bull":    sweep_bull,
            "sweep_bear":    sweep_bear,
            "unusual_bull":  unusual_bull,
            "unusual_bear":  unusual_bear,
            "total_rows":    total_rows,
            "signal":        signal,
            "cls":           cls,
            "top_flows":     top_flows[:10],
        }

    except Exception as e:
        return {"error": str(e)}


_BULL_WORDS = {"beat","beats","surge","surges","surged","jump","jumps","jumped","rally",
               "rallies","rallied","upgrade","upgrades","upgraded","buy","outperform",
               "strong","bullish","record","high","gain","gains","positive","boost",
               "boosts","boosted","win","wins","won","deal","partnership","contract"}
_BEAR_WORDS = {"miss","misses","missed","fall","falls","fell","drop","drops","dropped",
               "decline","declines","declined","downgrade","downgrades","downgraded",
               "sell","underperform","weak","bearish","loss","losses","lose","cut",
               "cuts","lawsuit","probe","investigation","fine","recall","layoff",
               "layoffs","warning","warn","concern","risk","negative","lower"}

def get_news_sentiment(ticker: str, max_headlines: int = 15) -> dict:
    """
    Fetch recent news via yfinance and score headlines as bull/bear.
    Returns counts, net score, signal, and top headlines.
    """
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        return {}
    if not news:
        return {}

    bull_count = bear_count = 0
    scored = []
    cutoff = datetime.now().timestamp() - 86400 * 3   # last 3 days

    for item in news[:max_headlines]:
        pub_time = item.get("providerPublishTime") or item.get("content", {}).get("pubDate", 0)
        if isinstance(pub_time, str):
            try:
                pub_time = datetime.fromisoformat(pub_time.replace("Z","+00:00")).timestamp()
            except Exception:
                pub_time = 0
        if pub_time and pub_time < cutoff:
            continue
        title = item.get("title") or (item.get("content") or {}).get("title", "")
        if not title:
            continue
        words = set(title.lower().replace(",","").replace(".","").split())
        bull = len(words & _BULL_WORDS)
        bear = len(words & _BEAR_WORDS)
        if bull > bear:
            bull_count += 1; sentiment = "bull"
        elif bear > bull:
            bear_count += 1; sentiment = "bear"
        else:
            sentiment = "neutral"
        scored.append({"title": title, "sentiment": sentiment,
                        "bull": bull, "bear": bear})

    total = bull_count + bear_count
    if total == 0:
        return {"headlines": scored, "bull_count": 0, "bear_count": 0,
                "net_score": 0, "signal": "No recent scored headlines", "cls": "neutral"}

    net = bull_count - bear_count
    bull_pct = round(bull_count / total * 100)
    if net >= 3:
        signal, cls = f"Strongly bullish news ({bull_count} bull, {bear_count} bear headlines)", "bull"
    elif net >= 1:
        signal, cls = f"Mildly bullish news ({bull_count} bull, {bear_count} bear headlines)", "bull"
    elif net <= -3:
        signal, cls = f"Strongly bearish news ({bear_count} bear, {bull_count} bull headlines)", "bear"
    elif net <= -1:
        signal, cls = f"Mildly bearish news ({bear_count} bear, {bull_count} bull headlines)", "bear"
    else:
        signal, cls = f"Mixed news ({bull_count} bull, {bear_count} bear headlines)", "neutral"

    return {"headlines": scored[:8], "bull_count": bull_count, "bear_count": bear_count,
            "net_score": net, "bull_pct": bull_pct, "signal": signal, "cls": cls}


def get_macro_context(ticker: str) -> dict:
    """
    Fetch SPY / QQQ / VIX / VIX3M / TLT / DXY (UUP) and sector ETF.
    Returns a flat dict with prices, % changes, and interpreted signals.
    """
    result: dict = {}
    sector_etf = SECTOR_ETF_MAP.get(ticker.upper())
    result["sector_etf"] = sector_etf

    syms = ["SPY", "QQQ", "^VIX", "^VIX3M", "TLT", "UUP", "NQ=F", "ES=F"]
    if sector_etf:
        syms.append(sector_etf)

    for sym in syms:
        try:
            fi = yf.Ticker(sym).fast_info
            price = fi.last_price
            prev  = fi.previous_close
            if price is None or prev is None:
                continue
            pct = round((price - prev) / prev * 100, 2)
            key = sym.lstrip("^").replace("-", "_")
            result[key] = {"price": round(float(price), 2),
                           "prev_close": round(float(prev), 2),
                           "pct_chg": pct,
                           "direction": "up" if pct > 0 else "down" if pct < 0 else "flat"}
        except Exception:
            pass

    # VIX regime
    vix_price = (result.get("VIX") or {}).get("price")
    if vix_price:
        if vix_price < 15:
            result["vix_regime"] = "Low <15 — complacency (prefer debit)"
            result["vix_cls"] = "bull"
        elif vix_price < 20:
            result["vix_regime"] = f"Neutral {vix_price:.1f} (16–20)"
            result["vix_cls"] = "neutral"
        elif vix_price < 30:
            result["vix_regime"] = f"Elevated {vix_price:.1f} — fear (prefer credit)"
            result["vix_cls"] = "bear"
        else:
            result["vix_regime"] = f"Panic {vix_price:.1f} >30 — buy dips aggressively"
            result["vix_cls"] = "bear"

    # VIX term structure
    vix3m = (result.get("VIX3M") or {}).get("price")
    if vix_price and vix3m:
        if vix3m < vix_price - 1:
            result["vix_term"] = f"Inverted (VIX3M {vix3m:.1f} < VIX {vix_price:.1f}) — near-term panic"
            result["vix_term_cls"] = "bear"
        else:
            result["vix_term"] = f"Normal (VIX3M {vix3m:.1f} > VIX {vix_price:.1f}) — calm structure"
            result["vix_term_cls"] = "neutral"

    # TLT signal
    tlt = result.get("TLT") or {}
    if tlt.get("pct_chg") is not None:
        if tlt["pct_chg"] < -0.5:
            result["tlt_signal"] = f'TLT {tlt["pct_chg"]:+.2f}% — bonds falling, rates rising (growth headwind)'
            result["tlt_cls"] = "bear"
        elif tlt["pct_chg"] > 0.5:
            result["tlt_signal"] = f'TLT {tlt["pct_chg"]:+.2f}% — bonds rising, rates falling (growth tailwind)'
            result["tlt_cls"] = "bull"
        else:
            result["tlt_signal"] = f'TLT {tlt["pct_chg"]:+.2f}% — flat, neutral bond signal'
            result["tlt_cls"] = "neutral"

    # DXY (UUP proxy)
    uup = result.get("UUP") or {}
    if uup.get("pct_chg") is not None:
        if uup["pct_chg"] > 0.2:
            result["dxy_signal"] = f'Dollar rising {uup["pct_chg"]:+.2f}% — headwind for mega-cap growth'
            result["dxy_cls"] = "bear"
        elif uup["pct_chg"] < -0.2:
            result["dxy_signal"] = f'Dollar falling {uup["pct_chg"]:+.2f}% — tailwind for growth stocks'
            result["dxy_cls"] = "bull"
        else:
            result["dxy_signal"] = f'Dollar flat {uup["pct_chg"]:+.2f}% — neutral DXY'
            result["dxy_cls"] = "neutral"

    # Futures signal (/NQ /ES)
    nq = result.get("NQ_F") or {}
    es = result.get("ES_F") or {}
    if nq.get("pct_chg") is not None or es.get("pct_chg") is not None:
        nq_chg = nq.get("pct_chg", 0) or 0
        es_chg = es.get("pct_chg", 0) or 0
        avg_fut = (nq_chg + es_chg) / 2
        if avg_fut > 0.3:
            result["futures_signal"] = f"/NQ {nq_chg:+.2f}%  /ES {es_chg:+.2f}% — futures bullish, expect gap-up open"
            result["futures_cls"] = "bull"
        elif avg_fut < -0.3:
            result["futures_signal"] = f"/NQ {nq_chg:+.2f}%  /ES {es_chg:+.2f}% — futures bearish, expect gap-down open"
            result["futures_cls"] = "bear"
        else:
            result["futures_signal"] = f"/NQ {nq_chg:+.2f}%  /ES {es_chg:+.2f}% — futures flat, neutral open expected"
            result["futures_cls"] = "neutral"

    # Sector ETF vs QQQ
    if sector_etf and sector_etf in result and "QQQ" in result:
        diff = round(result[sector_etf]["pct_chg"] - result["QQQ"]["pct_chg"], 2)
        if diff < -0.5:
            result["sector_signal"] = f"{sector_etf} underperforming QQQ by {abs(diff):.2f}% — stealth weakness, bearish override"
            result["sector_cls"] = "bear"
        elif diff > 0.5:
            result["sector_signal"] = f"{sector_etf} outperforming QQQ by {diff:.2f}% — sector strength, bullish confirmation"
            result["sector_cls"] = "bull"
        else:
            result["sector_signal"] = f"{sector_etf} in line with QQQ (diff: {diff:+.2f}%) — neutral"
            result["sector_cls"] = "neutral"

    # ── Sector Rotation (5-day relative strength vs SPY) ─────────────────────
    if sector_etf:
        try:
            hist5 = yf.download([sector_etf, "SPY"], period="10d", interval="1d",
                                 progress=False, auto_adjust=True)["Close"].dropna()
            if len(hist5) >= 5:
                sec_5d = float((hist5[sector_etf].iloc[-1] / hist5[sector_etf].iloc[-6] - 1) * 100)
                spy_5d = float((hist5["SPY"].iloc[-1]       / hist5["SPY"].iloc[-6]       - 1) * 100)
                rs_5d  = round(sec_5d - spy_5d, 2)
                if rs_5d > 1.5:
                    rot_signal = f"{sector_etf} +{rs_5d:.1f}% vs SPY (5d) — sector rotation IN, institutional buying"
                    rot_cls    = "bull"
                elif rs_5d < -1.5:
                    rot_signal = f"{sector_etf} {rs_5d:.1f}% vs SPY (5d) — sector rotation OUT, institutional selling"
                    rot_cls    = "bear"
                else:
                    rot_signal = f"{sector_etf} {rs_5d:+.1f}% vs SPY (5d) — no notable rotation"
                    rot_cls    = "neutral"
                result["sector_rotation_5d"]     = rs_5d
                result["sector_rotation_signal"] = rot_signal
                result["sector_rotation_cls"]    = rot_cls
                result["sector_5d_pct"]          = round(sec_5d, 2)
                result["spy_5d_pct"]             = round(spy_5d, 2)
        except Exception:
            pass

    return result


def compute_vpoc(df_1m: pd.DataFrame, bins: int = 100) -> dict:
    """Volume Profile from 1m bars: VPOC, VAH, VAL (70% value area)."""
    try:
        lo = float(df_1m["Low"].min())
        hi = float(df_1m["High"].max())
        if hi <= lo:
            return {}
        edges   = np.linspace(lo, hi, bins + 1)
        centers = (edges[:-1] + edges[1:]) / 2
        vol_per_bin = np.zeros(bins)
        for _, row in df_1m.iterrows():
            bar_lo, bar_hi = float(row["Low"]), float(row["High"])
            mask = (edges[1:] >= bar_lo) & (edges[:-1] <= bar_hi)
            n = int(mask.sum())
            if n > 0:
                vol_per_bin[mask] += float(row["Volume"]) / n
        vpoc_idx = int(np.argmax(vol_per_bin))
        vpoc = round(float(centers[vpoc_idx]), 2)
        # Expand from VPOC to capture 70% of volume (value area)
        target  = vol_per_bin.sum() * 0.70
        lo_idx  = hi_idx = vpoc_idx
        accum   = vol_per_bin[vpoc_idx]
        while accum < target and (lo_idx > 0 or hi_idx < bins - 1):
            add_lo = vol_per_bin[lo_idx - 1] if lo_idx > 0 else 0.0
            add_hi = vol_per_bin[hi_idx + 1] if hi_idx < bins - 1 else 0.0
            if add_lo >= add_hi and lo_idx > 0:
                lo_idx -= 1; accum += add_lo
            elif hi_idx < bins - 1:
                hi_idx += 1; accum += add_hi
            else:
                lo_idx -= 1; accum += add_lo
        return {"vpoc": vpoc,
                "vah":  round(float(centers[hi_idx]), 2),
                "val":  round(float(centers[lo_idx]), 2)}
    except Exception:
        return {}


def get_horizontal_sr(ticker: str, lookback_days: int = 60) -> list:
    """
    Detect key horizontal S/R levels from recent price history.
    Finds local highs/lows, clusters nearby ones, ranks by touch count.
    Returns list of dicts sorted by proximity to current price.
    """
    try:
        hist = yf.Ticker(ticker).history(period=f"{lookback_days + 10}d", interval="1d")
        if hist.empty or len(hist) < 15:
            return []
        highs  = hist["High"].values.astype(float)
        lows   = hist["Low"].values.astype(float)
        spot   = float(hist["Close"].iloc[-1])
        tol    = spot * 0.005          # 0.5% clustering tolerance
        window = 3

        raw: list = []
        for i in range(window, len(hist) - window):
            if all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, window + 1)):
                raw.append(("resistance", float(highs[i])))
            if all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
               all(lows[i] <= lows[i + j] for j in range(1, window + 1)):
                raw.append(("support", float(lows[i])))

        if not raw:
            return []

        # Cluster
        clustered: list = []
        used: set = set()
        for i, (typ, price) in enumerate(raw):
            if i in used:
                continue
            group = [(typ, price)]
            for j, (t2, p2) in enumerate(raw):
                if j != i and j not in used and abs(price - p2) <= tol:
                    group.append((t2, p2)); used.add(j)
            used.add(i)
            avg_p   = round(sum(p for _, p in group) / len(group), 2)
            touches = sum(1 for h, l in zip(highs, lows)
                          if abs(h - avg_p) <= tol or abs(l - avg_p) <= tol)
            lvl_type = "resistance" if avg_p > spot else "support"
            dist_pct = round((avg_p - spot) / spot * 100, 2)
            if abs(dist_pct) > 12:
                continue
            clustered.append({
                "price":      avg_p,
                "type":       lvl_type,
                "touches":    touches,
                "strength":   "Strong" if touches >= 3 else "Moderate" if touches >= 2 else "Weak",
                "strength_cls": "bear" if lvl_type == "resistance" else "bull",
                "dist_pct":   dist_pct,
            })

        clustered.sort(key=lambda x: abs(x["dist_pct"]))
        return clustered[:10]
    except Exception:
        return []


_IV_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".iv_cache.json")


def load_iv_cache() -> dict:
    try:
        with open(_IV_CACHE_FILE) as f:
            import json; return json.load(f)
    except Exception:
        return {}


def save_iv_cache(cache: dict) -> None:
    try:
        import json
        with open(_IV_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


_OI_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".oi_cache.json")

def _load_oi_cache() -> dict:
    try:
        with open(_OI_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_oi_cache(cache: dict) -> None:
    try:
        with open(_OI_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

def get_oi_changes(ticker: str, expiry_str: str, calls: "pd.DataFrame", puts: "pd.DataFrame") -> list:
    """
    Compare today's per-strike OI to yesterday's cached values.
    Returns list of {strike, call_oi, put_oi, call_chg, put_chg, signal, cls}
    sorted by abs(total OI change) descending.
    Strikes with OI change > 20% and > 500 contracts are flagged.
    """
    cache   = _load_oi_cache()
    today   = date.today().isoformat()
    prefix  = f"{ticker}_{expiry_str}_"
    results = []

    # Build today's snapshot
    call_oi_map = {float(r["strike"]): int(r.get("openInterest", 0) or 0)
                   for _, r in calls.iterrows()}
    put_oi_map  = {float(r["strike"]): int(r.get("openInterest", 0) or 0)
                   for _, r in puts.iterrows()}
    all_strikes = sorted(set(list(call_oi_map) + list(put_oi_map)))

    new_cache = dict(cache)  # carry forward everything
    for K in all_strikes:
        c_oi  = call_oi_map.get(K, 0)
        p_oi  = put_oi_map.get(K, 0)
        key   = f"{prefix}{K}"
        prev  = cache.get(key, {})
        prev_c = prev.get("call_oi", c_oi)  # default = no change on first run
        prev_p = prev.get("put_oi",  p_oi)
        c_chg  = c_oi - prev_c
        p_chg  = p_oi - prev_p

        # Only flag meaningful changes: >500 contracts AND >15% change
        c_flag = abs(c_chg) >= 500 and (prev_c == 0 or abs(c_chg) / max(prev_c, 1) >= 0.15)
        p_flag = abs(p_chg) >= 500 and (prev_p == 0 or abs(p_chg) / max(prev_p, 1) >= 0.15)

        new_cache[key] = {"date": today, "call_oi": c_oi, "put_oi": p_oi}

        if c_flag or p_flag:
            if c_chg > 0 and p_chg <= 0:
                signal, cls = f"New call buying (+{c_chg:,} OI overnight)", "bull"
            elif p_chg > 0 and c_chg <= 0:
                signal, cls = f"New put buying (+{p_chg:,} OI overnight)", "bear"
            elif c_chg > 0 and p_chg > 0:
                signal, cls = f"Both calls +{c_chg:,} puts +{p_chg:,} — straddle/strangle", "neutral"
            elif c_chg < 0 and p_chg < 0:
                signal, cls = f"OI dropping — positions closing (calls {c_chg:,}, puts {p_chg:,})", "neutral"
            else:
                signal, cls = f"Mixed OI change", "neutral"
            results.append({"strike": K, "call_oi": c_oi, "put_oi": p_oi,
                             "call_chg": c_chg, "put_chg": p_chg,
                             "signal": signal, "cls": cls})

    _save_oi_cache(new_cache)
    results.sort(key=lambda x: abs(x["call_chg"]) + abs(x["put_chg"]), reverse=True)
    return results[:15]


def get_iv_momentum(ticker: str, expiry_str: str, current_iv: float) -> dict:
    """
    Compare current ATM IV to yesterday's cached value.
    Returns iv_change, iv_momentum signal, and updates the cache.
    """
    cache = load_iv_cache()
    key   = f"{ticker}_{expiry_str}"
    today_str = date.today().isoformat()

    result: dict = {}
    prev_entry = cache.get(key)
    if prev_entry and prev_entry.get("date") != today_str:
        prev_iv  = prev_entry.get("iv")
        prev_date = prev_entry.get("date")
        if prev_iv is not None and prev_iv > 0:
            iv_chg = round(current_iv - prev_iv, 1)
            result["iv_yesterday"]   = prev_iv
            result["iv_yesterday_date"] = prev_date
            result["iv_change"]      = iv_chg
            if iv_chg > 3:
                result["iv_momentum"] = f"IV surged +{iv_chg:.1f}pts since {prev_date} — protection buying / fear spike"
                result["iv_mom_cls"]  = "bear"
            elif iv_chg < -3:
                result["iv_momentum"] = f"IV collapsed {iv_chg:.1f}pts since {prev_date} — calm, options getting cheaper"
                result["iv_mom_cls"]  = "bull"
            else:
                result["iv_momentum"] = f"IV stable ({iv_chg:+.1f}pts vs {prev_date}) — no unusual premium change"
                result["iv_mom_cls"]  = "neutral"

    # Always update cache with today's value
    cache[key] = {"date": today_str, "iv": current_iv}
    save_iv_cache(cache)
    return result


def compute_dap(calls: "pd.DataFrame", puts: "pd.DataFrame",
                spot: float, T: float) -> list:
    """
    Delta-Adjusted OI (DAP) per strike.
    DAP_call = BS_delta × call_OI   (positive — dealer long delta)
    DAP_put  = BS_delta × put_OI    (negative — dealer short delta)
    Net DAP at strike = call_DAP + put_DAP
    Positive net DAP = dealers net long → they sell into rallies (bearish headwind).
    Negative net DAP = dealers net short → they buy dips (bullish support).
    """
    from math import log, sqrt, exp, pi as PI

    def _bs_delta_call(S, K, T_, sigma, r=0.05):
        if T_ <= 0 or sigma <= 0:
            return 0.5
        try:
            d1 = (log(S / K) + (r + 0.5 * sigma ** 2) * T_) / (sigma * sqrt(T_))
            # Approximation of N(d1) without scipy
            return 0.5 * (1 + math.erf(d1 / sqrt(2)))
        except Exception:
            return 0.5

    rows: list = []
    all_strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
    for K in all_strikes:
        c_rows = calls[calls["strike"] == K]
        p_rows = puts[puts["strike"] == K]
        c_oi   = float(c_rows["openInterest"].sum()) if not c_rows.empty else 0
        p_oi   = float(p_rows["openInterest"].sum()) if not p_rows.empty else 0
        c_iv   = float(c_rows["impliedVolatility"].mean()) if not c_rows.empty else 0
        p_iv   = float(p_rows["impliedVolatility"].mean()) if not p_rows.empty else 0
        c_delta = _bs_delta_call(spot, K, T, c_iv) if c_iv > 0 else 0.5
        p_delta = c_delta - 1            # put-call parity: put Δ = call Δ − 1
        call_dap = round(c_delta * c_oi, 0)
        put_dap  = round(p_delta * p_oi, 0)
        net_dap  = round(call_dap + put_dap, 0)
        dist     = round((K - spot) / spot * 100, 2)
        if abs(dist) <= 10:
            rows.append({"strike": K, "call_dap": call_dap, "put_dap": put_dap,
                         "net_dap": net_dap, "dist_pct": dist})
    rows.sort(key=lambda x: x["strike"], reverse=True)
    return rows


def compute_max_pain_gravity(spot: float, max_pain: float, dte: int) -> dict:
    """
    Gravity score 0–100: how strongly max pain will pin price by expiry.
    Factors: distance (closer = stronger) × DTE urgency (fewer DTE = stronger).
    """
    if spot is None or max_pain is None or dte is None or spot == 0:
        return {}
    dist_pct  = abs(spot - max_pain) / spot * 100
    # DTE urgency: peaks at 0 DTE, minimal at 10+ DTE
    dte_factor  = max(0.0, 1 - dte / 10)
    # Distance factor: 0% away = 100, 5% away = 0
    dist_factor = max(0.0, 1 - dist_pct / 5)
    gravity     = round((dte_factor * 0.5 + dist_factor * 0.5) * 100)
    direction   = "upward" if max_pain > spot else "downward"
    if gravity >= 70:
        label = f"Strong — {gravity}/100, expect {direction} drift toward ${max_pain:.2f}"
        cls   = "bear" if direction == "downward" else "bull"
    elif gravity >= 40:
        label = f"Moderate — {gravity}/100, mild {direction} pull"
        cls   = "neutral"
    else:
        label = f"Weak — {gravity}/100, max pain gravity minimal with {dte} DTE"
        cls   = "neutral"
    return {"gravity": gravity, "label": label, "cls": cls,
            "dist_pct": round(dist_pct, 2), "direction": direction}


def compute_volume_anomaly(df_1m: pd.DataFrame, lookback_bars: int = 5) -> dict:
    """
    Compare current bar volume to the session average and recent average.
    Flags unusual volume spikes that indicate institutional activity.
    """
    try:
        vols = df_1m["Volume"].dropna().astype(float)
        if len(vols) < 10:
            return {}
        current  = float(vols.iloc[-1])
        session_avg = float(vols.mean())
        recent_avg  = float(vols.iloc[-lookback_bars - 1:-1].mean()) if len(vols) > lookback_bars else session_avg
        vs_session  = round(current / session_avg,  2) if session_avg > 0 else 1.0
        vs_recent   = round(current / recent_avg,   2) if recent_avg  > 0 else 1.0
        if vs_session > 3 or vs_recent > 3:
            signal = f"🔥 Volume spike {vs_session:.1f}× session avg — institutional activity likely"
            cls    = "bear"   # high vol can be distribution or accumulation — flag it
        elif vs_session > 1.5:
            signal = f"📈 Elevated volume {vs_session:.1f}× session avg — increased interest"
            cls    = "neutral"
        else:
            signal = f"Volume normal ({vs_session:.1f}× session avg)"
            cls    = "neutral"
        return {"current_vol": int(current), "session_avg": int(session_avg),
                "vs_session": vs_session, "vs_recent": vs_recent,
                "signal": signal, "cls": cls}
    except Exception:
        return {}


def compute_position_size(last: float, strategy: str, debit_or_credit: float,
                          max_loss_per_contract: float,
                          account_size: float = 25000,
                          risk_pct: float = 1.0) -> dict:
    """
    Calculate position sizing: max contracts given account size and risk %.
    risk_pct: % of account to risk on this trade (default 1%).
    """
    if last <= 0 or max_loss_per_contract <= 0 or account_size <= 0:
        return {}
    max_risk_dollars   = round(account_size * risk_pct / 100, 2)
    max_contracts      = max(1, int(max_risk_dollars / (max_loss_per_contract * 100)))
    total_risk         = round(max_contracts * max_loss_per_contract * 100, 2)
    total_cost         = round(max_contracts * debit_or_credit * 100, 2)
    return {
        "account_size":       account_size,
        "risk_pct":           risk_pct,
        "max_risk_dollars":   max_risk_dollars,
        "max_contracts":      max_contracts,
        "max_loss_per_contract": max_loss_per_contract,
        "total_risk":         total_risk,
        "total_cost":         total_cost,
        "cost_pct_account":   round(total_cost / account_size * 100, 2),
    }


def backtest_technicals(ticker: str, lookback_days: int = 120) -> dict:
    """
    Backtest our technical signal model vs next-day returns over recent history.
    Uses EMA9/21 position, RSI, MACD histogram — signals we can compute historically.
    Returns win rates and average returns per signal class (bull / bear / neutral).
    """
    try:
        hist = yf.Ticker(ticker).history(period=f"{lookback_days + 40}d", interval="1d")
        if hist.empty or len(hist) < 40:
            return {}
        close = hist["Close"].squeeze().astype(float)
        hist  = hist.copy()
        hist["EMA9"]      = close.ewm(span=9,  adjust=False).mean()
        hist["EMA21"]     = close.ewm(span=21, adjust=False).mean()
        delta = close.diff()
        g = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        l = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        hist["RSI"]       = 100 - (100 / (1 + g / l.replace(0, float("nan"))))
        hist["MACD_HIST"] = (close.ewm(span=12, adjust=False).mean()
                             - close.ewm(span=26, adjust=False).mean())

        buckets: dict = {"bull": [], "bear": [], "neutral": []}
        for i in range(26, len(hist) - 1):
            row     = hist.iloc[i]
            nxt_ret = float((hist.iloc[i + 1]["Close"] - row["Close"]) / row["Close"])
            c, e9, e21 = float(row["Close"]), float(row["EMA9"]), float(row["EMA21"])
            r   = float(row["RSI"])  if not math.isnan(float(row["RSI"]))  else 50.0
            mh  = float(row["MACD_HIST"])
            bull = bear = 0
            if c > e9:  bull += 2
            else:        bear += 2
            if c > e21: bull += 2
            else:        bear += 2
            if r > 50:  bull += 2
            else:        bear += 2
            if mh > 0:  bull += 1
            else:        bear += 1
            total = bull + bear
            score = bull / total * 100 if total else 50
            cls   = "bull" if score >= 60 else "bear" if score <= 40 else "neutral"
            buckets[cls].append(nxt_ret)

        def _stats(rets: list, direction: str) -> Optional[dict]:
            if not rets:
                return None
            correct = sum(1 for r in rets
                          if (direction == "bull" and r > 0) or (direction == "bear" and r < 0))
            wins  = [r for r in rets if r > 0]
            losses= [r for r in rets if r < 0]
            return {
                "count":      len(rets),
                "win_rate":   round(correct / len(rets) * 100, 1),
                "avg_return": round(sum(rets) / len(rets) * 100, 3),
                "avg_win":    round(sum(wins)   / len(wins)   * 100, 3) if wins   else 0.0,
                "avg_loss":   round(sum(losses) / len(losses) * 100, 3) if losses else 0.0,
            }

        return {
            "ticker":        ticker.upper(),
            "lookback_days": lookback_days,
            "bull":    _stats(buckets["bull"],    "bull"),
            "bear":    _stats(buckets["bear"],    "bear"),
            "neutral": _stats(buckets["neutral"], "neutral"),
        }
    except Exception:
        return {}


def get_level2_ibkr(ticker: str, port: int = 7497, client_id: int = 14) -> Optional[dict]:
    """Fetch Level 2 market depth (top 5 bid/ask) from IBKR TWS."""
    if not HAS_IB:
        return None
    import time as _time
    ib = IB()
    ib_util.logToConsole(50)
    try:
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=8, readonly=True)
        stock = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(stock)
        depth = ib.reqMktDepth(stock, numRows=5)
        ib.sleep(2)

        bids = [{"price": round(float(r.price), 2), "size": int(r.size)}
                for r in (depth.domBids or [])]
        asks = [{"price": round(float(r.price), 2), "size": int(r.size)}
                for r in (depth.domAsks or [])]

        ib.cancelMktDepth(stock)
        if not bids and not asks:
            return None

        total_bid = sum(b["size"] for b in bids)
        total_ask = sum(a["size"] for a in asks)
        ratio     = round(total_bid / total_ask, 2) if total_ask else None

        return {
            "bids": bids[:5], "asks": asks[:5],
            "total_bid_size": total_bid,
            "total_ask_size": total_ask,
            "bid_ask_ratio":  ratio,
            "l2_signal": ("Buyers dominating" if (ratio or 0) > 1.5
                          else "Sellers dominating" if (ratio or 0) < 0.67
                          else "Balanced order book"),
            "l2_cls":    ("bull" if (ratio or 0) > 1.5
                          else "bear" if (ratio or 0) < 0.67
                          else "neutral"),
        }
    except Exception as e:
        print(f"    ⚠  IBKR L2 not available: {e}")
        return None
    finally:
        try: ib.disconnect()
        except: pass


def resample_5m(df_1m: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Resample 1m bars to 5m and compute EMA9 for entry-trigger analysis."""
    try:
        df = df_1m.copy()
        df.index = pd.to_datetime(df.index)
        df5 = df.resample("5min").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
        if len(df5) < 10:
            return None
        df5["EMA9"]  = df5["Close"].ewm(span=9,  adjust=False).mean()
        df5["EMA21"] = df5["Close"].ewm(span=21, adjust=False).mean()
        df5["RSI"]   = rsi(df5["Close"].squeeze(), 14)
        typical5 = (df5["High"] + df5["Low"] + df5["Close"]) / 3
        df5["VWAP"] = (typical5 * df5["Volume"]).cumsum() / df5["Volume"].cumsum()
        return df5
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. LIVE OPTIONS CHAIN  (yfinance — ~15 min delay on free tier)
# ─────────────────────────────────────────────────────────────────────────────

def get_options_chain(ticker: str, expiry_date: date) -> Optional[dict]:
    """
    Fetch the real options chain for the nearest expiry >= expiry_date.
    Returns a dict with max_pain, PCR, ATM IV, gamma walls, top OI strikes.
    Returns None if chain data is unavailable.
    """
    tk = yf.Ticker(ticker)
    try:
        expirations = tk.options          # e.g. ["2026-06-20", "2026-06-27", …]
    except Exception:
        return None
    if not expirations:
        return None

    # Pick nearest expiry on or after the requested date
    target_str = expiry_date.strftime("%Y-%m-%d")
    expiry_str = next((e for e in sorted(expirations) if e >= target_str), expirations[-1])

    try:
        chain = tk.option_chain(expiry_str)
    except Exception:
        return None

    calls = chain.calls.fillna(0).copy()
    puts  = chain.puts.fillna(0).copy()

    # ── Current price ────────────────────────────────────────────────────────
    try:
        spot = tk.fast_info.last_price
    except Exception:
        spot = None

    # ── Max Pain ─────────────────────────────────────────────────────────────
    all_strikes = sorted(set(calls["strike"].tolist() + puts["strike"].tolist()))
    max_pain_strike = None
    min_pain = float("inf")
    for s in all_strikes:
        call_pain = sum((s - k) * oi for k, oi in
                        zip(calls["strike"], calls["openInterest"]) if k < s)
        put_pain  = sum((k - s) * oi for k, oi in
                        zip(puts["strike"],  puts["openInterest"])  if k > s)
        total = call_pain + put_pain
        if total < min_pain:
            min_pain, max_pain_strike = total, s

    # ── PCR ──────────────────────────────────────────────────────────────────
    cv, pv = calls["volume"].sum(), puts["volume"].sum()
    coi, poi = calls["openInterest"].sum(), puts["openInterest"].sum()
    pcr_vol = round(pv / cv,  2) if cv  > 0 else 0.0
    pcr_oi  = round(poi / coi, 2) if coi > 0 else 0.0

    # ── ATM IV + Greeks ──────────────────────────────────────────────────────
    atm_iv = atm_delta = atm_gamma = atm_theta = atm_vega = None
    atm_strike = None
    if spot is not None and not calls.empty:
        idx = (calls["strike"] - spot).abs().idxmin()
        atm_strike = float(calls.loc[idx, "strike"])
        atm_iv     = round(float(calls.loc[idx, "impliedVolatility"]) * 100, 1)
        for greek, col in [("atm_delta", "delta"), ("atm_gamma", "gamma"),
                           ("atm_theta", "theta"), ("atm_vega", "vega")]:
            if col in calls.columns:
                val = calls.loc[idx, col]
                locals()[greek]  # ensure name exists — assign below
        atm_delta = round(float(calls.loc[idx, "delta"]), 4) if "delta" in calls.columns else None
        atm_gamma = round(float(calls.loc[idx, "gamma"]), 4) if "gamma" in calls.columns else None
        atm_theta = round(float(calls.loc[idx, "theta"]), 4) if "theta" in calls.columns else None
        atm_vega  = round(float(calls.loc[idx, "vega"]),  4) if "vega"  in calls.columns else None

    # ── IV Rank (52-week HV proxy) ───────────────────────────────────────────
    iv_rank = iv_pct = hv_20 = hv_52w_low = hv_52w_high = None
    try:
        hist = tk.history(period="1y", interval="1d")
        if not hist.empty and len(hist) >= 22:
            log_ret = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
            roll_hv = log_ret.rolling(20).std().dropna() * np.sqrt(252) * 100
            if len(roll_hv) >= 2:
                hv_20      = round(float(roll_hv.iloc[-1]), 1)
                hv_52w_low = round(float(roll_hv.min()), 1)
                hv_52w_high= round(float(roll_hv.max()), 1)
                rng = hv_52w_high - hv_52w_low
                if atm_iv is not None and rng > 0:
                    iv_rank = round((atm_iv - hv_52w_low) / rng * 100, 1)
                    iv_rank = max(0.0, min(100.0, iv_rank))
                    iv_pct  = round(float(np.mean(roll_hv < atm_iv)) * 100, 1)
    except Exception:
        pass

    # ── IV Rank label ────────────────────────────────────────────────────────
    if iv_rank is not None:
        if iv_rank < 20:
            ivr_label, ivr_cls = "Very Low — buy debit spreads", "bull"
        elif iv_rank < 40:
            ivr_label, ivr_cls = "Low — debit spreads preferred", "bull"
        elif iv_rank < 60:
            ivr_label, ivr_cls = "Moderate — neutral strategy", "neutral"
        elif iv_rank < 80:
            ivr_label, ivr_cls = "High — credit spreads preferred", "bear"
        else:
            ivr_label, ivr_cls = "Very High — sell premium", "bear"
    else:
        ivr_label, ivr_cls = "Unavailable", "neutral"

    # ── Realized Vol vs IV spread ─────────────────────────────────────────────
    iv_hv_spread = iv_hv_signal = iv_hv_cls = None
    if atm_iv is not None and hv_20 is not None:
        iv_hv_spread = round(atm_iv - hv_20, 1)
        if iv_hv_spread > 8:
            iv_hv_signal = f"IV {atm_iv:.1f}% >> HV20 {hv_20:.1f}% (+{iv_hv_spread:.1f}%) — options overpriced, SELL premium"
            iv_hv_cls    = "bear"
        elif iv_hv_spread < -8:
            iv_hv_signal = f"IV {atm_iv:.1f}% << HV20 {hv_20:.1f}% ({iv_hv_spread:.1f}%) — options underpriced, BUY debit spreads"
            iv_hv_cls    = "bull"
        else:
            iv_hv_signal = f"IV {atm_iv:.1f}% ≈ HV20 {hv_20:.1f}% (spread {iv_hv_spread:+.1f}%) — fair value"
            iv_hv_cls    = "neutral"

    # ── Implied move (ATM straddle price ÷ spot) ─────────────────────────────
    implied_move_dollar = implied_move_pct = None
    atm_call_spread_pct = atm_put_spread_pct = None
    atm_call_mid = atm_put_mid = None
    if spot is not None and atm_strike is not None and not puts.empty:
        p_idx = (puts["strike"] - spot).abs().idxmin()
        c_last = float(calls.loc[idx, "lastPrice"]) if "lastPrice" in calls.columns else 0
        p_last = float(puts.loc[p_idx, "lastPrice"]) if "lastPrice" in puts.columns else 0
        if c_last > 0 and p_last > 0:
            implied_move_dollar = round(c_last + p_last, 2)
            implied_move_pct    = round(implied_move_dollar / spot * 100, 2)
        # Bid-ask spread quality
        if "bid" in calls.columns and "ask" in calls.columns:
            c_bid = float(calls.loc[idx, "bid"]); c_ask = float(calls.loc[idx, "ask"])
            c_mid = (c_bid + c_ask) / 2
            if c_mid > 0:
                atm_call_spread_pct = round((c_ask - c_bid) / c_mid * 100, 1)
                atm_call_mid = round(c_mid, 2)
        if "bid" in puts.columns and "ask" in puts.columns:
            p_bid = float(puts.loc[p_idx, "bid"]); p_ask = float(puts.loc[p_idx, "ask"])
            p_mid = (p_bid + p_ask) / 2
            if p_mid > 0:
                atm_put_spread_pct = round((p_ask - p_bid) / p_mid * 100, 1)
                atm_put_mid = round(p_mid, 2)

    # ── 25Δ Risk Reversal (Skew) ─────────────────────────────────────────────
    skew_25d = iv_call_25d = iv_put_25d = None
    strike_call_25d = strike_put_25d = None
    skew_label = skew_cls = None
    if spot and atm_iv and not calls.empty and not puts.empty:
        try:
            exp_date_obj = date.fromisoformat(expiry_str)
            dte_days = max((exp_date_obj - date.today()).days, 1)
            sigma = atm_iv / 100
            T = dte_days / 252
            offset = 0.674 * sigma * math.sqrt(T)   # N^{-1}(0.75) ≈ 0.674
            c25_target = spot * math.exp(offset)
            p25_target = spot * math.exp(-offset)
            c_idx_25 = (calls["strike"] - c25_target).abs().idxmin()
            p_idx_25 = (puts["strike"]  - p25_target).abs().idxmin()
            iv_call_25d = round(float(calls.loc[c_idx_25, "impliedVolatility"]) * 100, 1)
            iv_put_25d  = round(float(puts.loc[p_idx_25,  "impliedVolatility"]) * 100, 1)
            strike_call_25d = float(calls.loc[c_idx_25, "strike"])
            strike_put_25d  = float(puts.loc[p_idx_25,  "strike"])
            skew_25d = round(iv_call_25d - iv_put_25d, 1)
            if skew_25d > 2:
                skew_label = "Call skew — upside pricing / squeeze potential"
                skew_cls   = "bull"
            elif skew_25d < -2:
                skew_label = "Put skew — downside protection / crash pricing"
                skew_cls   = "bear"
            else:
                skew_label = "Neutral skew — no strong directional IV bias"
                skew_cls   = "neutral"
        except Exception:
            pass

    # ── IV Term Structure (ATM IV across next 5 expirations) ─────────────────
    term_structure = []
    try:
        for exp in sorted(expirations)[:6]:
            try:
                exp_d = date.fromisoformat(exp)
                dte_exp = max((exp_d - date.today()).days, 1)
                if exp == expiry_str:
                    term_structure.append({"expiry": exp, "dte": dte_exp, "atm_iv": atm_iv})
                    continue
                ch = tk.option_chain(exp)
                c = ch.calls.fillna(0)
                if c.empty or spot is None:
                    continue
                ai = (c["strike"] - spot).abs().idxmin()
                iv_exp = round(float(c.loc[ai, "impliedVolatility"]) * 100, 1)
                term_structure.append({"expiry": exp, "dte": dte_exp, "atm_iv": iv_exp})
            except Exception:
                pass
    except Exception:
        pass

    # ── GEX (Gamma Exposure) per strike ──────────────────────────────────────
    gex_by_strike: dict = {}
    net_gex = top_pin_strike = top_flip_strike = None
    if spot and atm_iv and not calls.empty:
        try:
            exp_obj = date.fromisoformat(expiry_str)
            dte_gex = max((exp_obj - date.today()).days, 1)
            T_gex = dte_gex / 252
            for _, row in calls.iterrows():
                K = float(row["strike"]); oi = float(row.get("openInterest", 0) or 0)
                iv = float(row["impliedVolatility"]) if row["impliedVolatility"] > 0 else atm_iv / 100
                if oi > 0:
                    g = _bs_gamma(spot, K, T_gex, iv)
                    gex_by_strike[K] = gex_by_strike.get(K, 0.0) + g * oi * 100 * spot
            for _, row in puts.iterrows():
                K = float(row["strike"]); oi = float(row.get("openInterest", 0) or 0)
                iv = float(row["impliedVolatility"]) if row["impliedVolatility"] > 0 else atm_iv / 100
                if oi > 0:
                    g = _bs_gamma(spot, K, T_gex, iv)
                    gex_by_strike[K] = gex_by_strike.get(K, 0.0) - g * oi * 100 * spot
            if gex_by_strike:
                net_gex = round(sum(gex_by_strike.values()), 2)
                top_pin_strike  = max(gex_by_strike, key=lambda k: gex_by_strike[k])
                top_flip_strike = min(gex_by_strike, key=lambda k: gex_by_strike[k])

                # ── GEX-based price prediction ────────────────────────────────
                # Gamma walls: strikes with largest positive GEX = resistance/support
                # Flip point: most negative GEX strike = breakout trigger
                # Expected daily move constrained by dealer hedging = spot * ATM_IV / sqrt(252)
                pos_strikes = sorted([(k, v) for k, v in gex_by_strike.items() if v > 0],
                                     key=lambda x: -x[1])
                neg_strikes = sorted([(k, v) for k, v in gex_by_strike.items() if v < 0],
                                     key=lambda x: x[1])

                # Top resistance wall (highest +GEX above spot)
                gex_resistance = next((k for k, _ in pos_strikes if k > spot), None)
                # Top support wall (highest +GEX below spot)
                gex_support    = next((k for k, _ in pos_strikes if k < spot), None)
                # Flip level — most negative GEX (dealers flip from long to short gamma)
                gex_flip_level = neg_strikes[0][0] if neg_strikes else top_flip_strike

                # Dealer-hedging expected range for the session
                # Positive GEX compresses move; negative GEX amplifies it
                raw_daily_move = spot * (atm_iv / 100) / math.sqrt(252)
                gex_compression = max(0.5, 1.0 - min(abs(net_gex) / (abs(net_gex) + 1e6), 0.5)) \
                                  if net_gex > 0 else \
                                  min(2.0, 1.0 + min(abs(net_gex) / (abs(net_gex) + 1e6), 1.0))
                gex_expected_move = round(raw_daily_move * gex_compression, 2)
                gex_upper_band    = round(spot + gex_expected_move, 2)
                gex_lower_band    = round(spot - gex_expected_move, 2)

                # Predicted option price impact:
                # If spot moves to upper/lower band, ATM call/put delta * move = premium change
                atm_delta_est = 0.50
                gex_call_gain  = round(atm_delta_est * gex_expected_move, 2)
                gex_put_gain   = round(atm_delta_est * gex_expected_move, 2)

                # Regime label
                if net_gex > 0:
                    gex_regime       = "Pinning"
                    gex_regime_desc  = "Dealers long gamma → sell rallies, buy dips. Price compresses toward pin zone."
                    gex_regime_cls   = "neutral"
                else:
                    gex_regime       = "Trending"
                    gex_regime_desc  = "Dealers short gamma → buy rallies, sell dips. Price moves amplified."
                    gex_regime_cls   = "bull" if (spot > top_pin_strike if top_pin_strike else False) else "bear"
        except Exception:
            gex_resistance = gex_support = gex_flip_level = None
            gex_expected_move = gex_upper_band = gex_lower_band = None
            gex_call_gain = gex_put_gain = None
            gex_regime = gex_regime_desc = gex_regime_cls = None
            pass

    # Detect vol term structure shape
    term_shape = term_label = None
    if len(term_structure) >= 2:
        near_iv = term_structure[0]["atm_iv"]
        far_iv  = term_structure[-1]["atm_iv"]
        if near_iv is not None and far_iv is not None:
            if near_iv > far_iv + 3:
                term_shape, term_label = "backwardation", "Near-term fear / event risk"
            elif far_iv > near_iv + 3:
                term_shape, term_label = "contango", "Normal / calm market"
            else:
                term_shape, term_label = "flat", "Flat term structure"

    # ── Gamma walls = top-OI strikes (enriched with Greeks + vol/OI ratio) ──
    want_cols = ["strike", "openInterest", "volume", "impliedVolatility",
                 "bid", "ask", "lastPrice", "delta", "gamma", "theta", "vega"]
    greek_cols   = [c for c in want_cols if c in calls.columns]
    greek_cols_p = [c for c in want_cols if c in puts.columns]
    top_calls_raw = calls.nlargest(5, "openInterest")[greek_cols].to_dict("records")
    top_puts_raw  = puts.nlargest(5, "openInterest")[greek_cols_p].to_dict("records")

    def _enrich(rows: list) -> list:
        out = []
        for r in rows:
            oi  = r.get("openInterest", 0) or 0
            vol = r.get("volume", 0) or 0
            bid = r.get("bid", 0) or 0
            ask = r.get("ask", 0) or 0
            mid = (bid + ask) / 2
            r["vol_oi_ratio"]    = round(vol / oi, 2) if oi > 0 else None
            r["bid_ask_pct"]     = round((ask - bid) / mid * 100, 1) if mid > 0 else None
            r["liquidity_flag"]  = "⚠ Illiquid" if (r["bid_ask_pct"] or 0) > 15 else "✅ Liquid"
            r["impliedVolatility"] = round(r["impliedVolatility"] * 100, 1)
            out.append(r)
        return out

    top_calls = _enrich(top_calls_raw)
    top_puts  = _enrich(top_puts_raw)
    call_wall = float(top_calls[0]["strike"]) if top_calls else None
    put_wall  = float(top_puts[0]["strike"])  if top_puts  else None

    # ── Per-Expiry PCR (where is hedging concentrated?) ──────────────────────
    expiry_pcr = []
    try:
        for exp in sorted(expirations)[:8]:
            try:
                ch_e  = tk.option_chain(exp)
                cv_e  = ch_e.calls["volume"].sum()
                pv_e  = ch_e.puts["volume"].sum()
                coi_e = ch_e.calls["openInterest"].sum()
                poi_e = ch_e.puts["openInterest"].sum()
                pcr_v = round(pv_e / cv_e,  2) if cv_e  > 0 else None
                pcr_o = round(poi_e / coi_e, 2) if coi_e > 0 else None
                dte_e = max((date.fromisoformat(exp) - date.today()).days, 0)
                if pcr_v is not None:
                    if pcr_v < 0.7:   ep_cls = "bull"
                    elif pcr_v > 1.3: ep_cls = "bear"
                    else:              ep_cls = "neutral"
                    expiry_pcr.append({"expiry": exp, "dte": dte_e,
                                       "pcr_vol": pcr_v, "pcr_oi": pcr_o,
                                       "call_vol": int(cv_e), "put_vol": int(pv_e),
                                       "call_oi": int(coi_e), "put_oi": int(poi_e),
                                       "cls": ep_cls})
            except Exception:
                pass
    except Exception:
        pass

    # ── Strike Buy Pressure (lastPrice vs mid → aggressive buyer proxy) ────
    strike_pressure = []
    try:
        for frame, opt_type in [(calls, "CALL"), (puts, "PUT")]:
            for _, row in frame.iterrows():
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                last = float(row.get("lastPrice", 0) or 0)
                oi   = float(row.get("openInterest", 0) or 0)
                vol  = float(row.get("volume", 0) or 0)
                K    = float(row["strike"])
                if bid <= 0 or ask <= 0 or last <= 0 or oi < 100:
                    continue
                mid = (bid + ask) / 2
                # Pressure: how far last print is above/below mid
                # >0 = paid above mid (aggressive buyer), <0 = sold below mid
                pressure = round((last - mid) / mid * 100, 1) if mid > 0 else 0
                vol_oi   = round(vol / oi, 2) if oi > 0 else 0
                # Score: weighted by vol/OI spike and pressure
                score = round(pressure * min(vol_oi, 5), 1)
                if abs(score) > 1 and vol > 50:
                    strike_pressure.append({
                        "strike": K, "type": opt_type,
                        "pressure": pressure, "vol_oi": vol_oi,
                        "score": score, "vol": int(vol), "oi": int(oi),
                        "cls": "bull" if (score > 0 and opt_type == "CALL") or
                                         (score < 0 and opt_type == "PUT") else "bear",
                    })
        strike_pressure.sort(key=lambda x: abs(x["score"]), reverse=True)
        strike_pressure = strike_pressure[:12]
    except Exception:
        pass

    # ── Sentiment label ──────────────────────────────────────────────────────
    if pcr_vol < 0.7:
        pcr_sentiment, pcr_cls = "Greed (call-heavy)", "bull"
    elif pcr_vol < 1.0:
        pcr_sentiment, pcr_cls = "Mild Greed", "bull"
    elif pcr_vol < 1.3:
        pcr_sentiment, pcr_cls = "Neutral / Balanced", "neutral"
    elif pcr_vol < 1.6:
        pcr_sentiment, pcr_cls = "Mild Fear (put-heavy)", "bear"
    else:
        pcr_sentiment, pcr_cls = "Extreme Fear", "bear"

    return dict(
        expiry_used=expiry_str,
        max_pain=max_pain_strike,
        pcr_vol=pcr_vol,
        pcr_oi=pcr_oi,
        pcr_sentiment=pcr_sentiment,
        pcr_cls=pcr_cls,
        atm_iv=atm_iv,
        atm_strike=atm_strike,
        atm_delta=atm_delta,
        atm_gamma=atm_gamma,
        atm_theta=atm_theta,
        atm_vega=atm_vega,
        iv_rank=iv_rank,
        iv_pct=iv_pct,
        ivr_label=ivr_label,
        ivr_cls=ivr_cls,
        hv_20=hv_20,
        hv_52w_low=hv_52w_low,
        hv_52w_high=hv_52w_high,
        call_wall=call_wall,
        put_wall=put_wall,
        top_calls=top_calls,
        top_puts=top_puts,
        total_call_vol=int(cv),
        total_put_vol=int(pv),
        total_call_oi=int(coi),
        total_put_oi=int(poi),
        all_strikes=all_strikes,
        spot=spot,
        implied_move_dollar=implied_move_dollar,
        implied_move_pct=implied_move_pct,
        atm_call_spread_pct=atm_call_spread_pct,
        atm_put_spread_pct=atm_put_spread_pct,
        atm_call_mid=atm_call_mid,
        atm_put_mid=atm_put_mid,
        skew_25d=skew_25d,
        iv_call_25d=iv_call_25d,
        iv_put_25d=iv_put_25d,
        strike_call_25d=strike_call_25d,
        strike_put_25d=strike_put_25d,
        skew_label=skew_label,
        skew_cls=skew_cls,
        term_structure=term_structure,
        term_shape=term_shape,
        term_label=term_label,
        gex_by_strike=gex_by_strike,
        net_gex=net_gex,
        top_pin_strike=top_pin_strike,
        top_flip_strike=top_flip_strike,
        gex_resistance=locals().get("gex_resistance"),
        gex_support=locals().get("gex_support"),
        gex_flip_level=locals().get("gex_flip_level"),
        gex_expected_move=locals().get("gex_expected_move"),
        gex_upper_band=locals().get("gex_upper_band"),
        gex_lower_band=locals().get("gex_lower_band"),
        gex_call_gain=locals().get("gex_call_gain"),
        gex_put_gain=locals().get("gex_put_gain"),
        gex_regime=locals().get("gex_regime"),
        gex_regime_desc=locals().get("gex_regime_desc"),
        gex_regime_cls=locals().get("gex_regime_cls"),
        iv_hv_spread=iv_hv_spread,
        iv_hv_signal=iv_hv_signal,
        iv_hv_cls=iv_hv_cls,
        expiry_pcr=expiry_pcr,
        strike_pressure=strike_pressure,
        # DAP computed in main() after chain fetch (needs dte)
        dap=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. CATALYST CALENDAR
# ─────────────────────────────────────────────────────────────────────────────

def get_catalyst_info(ticker: str, expiry_date: date) -> dict:
    """
    Returns earnings proximity, FOMC proximity, and risk alerts.
    Called inline during every scan — no user action needed.
    """
    alerts = []
    earnings_date = None
    earnings_warning = False
    fomc_warning = False

    # ── Earnings date via yfinance ────────────────────────────────────────────
    try:
        tk = yf.Ticker(ticker)
        # Try calendar first (gives next confirmed earnings date)
        cal = tk.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
            earnings_date = raw.date() if hasattr(raw, "date") else raw
        # Fallback: earnings_dates (historical + estimate)
        if earnings_date is None:
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
                    earnings_date = min(future)
    except Exception:
        pass

    if earnings_date:
        days_away = (earnings_date - expiry_date).days
        if abs(days_away) <= 5:
            alerts.append(
                f"🚨 EARNINGS {earnings_date} is {abs(days_away)}d from expiry "
                f"— HIGH GAP RISK. Avoid short premium."
            )
            earnings_warning = True
        elif abs(days_away) <= 14:
            alerts.append(
                f"⚠️  Earnings {earnings_date} is {abs(days_away)}d away "
                f"— IV may stay elevated."
            )

    # ── FOMC proximity ────────────────────────────────────────────────────────
    today = date.today()
    future_fomc = [d for d in FOMC_DATES_2026 if d >= today]
    nearest_fomc = future_fomc[0] if future_fomc else None
    fomc_days_away = None
    if nearest_fomc:
        fomc_days_away = (nearest_fomc - expiry_date).days
        if abs(fomc_days_away) <= 2:
            alerts.append(
                f"🚨 FOMC decision {nearest_fomc} is {abs(fomc_days_away)}d from expiry "
                f"— volatility spike risk. Avoid short vol."
            )
            fomc_warning = True
        elif abs(fomc_days_away) <= 7:
            alerts.append(
                f"ℹ️  FOMC {nearest_fomc} is {abs(fomc_days_away)}d away "
                f"— market may price in uncertainty."
            )

    return dict(
        earnings_date=earnings_date,
        earnings_warning=earnings_warning,
        nearest_fomc=nearest_fomc,
        fomc_days_away=fomc_days_away,
        fomc_warning=fomc_warning,
        alerts=alerts,
        high_risk=earnings_warning or fomc_warning,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3b. STOCK INFO  (short interest + prior-day levels)
# ─────────────────────────────────────────────────────────────────────────────

def get_stock_info(ticker: str) -> dict:
    """PDH/PDL/PDC and short interest from yfinance — free tier."""
    tk = yf.Ticker(ticker)
    short_pct = pdh = pdl = pdc = None
    try:
        info = tk.info
        sp = info.get("shortPercentOfFloat")
        if sp is not None:
            short_pct = round(float(sp) * 100, 1)
    except Exception:
        pass
    try:
        hist = tk.history(period="5d", interval="1d")
        if len(hist) >= 2:
            prev = hist.iloc[-2]
            pdh = round(float(prev["High"]), 2)
            pdl = round(float(prev["Low"]), 2)
            pdc = round(float(prev["Close"]), 2)
    except Exception:
        pass
    return dict(short_pct=short_pct, pdh=pdh, pdl=pdl, pdc=pdc)


# ─────────────────────────────────────────────────────────────────────────────
# 3c. IBKR TWS API  (real-time Greeks + IV — requires ib_insync + TWS running)
# ─────────────────────────────────────────────────────────────────────────────

def get_greeks_ibkr(ticker: str, expiry_date: date, atm_strike: float,
                    port: int = 7497, client_id: int = 12) -> Optional[dict]:
    """
    Fetch real-time ATM call Greeks and IV from IBKR TWS/Gateway.
    Returns None if TWS is not running or ib_insync is not installed.
    port 7497 = paper trading TWS, 7496 = live TWS, 4002 = live IB Gateway.
    """
    if not HAS_IB:
        return None
    import time as _time
    ib = IB()
    ib_util.logToConsole(50)  # suppress ib_insync INFO logs (50=CRITICAL only)
    try:
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=8, readonly=True)
        # Use frozen data when market is closed (mode 2), fall back to delayed frozen (4)
        ib.reqMarketDataType(2)
        exp_str = expiry_date.strftime("%Y%m%d")
        call_contract = Option(ticker, exp_str, atm_strike, "C", "SMART", currency="USD")
        put_contract  = Option(ticker, exp_str, atm_strike, "P", "SMART", currency="USD")
        ib.qualifyContracts(call_contract, put_contract)

        # Stream market data — modelGreeks populate after a tick arrives
        call_ticker = ib.reqMktData(call_contract, genericTickList="106", snapshot=False)
        put_ticker  = ib.reqMktData(put_contract,  genericTickList="106", snapshot=False)

        # Poll up to 6 seconds for Greeks to arrive
        deadline = _time.time() + 6
        while _time.time() < deadline:
            ib.sleep(0.5)
            if (call_ticker.modelGreeks is not None and
                    call_ticker.modelGreeks.delta is not None):
                break

        result: dict = {}
        for t, prefix in [(call_ticker, "call"), (put_ticker, "put")]:
            mg = t.modelGreeks
            if mg is None:
                continue
            result[f"{prefix}_delta"] = round(float(mg.delta), 4)  if mg.delta      is not None else None
            result[f"{prefix}_gamma"] = round(float(mg.gamma), 4)  if mg.gamma      is not None else None
            result[f"{prefix}_theta"] = round(float(mg.theta), 4)  if mg.theta      is not None else None
            result[f"{prefix}_vega"]  = round(float(mg.vega),  4)  if mg.vega       is not None else None
            result[f"{prefix}_iv"]    = round(float(mg.impliedVol) * 100, 1) if mg.impliedVol is not None else None
            result[f"{prefix}_und_price"] = round(float(mg.undPrice), 2) if mg.undPrice is not None else None

        ib.cancelMktData(call_contract)
        ib.cancelMktData(put_contract)
        result["ibkr_connected"] = True
        result["ibkr_port"]      = port
        return result if len(result) > 2 else None  # >2 means we got actual Greeks
    except Exception as e:
        print(f"    ⚠  IBKR TWS not reachable (port {port}): {e}")
        return None
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def get_full_chain_ibkr(ticker: str, expiry_date: date,
                         port: int = 7497, client_id: int = 13) -> Optional[dict]:
    """
    Fetch the full options chain from IBKR including real Greeks for every strike.
    Much richer than yfinance. Returns None if TWS unavailable.
    """
    if not HAS_IB:
        return None
    ib = IB()
    ib_util.logToConsole(50)
    try:
        ib.connect("127.0.0.1", port, clientId=client_id, timeout=5, readonly=True)
        exp_str = expiry_date.strftime("%Y%m%d")

        # 1. Get valid strikes for this expiry
        params = ib.reqSecDefOptParams(ticker, "", "STK", ib.qualifyContracts(
            Stock(ticker, "SMART", "USD"))[0].conId)
        if not params:
            return None
        strikes = sorted(p.strikes for p in params if exp_str in p.expirations)[0]

        # 2. Fetch ATM ± 10 strikes to keep request count reasonable
        stock_ticker = ib.reqTickers(Stock(ticker, "SMART", "USD"))
        spot = stock_ticker[0].last or stock_ticker[0].close if stock_ticker else None
        if spot is None:
            return None

        atm_idx   = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        lo, hi    = max(0, atm_idx - 10), min(len(strikes), atm_idx + 11)
        sel_stk   = list(strikes)[lo:hi]

        contracts = [Option(ticker, exp_str, s, r, "SMART", currency="USD")
                     for s in sel_stk for r in ("C", "P")]
        ib.qualifyContracts(*contracts)
        tickers = ib.reqTickers(*contracts)

        calls_ibkr, puts_ibkr = [], []
        for t in tickers:
            mg  = t.modelGreeks
            bid = t.bid; ask = t.ask
            mid = ((bid + ask) / 2) if bid is not None and ask is not None else None
            row = dict(
                strike    = t.contract.strike,
                bid       = round(bid, 2) if bid is not None else None,
                ask       = round(ask, 2) if ask is not None else None,
                mid       = round(mid, 2) if mid is not None else None,
                volume    = t.volume or 0,
                openInterest = 0,  # IBKR doesn't stream OI in real-time; yfinance OI still used
                impliedVolatility = round(mg.impliedVol * 100, 1) if mg and mg.impliedVol else None,
                delta     = round(mg.delta, 4)  if mg and mg.delta  is not None else None,
                gamma     = round(mg.gamma, 4)  if mg and mg.gamma  is not None else None,
                theta     = round(mg.theta, 4)  if mg and mg.theta  is not None else None,
                vega      = round(mg.vega,  4)  if mg and mg.vega   is not None else None,
            )
            if t.contract.right == "C":
                calls_ibkr.append(row)
            else:
                puts_ibkr.append(row)

        return dict(calls=sorted(calls_ibkr, key=lambda r: r["strike"]),
                    puts=sorted(puts_ibkr,  key=lambda r: r["strike"]),
                    spot=round(spot, 2), ibkr_connected=True, ibkr_port=port)
    except Exception as e:
        print(f"    ⚠  IBKR full chain fetch failed: {e}")
        return None
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 4. TECHNICAL INDICATORS  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"].squeeze()
    if HAS_PANDAS_TA:
        df["EMA9"]  = ta.ema(close, length=9)
        df["EMA21"] = ta.ema(close, length=21)
        df["RSI"]   = ta.rsi(close, length=14)
        m = ta.macd(close)
        if m is not None and not m.empty:
            df["MACD"]      = m.iloc[:, 0]
            df["MACD_HIST"] = m.iloc[:, 1]
            df["MACD_SIG"]  = m.iloc[:, 2]
        else:
            _m, _s, _h = macd(close)
            df["MACD"], df["MACD_SIG"], df["MACD_HIST"] = _m, _s, _h
    else:
        df["EMA9"]      = ema(close, 9)
        df["EMA21"]     = ema(close, 21)
        df["RSI"]       = rsi(close, 14)
        _m, _s, _h      = macd(close)
        df["MACD"]      = _m
        df["MACD_SIG"]  = _s
        df["MACD_HIST"] = _h
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5. ANALYSIS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _confidence_score(last: float, ema9: float, ema21: float, rsi_val: float,
                       macd_hist: float, vwap: float,
                       chain: Optional[dict], macro: Optional[dict],
                       uw_flow: Optional[dict] = None,
                       news: Optional[dict] = None) -> tuple:
    """
    Returns (score_0_to_100, css_class, reasons_list).
    score > 60 = bullish, < 40 = bearish, else neutral.
    """
    bull = bear = 0
    reasons: list = []

    def _add(pts, cond, b_msg, bear_msg):
        nonlocal bull, bear
        if cond:
            bull += pts; reasons.append(f"+{pts} {b_msg}")
        else:
            bear += pts; reasons.append(f"-{pts} {bear_msg}")

    _add(2, last > ema9,  "Price > EMA9",  "Price < EMA9")
    _add(2, last > ema21, "Price > EMA21", "Price < EMA21")
    _add(2, rsi_val > 50, "RSI > 50",      "RSI < 50")
    _add(1, macd_hist > 0,"MACD positive", "MACD negative")
    if not math.isnan(vwap or float("nan")):
        _add(2, last > vwap, "Price > VWAP", "Price < VWAP")

    if chain:
        pcr = chain.get("pcr_vol", 1.0)
        if pcr < 0.7:
            bull += 3; reasons.append("+3 PCR bullish (call-heavy)")
        elif pcr > 1.3:
            bear += 3; reasons.append("-3 PCR bearish (put-heavy)")
        skew = chain.get("skew_25d") or 0
        if skew > 2:
            bull += 2; reasons.append("+2 Call skew (upside pricing)")
        elif skew < -2:
            bear += 2; reasons.append("-2 Put skew (crash protection)")
        ngex = chain.get("net_gex") or 0
        if ngex > 0:
            bull += 1; reasons.append("+1 Positive net GEX (pinning support)")
        elif ngex < 0:
            bear += 1; reasons.append("-1 Negative net GEX (acceleration risk)")

    if macro:
        spy_dir = (macro.get("SPY") or {}).get("direction")
        qqq_dir = (macro.get("QQQ") or {}).get("direction")
        if spy_dir == "up":   bull += 1; reasons.append("+1 SPY up")
        elif spy_dir == "down": bear += 1; reasons.append("-1 SPY down")
        if qqq_dir == "up":   bull += 1; reasons.append("+1 QQQ up")
        elif qqq_dir == "down": bear += 1; reasons.append("-1 QQQ down")
        tlt_cls = macro.get("tlt_cls")
        if tlt_cls == "bull": bull += 1; reasons.append("+1 TLT rising (rates falling)")
        elif tlt_cls == "bear": bear += 1; reasons.append("-1 TLT falling (rates rising)")
        dxy_cls = macro.get("dxy_cls")
        if dxy_cls == "bull": bull += 1; reasons.append("+1 Dollar falling")
        elif dxy_cls == "bear": bear += 1; reasons.append("-1 Dollar rising")
        sec_cls = macro.get("sector_cls")
        if sec_cls == "bull": bull += 2; reasons.append("+2 Sector ETF outperforming")
        elif sec_cls == "bear": bear += 2; reasons.append("-2 Sector ETF underperforming")

    # News sentiment
    if news and not news.get("error") and news.get("bull_count") is not None:
        net = news.get("net_score", 0)
        if net >= 3:
            bull += 3; reasons.append(f"+3 News strongly bullish ({news['bull_count']} bull headlines)")
        elif net >= 1:
            bull += 1; reasons.append(f"+1 News mildly bullish ({news['bull_count']} bull)")
        elif net <= -3:
            bear += 3; reasons.append(f"-3 News strongly bearish ({news['bear_count']} bear headlines)")
        elif net <= -1:
            bear += 1; reasons.append(f"-1 News mildly bearish ({news['bear_count']} bear)")

    # Sector rotation (5-day relative strength)
    if macro:
        rs = macro.get("sector_rotation_5d")
        rot_cls = macro.get("sector_rotation_cls")
        if rs is not None:
            if rot_cls == "bull":
                bull += 2; reasons.append(f"+2 Sector rotation IN (+{rs:.1f}% vs SPY 5d)")
            elif rot_cls == "bear":
                bear += 2; reasons.append(f"-2 Sector rotation OUT ({rs:.1f}% vs SPY 5d)")

    # Options flow direction (Unusual Whales) — strongest signal when available
    if uw_flow and not uw_flow.get("error"):
        net_pct = uw_flow.get("net_pct", 0)
        sw_bull = uw_flow.get("sweep_bull", 0)
        sw_bear = uw_flow.get("sweep_bear", 0)
        if net_pct >= 15:
            bull += 5; reasons.append(f"+5 UW flow strongly bullish ({net_pct:+.1f}% net call premium)")
        elif net_pct >= 5:
            bull += 3; reasons.append(f"+3 UW flow mildly bullish ({net_pct:+.1f}%)")
        elif net_pct <= -15:
            bear += 5; reasons.append(f"-5 UW flow strongly bearish ({net_pct:+.1f}% net put premium)")
        elif net_pct <= -5:
            bear += 3; reasons.append(f"-3 UW flow mildly bearish ({net_pct:+.1f}%)")
        if sw_bull > sw_bear + 2:
            bull += 2; reasons.append(f"+2 UW sweep buys dominant ({sw_bull} bull vs {sw_bear} bear sweeps)")
        elif sw_bear > sw_bull + 2:
            bear += 2; reasons.append(f"-2 UW sweep sells dominant ({sw_bear} bear vs {sw_bull} bull sweeps)")

    total = bull + bear
    score = round(bull / total * 100) if total > 0 else 50
    cls   = "bull" if score >= 60 else "bear" if score <= 40 else "neutral"
    return score, cls, reasons


def analyse(ticker: str, df: pd.DataFrame, prior_close: float,
            pm_high: float, pm_low: float,
            chain: Optional[dict] = None,
            catalyst: Optional[dict] = None,
            stock_info: Optional[dict] = None,
            df5: Optional[pd.DataFrame] = None,
            macro: Optional[dict] = None,
            sr_levels: Optional[list] = None,
            vpoc: Optional[dict] = None,
            backtest: Optional[dict] = None,
            level2: Optional[dict] = None,
            iv_momentum: Optional[dict] = None,
            gravity: Optional[dict] = None,
            vol_anomaly: Optional[dict] = None,
            position_size: Optional[dict] = None,
            uw_flow: Optional[dict] = None,
            news: Optional[dict] = None,
            trading_style: str = "spread") -> dict:
    close  = df["Close"].squeeze()
    last   = float(close.iloc[-1])
    day_open = float(df["Open"].iloc[0])
    day_high = float(df["High"].max())
    day_low  = float(df["Low"].min())
    day_range = day_high - day_low
    pct_change = (last - day_open) / day_open * 100

    ema9_val  = float(df["EMA9"].iloc[-1])
    ema21_val = float(df["EMA21"].iloc[-1])
    rsi_val   = float(df["RSI"].iloc[-1])
    macd_val  = float(df["MACD"].iloc[-1])
    macd_sig  = float(df["MACD_SIG"].iloc[-1])
    macd_hist = float(df["MACD_HIST"].iloc[-1])

    last_vol  = int(df["Volume"].iloc[-1])
    avg_vol   = int(df["Volume"].mean())
    vol_ratio = last_vol / avg_vol if avg_vol else 1.0
    vwap_val  = compute_vwap(df)

    # ── Bias logic ──────────────────────────────────────────────────────────
    bear_signals = 0
    bull_signals = 0
    if last < ema9_val:  bear_signals += 1
    else:                bull_signals += 1
    if last < ema21_val: bear_signals += 1
    else:                bull_signals += 1
    if pct_change < 0:   bear_signals += 1
    else:                bull_signals += 1
    if macd_hist < 0:    bear_signals += 1
    else:                bull_signals += 1
    if rsi_val < 50:     bear_signals += 1
    else:                bull_signals += 1

    if bear_signals >= 4:
        bias = "Strongly Bearish" if bear_signals == 5 else "Mildly Bearish"
        bias_color = "#f85149"
        bias_class = "bear"
    elif bull_signals >= 4:
        bias = "Strongly Bullish" if bull_signals == 5 else "Mildly Bullish"
        bias_color = "#3fb950"
        bias_class = "bull"
    else:
        bias = "Neutral / Indecisive"
        bias_color = "#d29922"
        bias_class = "neutral"

    # ── IV — use real ATM IV from chain, else estimate from range ────────────
    typical_daily_range_pct = 0.012
    today_range_pct = day_range / day_open
    iv_multiplier = today_range_pct / typical_daily_range_pct
    base_iv = 0.22
    est_iv_fallback = min(base_iv * iv_multiplier, 1.50)

    if chain and chain.get("atm_iv") is not None:
        est_iv = chain["atm_iv"] / 100          # real ATM IV as decimal
        est_ivr_low  = min(int(chain["atm_iv"] * 1.2), 95)
        est_ivr_high = min(est_ivr_low + 10, 99)
        iv_source = "Live (yfinance ATM IV)"
    else:
        est_iv = est_iv_fallback
        est_ivr_low  = min(int(30 * iv_multiplier), 95)
        est_ivr_high = min(est_ivr_low + 15, 99)
        iv_source = "Estimated (range proxy)"

    iv_regime = ("Compressed" if est_ivr_high < 35
                 else "Moderate" if est_ivr_high < 55
                 else "Elevated" if est_ivr_high < 75
                 else "Very High")
    iv_color = ("#3fb950" if iv_regime == "Compressed"
                else "#d29922" if iv_regime == "Moderate"
                else "#f85149")

    # ── Key levels ───────────────────────────────────────────────────────────
    round_step = 1.0 if last >= 50 else 0.5
    nearest_round = round(last / round_step) * round_step

    # Max pain — use real value from chain, else estimate
    if chain and chain.get("max_pain") is not None:
        max_pain_est = float(chain["max_pain"])
    elif not math.isnan(prior_close):
        max_pain_est = round((prior_close + day_open) / 2 / round_step) * round_step
    else:
        max_pain_est = round((day_high + day_low) / 2 / round_step) * round_step

    # ── Strike grid for options chain ───────────────────────────────────────
    def strike_grid(center, step, n=4):
        base = round(center / step) * step
        return sorted({round((base + i * step), 2) for i in range(-n, n + 1)})

    strikes = strike_grid(last, round_step, n=5)

    # ── ATM estimates used by both strategy modes ─────────────────────────────
    atm_call_est  = (chain.get("atm_call_mid")  if chain else None) or round(day_range * 0.12, 2)
    atm_put_est   = (chain.get("atm_put_mid")   if chain else None) or round(day_range * 0.12, 2)
    atm_delta_val = (chain.get("atm_delta")     if chain else None) or 0.50
    atm_iv_val    = (chain.get("atm_iv")        if chain else None) or (est_iv * 100)

    call_spread_pct = chain.get("atm_call_spread_pct") if chain else None
    put_spread_pct  = chain.get("atm_put_spread_pct")  if chain else None
    liq_warn = ""
    if call_spread_pct and call_spread_pct > 15:
        liq_warn = f"⚠ Wide bid-ask ({call_spread_pct:.0f}%) — costs you on entry AND exit, trade carefully"

    if trading_style == "daytrader":
        # ── Day Trading: Single-Leg Call or Put Buy ───────────────────────────
        if bias_class == "bull":
            strat_a_name      = "Long Call (Day Trade)"
            strat_a_tag       = "BUY CALL · Directional Bullish"
            strat_a_tag_class = "bull-tag"
            strike_dt  = nearest_round
            premium    = atm_call_est
            breakeven  = round(strike_dt + premium, 2)
            target_stock   = round(last + min(day_range * 0.5, est_iv * last / math.sqrt(252) * 2), 2)
            tgt_premium_lo = round(premium * 1.5, 2)
            tgt_premium_hi = round(premium * 2.0, 2)
            stop_stock     = round(ema9_val - round_step * 0.5, 2)
            stop_premium   = round(premium * 0.5, 2)
            max_loss_a     = premium
            strat_a_rows   = [
                ("Action",        f"BUY {strike_dt:.2f} Call"),
                ("Expiry",        chain["expiry_used"] if chain else "same day"),
                ("Est. Premium",  f"~${premium:.2f}/contract = ${premium*100:.0f} total"),
                ("Delta",         f"~{atm_delta_val:.2f} (moves ${atm_delta_val:.2f} per $1 in {ticker})"),
                ("Breakeven",     f"${breakeven:.2f} by expiry"),
                ("Profit Target", f"Sell at ${tgt_premium_lo:.2f}–${tgt_premium_hi:.2f} (50–100% gain)"),
                ("Stop Loss",     f"Sell at ${stop_premium:.2f} (−50% on premium)"),
                ("Max Loss",      f"${premium:.2f}/contract if expires worthless"),
            ]
            if liq_warn: strat_a_rows.append(("Liquidity", liq_warn))
            entry_a    = f"1-min candle closes above ${day_high:.2f} (HOD breakout) OR bounce off ${ema9_val:.2f} EMA9"
            stop_a     = f"Stock drops below ${stop_stock:.2f} OR premium drops to ${stop_premium:.2f} — exit immediately"
            target_a   = f"Stock reaches ${target_stock:.2f} → sell call at ${tgt_premium_lo:.2f}–${tgt_premium_hi:.2f}"
            max_risk_a = f"~${round(premium * 100):.0f}/contract"
            inval_a    = f"Price drops below EMA21 (${ema21_val:.2f}) — thesis broken"

        elif bias_class == "bear":
            strat_a_name      = "Long Put (Day Trade)"
            strat_a_tag       = "BUY PUT · Directional Bearish"
            strat_a_tag_class = "primary"
            strike_dt  = nearest_round
            premium    = atm_put_est
            breakeven  = round(strike_dt - premium, 2)
            target_stock   = round(last - min(day_range * 0.5, est_iv * last / math.sqrt(252) * 2), 2)
            tgt_premium_lo = round(premium * 1.5, 2)
            tgt_premium_hi = round(premium * 2.0, 2)
            stop_stock     = round(ema9_val + round_step * 0.5, 2)
            stop_premium   = round(premium * 0.5, 2)
            max_loss_a     = premium
            strat_a_rows   = [
                ("Action",        f"BUY {strike_dt:.2f} Put"),
                ("Expiry",        chain["expiry_used"] if chain else "same day"),
                ("Est. Premium",  f"~${premium:.2f}/contract = ${premium*100:.0f} total"),
                ("Delta",         f"~{-atm_delta_val:.2f} (moves ${atm_delta_val:.2f} per $1 drop in {ticker})"),
                ("Breakeven",     f"${breakeven:.2f} by expiry"),
                ("Profit Target", f"Sell at ${tgt_premium_lo:.2f}–${tgt_premium_hi:.2f} (50–100% gain)"),
                ("Stop Loss",     f"Sell at ${stop_premium:.2f} (−50% on premium)"),
                ("Max Loss",      f"${premium:.2f}/contract if expires worthless"),
            ]
            if liq_warn: strat_a_rows.append(("Liquidity", liq_warn))
            entry_a    = f"1-min candle closes below ${day_low:.2f} (LOD breakdown) OR rejection at ${ema9_val:.2f} EMA9"
            stop_a     = f"Stock reclaims ${stop_stock:.2f} OR premium drops to ${stop_premium:.2f} — exit immediately"
            target_a   = f"Stock reaches ${target_stock:.2f} → sell put at ${tgt_premium_lo:.2f}–${tgt_premium_hi:.2f}"
            max_risk_a = f"~${round(premium * 100):.0f}/contract"
            inval_a    = f"Price reclaims EMA9 (${ema9_val:.2f}) — bullish reversal, exit"

        else:  # neutral
            strat_a_name      = "Long Call (Day Trade) — Wait for Breakout"
            strat_a_tag       = "BUY CALL · Breakout Confirmation Required"
            strat_a_tag_class = "neutral-tag"
            strike_dt      = nearest_round + round_step
            premium        = round(atm_call_est * 0.70, 2)
            breakeven      = round(strike_dt + premium, 2)
            tgt_premium_lo = round(premium * 1.5, 2)
            tgt_premium_hi = round(premium * 2.5, 2)
            stop_premium   = round(premium * 0.5, 2)
            max_loss_a     = premium
            strat_a_rows   = [
                ("Action",        f"BUY {strike_dt:.2f} Call (on confirmed breakout only)"),
                ("Expiry",        chain["expiry_used"] if chain else "same day"),
                ("Est. Premium",  f"~${premium:.2f}/contract = ${premium*100:.0f} total"),
                ("Delta",         f"~0.35–0.40 (OTM, high gamma potential)"),
                ("Breakeven",     f"${breakeven:.2f} by expiry"),
                ("Profit Target", f"Sell at ${tgt_premium_lo:.2f}–${tgt_premium_hi:.2f} (50–150% gain)"),
                ("Stop Loss",     f"Sell at ${stop_premium:.2f} (−50% on premium)"),
                ("Max Loss",      f"${premium:.2f}/contract if no follow-through"),
            ]
            if liq_warn: strat_a_rows.append(("Liquidity", liq_warn))
            entry_a    = (f"DO NOT enter yet — market is neutral/choppy. "
                          f"Enter call ONLY on 1-min close above ${day_high:.2f} with volume. "
                          f"Enter put ONLY on 1-min close below ${day_low:.2f} with volume.")
            stop_a     = f"If premium drops ${stop_premium:.2f} from entry (−50%) — cut immediately, no averaging down"
            target_a   = "First target: +50% on premium. Trail stop to breakeven after +75%."
            max_risk_a = f"~${round(premium * 100):.0f}/contract"
            inval_a    = "No clean breakout — do not force a trade in choppy conditions"

        # Strategy B for day trader: opposite-direction single-leg
        ic_sell_call = nearest_round + round_step * 2
        ic_buy_call  = nearest_round + round_step * 3
        ic_sell_put  = nearest_round - round_step * 2
        ic_buy_put   = nearest_round - round_step * 3
        ic_credit_lo = round(atm_put_est * 0.6, 2)
        ic_credit_hi = round(atm_put_est * 0.8, 2)
        ic_max_loss  = round(atm_put_est, 2)

    else:
        # ── Spread / Multi-Leg Strategy (default) ────────────────────────────
        if bias_class in ("bear", "neutral") and est_ivr_high >= 55:
            strat_a_name      = "Bear Call Credit Spread"
            strat_a_tag       = "PRIMARY · High IV Premium Sell"
            strat_a_tag_class = "primary"
            sell_call  = nearest_round + round_step
            buy_call   = sell_call + 2 * round_step
            credit_lo  = round(day_range * 0.12, 2)
            credit_hi  = round(day_range * 0.18, 2)
            max_loss_a = round(buy_call - sell_call - credit_hi, 2)
            strat_a_rows = [
                ("Sell", f"${sell_call:.2f} Call (0DTE)"),
                ("Buy",  f"${buy_call:.2f} Call (0DTE)"),
                ("Net Credit (est.)", f"${credit_lo:.2f} – ${credit_hi:.2f}"),
                ("Breakeven", f"${sell_call + credit_hi:.2f}"),
                ("Max Profit", f"Full credit if {ticker} stays ≤ ${sell_call:.2f}"),
                ("Max Loss",   f"${max_loss_a:.2f} / contract"),
            ]
            entry_a    = f"Enter now or on bounce to ${sell_call:.2f}–${sell_call + round_step:.2f}"
            stop_a     = f"Exit if price closes above ${sell_call + credit_hi + 0.20:.2f}"
            target_a   = "75% of max credit, or let expire worthless"
            max_risk_a = f"~${round(max_loss_a * 100):.0f}/contract"
            inval_a    = f"{ticker} closes above ${sell_call + credit_hi:.2f}"
        elif bias_class == "bear":
            strat_a_name      = "Bear Put Debit Spread"
            strat_a_tag       = "PRIMARY · Directional Bearish"
            strat_a_tag_class = "primary"
            buy_put    = nearest_round
            sell_put   = nearest_round - 2 * round_step
            debit_lo   = round(day_range * 0.10, 2)
            debit_hi   = round(day_range * 0.14, 2)
            max_profit_a = round(buy_put - sell_put - debit_hi, 2)
            max_loss_a   = debit_hi
            strat_a_rows = [
                ("Buy",  f"${buy_put:.2f} Put (0DTE)"),
                ("Sell", f"${sell_put:.2f} Put (0DTE)"),
                ("Net Debit (est.)", f"${debit_lo:.2f} – ${debit_hi:.2f}"),
                ("Breakeven", f"${buy_put - debit_hi:.2f}"),
                ("Max Profit", f"${max_profit_a:.2f} / contract"),
                ("Max Loss",   f"Debit paid (${debit_hi:.2f})"),
            ]
            entry_a    = f"1-min close below ${day_low:.2f} (LOD breakdown)"
            stop_a     = f"Exit if price reclaims ${ema9_val:.2f} (EMA 9)"
            target_a   = f"70% of max profit (~${sell_put + (buy_put - sell_put) * 0.3:.2f} on stock)"
            max_risk_a = f"~${round(debit_hi * 100):.0f}/contract"
            inval_a    = f"{ticker} reclaims ${ema9_val:.2f}+"
        else:
            strat_a_name      = "Bull Call Debit Spread"
            strat_a_tag       = "PRIMARY · Directional Bullish"
            strat_a_tag_class = "bull-tag"
            buy_call   = nearest_round
            sell_call  = nearest_round + 2 * round_step
            debit_lo   = round(day_range * 0.10, 2)
            debit_hi   = round(day_range * 0.14, 2)
            max_profit_a = round(sell_call - buy_call - debit_hi, 2)
            max_loss_a   = debit_hi
            strat_a_rows = [
                ("Buy",  f"${buy_call:.2f} Call (0DTE)"),
                ("Sell", f"${sell_call:.2f} Call (0DTE)"),
                ("Net Debit (est.)", f"${debit_lo:.2f} – ${debit_hi:.2f}"),
                ("Breakeven", f"${buy_call + debit_hi:.2f}"),
                ("Max Profit", f"${max_profit_a:.2f} / contract"),
                ("Max Loss",   f"Debit paid (${debit_hi:.2f})"),
            ]
            entry_a    = f"1-min close above ${day_high:.2f} (HOD breakout)"
            stop_a     = f"Exit if price drops below ${ema9_val:.2f} (EMA 9)"
            target_a   = "70% of max profit"
            max_risk_a = f"~${round(debit_hi * 100):.0f}/contract"
            inval_a    = f"{ticker} drops below ${ema21_val:.2f}"

        # Strategy B: Iron Condor
        ic_sell_call = round((last + day_range * 0.35) / round_step) * round_step
        ic_buy_call  = ic_sell_call + round_step
        ic_sell_put  = round((last - day_range * 0.35) / round_step) * round_step
        ic_buy_put   = ic_sell_put - round_step
        ic_credit_lo = round(day_range * 0.08, 2)
        ic_credit_hi = round(day_range * 0.12, 2)
        ic_max_loss  = round(round_step - ic_credit_hi, 2)

    rsi_label = ("Oversold" if rsi_val < 30
                 else "Near Oversold" if rsi_val < 35
                 else "Bearish" if rsi_val < 50
                 else "Neutral" if rsi_val < 55
                 else "Bullish" if rsi_val < 70
                 else "Overbought")
    rsi_class = ("bear" if rsi_val < 50 else "bull")

    macd_label = "Bearish Cross" if macd_hist < 0 else "Bullish Cross"
    macd_class = "bear" if macd_hist < 0 else "bull"

    ema_rel = "below both EMAs" if last < min(ema9_val, ema21_val) else \
              "above both EMAs" if last > max(ema9_val, ema21_val) else \
              "between EMAs"

    return dict(
        ticker=ticker.upper(),
        trading_date=str(date.today()),
        last=last, day_open=day_open, day_high=day_high, day_low=day_low,
        day_range=day_range, pct_change=pct_change,
        prior_close=prior_close, pm_high=pm_high, pm_low=pm_low,
        ema9=ema9_val, ema21=ema21_val,
        rsi=rsi_val, rsi_label=rsi_label, rsi_class=rsi_class,
        macd=macd_val, macd_sig=macd_sig, macd_hist=macd_hist,
        macd_label=macd_label, macd_class=macd_class,
        last_vol=last_vol, avg_vol=avg_vol, vol_ratio=vol_ratio,
        bias=bias, bias_color=bias_color, bias_class=bias_class,
        ema_rel=ema_rel,
        est_iv=est_iv, est_ivr_low=est_ivr_low, est_ivr_high=est_ivr_high,
        iv_regime=iv_regime, iv_color=iv_color, iv_source=iv_source,
        max_pain_est=max_pain_est,
        strikes=strikes,
        ic_sell_call=ic_sell_call, ic_buy_call=ic_buy_call,
        ic_sell_put=ic_sell_put, ic_buy_put=ic_buy_put,
        ic_credit_lo=ic_credit_lo, ic_credit_hi=ic_credit_hi,
        ic_max_loss=ic_max_loss,
        strat_a_name=strat_a_name, strat_a_tag=strat_a_tag,
        strat_a_tag_class=strat_a_tag_class, strat_a_rows=strat_a_rows,
        entry_a=entry_a, stop_a=stop_a, target_a=target_a,
        max_risk_a=max_risk_a, inval_a=inval_a,
        round_step=round_step,
        vwap=vwap_val,
        # Confidence score
        **dict(zip(("conf_score","conf_cls","conf_reasons"),
                   _confidence_score(last, ema9_val, ema21_val, rsi_val,
                                     macd_hist, vwap_val, chain, macro, uw_flow, news))),
        # Real options chain data (None if unavailable)
        chain=chain,
        # Catalyst calendar (earnings + FOMC)
        catalyst=catalyst,
        # Stock info (PDH/PDL/PDC + short interest)
        stock_info=stock_info,
        # 5m chart data for entry trigger
        df5=df5,
        # Macro context (SPY/QQQ/VIX/TLT/DXY/sector ETF)
        macro=macro,
        # Horizontal S/R levels
        sr_levels=sr_levels or [],
        # Volume profile (VPOC/VAH/VAL)
        vpoc=vpoc or {},
        # Backtest results
        backtest=backtest or {},
        # Level 2 market depth
        level2=level2,
        # IV momentum (vs yesterday)
        iv_momentum=iv_momentum or {},
        # Max pain gravity score
        gravity=gravity or {},
        # Volume anomaly
        vol_anomaly=vol_anomaly or {},
        # Position sizing
        position_size=position_size or {},
        # Unusual Whales options flow
        uw_flow=uw_flow or {},
        # News sentiment
        news=news or {},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. HTML RENDERER
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0d1117; color: #c9d1d9;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 15px; line-height: 1.7; padding: 32px 16px;
}
.container { max-width: 980px; margin: 0 auto; }
header {
  background: linear-gradient(135deg,#161b22,#1f2937);
  border:1px solid #30363d; border-radius:12px; padding:28px 32px; margin-bottom:32px;
}
header h1 { font-size:26px; font-weight:700; color:#58a6ff; margin-bottom:6px; }
header .subtitle { color:#8b949e; font-size:14px; }
.badge {
  display:inline-block; background:#21262d; border:1px solid #30363d;
  border-radius:20px; padding:3px 12px; font-size:12px; color:#8b949e;
  margin-top:10px; margin-right:8px;
}
.badge.bear { border-color:#f85149; color:#f85149; }
.badge.bull { border-color:#3fb950; color:#3fb950; }
.badge.neutral { border-color:#d29922; color:#d29922; }
.section {
  background:#161b22; border:1px solid #30363d; border-radius:10px;
  padding:24px 28px; margin-bottom:24px;
}
.section h2 {
  font-size:17px; font-weight:600; color:#e6edf3; margin-bottom:16px;
  padding-bottom:10px; border-bottom:1px solid #21262d;
  display:flex; align-items:center; gap:10px;
}
table { width:100%; border-collapse:collapse; font-size:14px; margin-top:4px; }
th {
  background:#21262d; color:#8b949e; text-align:left;
  padding:9px 12px; font-weight:600; font-size:12px;
  text-transform:uppercase; letter-spacing:.04em;
}
td { padding:9px 12px; border-bottom:1px solid #21262d; color:#c9d1d9; }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#1c2128; }
td strong { color:#e6edf3; }
.price-grid {
  display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:14px; margin-bottom:18px;
}
.price-card {
  background:#21262d; border:1px solid #30363d; border-radius:8px; padding:14px 16px;
}
.price-card .label { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:.05em; }
.price-card .value { font-size:22px; font-weight:700; color:#e6edf3; margin-top:4px; }
.price-card .value.red { color:#f85149; }
.price-card .value.green { color:#3fb950; }
.price-card .value.blue { color:#58a6ff; }
.price-card .sub { font-size:12px; color:#8b949e; margin-top:2px; }
.bias-box {
  background:#1c2128; border-left:4px solid #f85149; border-radius:0 8px 8px 0;
  padding:14px 16px; margin-top:16px; font-size:14px;
}
.bias-box.neutral { border-left-color:#d29922; }
.bias-box.bull { border-left-color:#3fb950; }
.strategy-card {
  background:#1c2128; border:1px solid #30363d; border-radius:10px;
  padding:20px 22px; margin-bottom:18px;
}
.strategy-card h3 { font-size:15px; font-weight:700; color:#58a6ff; margin-bottom:4px; }
.tag {
  display:inline-block; background:#21262d; border:1px solid #30363d;
  border-radius:4px; padding:2px 8px; font-size:11px; color:#8b949e; margin-bottom:14px;
}
.tag.primary { border-color:#f85149; color:#f85149; }
.tag.bull-tag { border-color:#3fb950; color:#3fb950; }
.risk-reward { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-top:14px; }
.rr-box { background:#21262d; border-radius:6px; padding:12px; text-align:center; }
.rr-box .rr-label { font-size:11px; color:#8b949e; text-transform:uppercase; }
.rr-box .rr-val { font-size:18px; font-weight:700; margin-top:4px; }
.rr-box .rr-val.loss { color:#f85149; }
.rr-box .rr-val.gain { color:#3fb950; }
.rr-box .rr-val.ratio { color:#d2a679; }
.note {
  background:#1c2128; border:1px solid #d29922; border-radius:8px;
  padding:14px 16px; font-size:13px; color:#c9d1d9; margin-top:14px;
}
.note strong { color:#d29922; }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
.pill {
  display:inline-block; padding:2px 10px; border-radius:12px;
  font-size:12px; font-weight:600;
}
.pill.bear { background:rgba(248,81,73,.15); color:#f85149; border:1px solid rgba(248,81,73,.3); }
.pill.bull { background:rgba(63,185,80,.15); color:#3fb950; border:1px solid rgba(63,185,80,.3); }
.pill.neutral { background:rgba(210,153,34,.15); color:#d29922; border:1px solid rgba(210,153,34,.3); }
.summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }
.summary-item { background:#21262d; border-radius:8px; padding:14px 16px; }
.summary-item .s-label { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:.05em; }
.summary-item .s-value { font-size:15px; font-weight:600; color:#e6edf3; margin-top:4px; }
.disclaimer {
  background:#161b22; border:1px solid #30363d; border-radius:8px;
  padding:16px 20px; font-size:12px; color:#6e7681; margin-top:32px; text-align:center;
}
p { margin-bottom:10px; font-size:14px; color:#c9d1d9; }
@media(max-width:640px){.two-col,.risk-reward{grid-template-columns:1fr;}}
"""


def fmt(val, decimals=2, prefix="$"):
    if math.isnan(val):
        return "N/A"
    return f"{prefix}{val:.{decimals}f}" if prefix else f"{val:.{decimals}f}"


def pill(label, css_class):
    return f'<span class="pill {css_class}">{label}</span>'


def _build_iv_momentum_section(d: dict) -> str:
    ivm = d.get("iv_momentum") or {}
    if not ivm.get("iv_change"):
        return ""
    chg   = ivm["iv_change"]
    color = "#f85149" if ivm.get("iv_mom_cls") == "bear" else "#3fb950" if ivm.get("iv_mom_cls") == "bull" else "#d29922"
    c     = d.get("chain") or {}
    today_iv = c.get("atm_iv", "—")
    return f"""
  <div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;
    padding:12px 18px;margin-bottom:18px;display:flex;align-items:center;gap:24px;">
    <div style="text-align:center;min-width:80px">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase">IV Yesterday</div>
      <div style="font-size:18px;font-weight:700;color:#e6edf3">{ivm.get('iv_yesterday','—')}%</div>
    </div>
    <div style="font-size:24px;color:{color}">{"▲" if chg > 0 else "▼"}</div>
    <div style="text-align:center;min-width:80px">
      <div style="font-size:11px;color:#8b949e;text-transform:uppercase">IV Today</div>
      <div style="font-size:18px;font-weight:700;color:{color}">{today_iv}%</div>
    </div>
    <div style="flex:1;padding-left:16px;border-left:1px solid #30363d;">
      <div style="font-weight:600;color:{color}">{chg:+.1f}pt change</div>
      <div style="font-size:13px;color:#c9d1d9;margin-top:2px">{ivm.get('iv_momentum','')}</div>
    </div>
  </div>"""


def _build_dap_section(d: dict) -> str:
    c   = d.get("chain") or {}
    dap = c.get("dap") or []
    if not dap:
        return ""
    spot = c.get("spot") or d.get("last", 0)

    rows = ""
    for r in dap:
        net  = r["net_dap"]
        color = "#3fb950" if net > 0 else "#f85149" if net < 0 else "#8b949e"
        atm  = " ◀ ATM" if abs(r["strike"] - spot) < 2.5 else ""
        rows += (f'<tr>'
                 f'<td><strong>${r["strike"]:.2f}</strong>{atm}</td>'
                 f'<td style="color:#3fb950">{r["call_dap"]:+,.0f}</td>'
                 f'<td style="color:#f85149">{r["put_dap"]:+,.0f}</td>'
                 f'<td style="color:{color};font-weight:600">{net:+,.0f}</td>'
                 f'<td style="color:#8b949e">{r["dist_pct"]:+.2f}%</td></tr>')

    # Net DAP interpretation
    total_net = sum(r["net_dap"] for r in dap)
    t_color   = "#f85149" if total_net > 0 else "#3fb950"
    t_signal  = ("Dealers net long delta → they sell rallies (headwind above)" if total_net > 0
                 else "Dealers net short delta → they buy dips (support below)")
    return f"""
  <div class="section">
    <h2><span>Δ</span> Delta-Adjusted OI (DAP) — Dealer Directional Exposure</h2>
    <div style="background:#1c2128;border-left:4px solid {t_color};border-radius:0 8px 8px 0;
      padding:10px 14px;margin-bottom:14px;font-size:13px;">
      <strong>Net DAP {total_net:+,.0f}</strong> — {t_signal}
    </div>
    <table>
      <tr><th>Strike</th><th>Call DAP (+)</th><th>Put DAP (−)</th><th>Net DAP</th><th>Dist</th></tr>
      {rows}
    </table>
    <div class="note" style="margin-top:10px">
      <strong>How to read DAP:</strong> Positive net = dealers long delta here → they sell into price rises above this strike (acts as resistance).
      Negative net = dealers short delta → they buy when price dips below (acts as support).
      The strike with the largest absolute net DAP is where dealer hedging flow is strongest.
    </div>
  </div>"""


def _build_gravity_section(d: dict) -> str:
    g = d.get("gravity") or {}
    c = d.get("chain") or {}
    if not g or not c.get("max_pain"):
        return ""
    score   = g.get("gravity", 0)
    color   = "#f85149" if score >= 70 else "#d29922" if score >= 40 else "#8b949e"
    bar_w   = min(score, 100)
    mp      = c.get("max_pain")
    spot    = c.get("spot") or d.get("last", 0)
    dist    = g.get("dist_pct", 0)
    exp_str = c.get("expiry_used", "")
    return f"""
  <div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;
    padding:14px 18px;margin-bottom:18px;">
    <div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">
      🎯 MAX PAIN GRAVITY — ${mp:.2f} target by {exp_str}
    </div>
    <div style="display:flex;align-items:center;gap:16px">
      <div style="font-size:36px;font-weight:800;color:{color};min-width:60px">{score}</div>
      <div style="flex:1">
        <div style="background:#21262d;border-radius:6px;height:12px;margin-bottom:8px;">
          <div style="background:{color};height:100%;width:{bar_w}%;border-radius:6px;opacity:.85"></div>
        </div>
        <div style="font-size:13px;color:#c9d1d9">{g.get('label','')}</div>
        <div style="font-size:12px;color:#8b949e;margin-top:4px">
          Distance: {dist:.2f}% ({abs(spot - mp):.2f} pts) &nbsp;|&nbsp;
          {"Strong pin expected — size accordingly" if score >= 70
           else "Moderate pull — monitor into close" if score >= 40
           else "Gravity weak — price free to move"}
        </div>
      </div>
    </div>
  </div>"""


def _build_position_size_section(d: dict) -> str:
    ps = d.get("position_size") or {}
    if not ps:
        return ""
    acct  = ps.get("account_size", 25000)
    risk  = ps.get("risk_pct", 1.0)
    contr = ps.get("max_contracts", 1)
    total_risk  = ps.get("total_risk", 0)
    total_cost  = ps.get("total_cost", 0)
    cost_pct    = ps.get("cost_pct_account", 0)
    max_loss_c  = ps.get("max_loss_per_contract", 0)
    return f"""
  <div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;
    padding:14px 18px;margin-bottom:18px;">
    <div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:12px;">
      💰 POSITION SIZING — ${acct:,.0f} account · {risk}% max risk per trade
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
      <div style="text-align:center">
        <div style="font-size:11px;color:#8b949e;text-transform:uppercase">Max Contracts</div>
        <div style="font-size:28px;font-weight:800;color:#58a6ff">{contr}</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:11px;color:#8b949e;text-transform:uppercase">Max Risk</div>
        <div style="font-size:22px;font-weight:700;color:#f85149">${total_risk:,.0f}</div>
        <div style="font-size:11px;color:#8b949e">{risk}% of account</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:11px;color:#8b949e;text-transform:uppercase">Capital Deployed</div>
        <div style="font-size:22px;font-weight:700;color:#d29922">${total_cost:,.0f}</div>
        <div style="font-size:11px;color:#8b949e">{cost_pct:.1f}% of account</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:11px;color:#8b949e;text-transform:uppercase">Loss/Contract</div>
        <div style="font-size:22px;font-weight:700;color:#e6edf3">${max_loss_c * 100:,.0f}</div>
      </div>
    </div>
    <div style="font-size:12px;color:#6e7681;margin-top:10px">
      ⚠ Sizing uses 1% rule on estimated spread debit. Adjust --account and --risk flags to match your setup.
    </div>
  </div>"""


def _build_vol_anomaly_inline(d: dict) -> str:
    va = d.get("vol_anomaly") or {}
    if not va or va.get("vs_session", 1) < 1.5:
        return ""
    color = "#f85149" if va.get("cls") == "bear" else "#d29922"
    return (f'<div style="background:#1c2128;border-left:3px solid {color};'
            f'padding:8px 14px;margin-bottom:10px;font-size:13px;border-radius:0 6px 6px 0">'
            f'📊 {va.get("signal","")} &nbsp;|&nbsp; '
            f'Current: {va.get("current_vol",0):,} · Session avg: {va.get("session_avg",0):,}'
            f'</div>')


def _build_vpoc_sr_section(d: dict) -> str:
    vpoc  = d.get("vpoc") or {}
    sr    = d.get("sr_levels") or []
    spot  = d.get("last", 0)
    if not vpoc and not sr:
        return ""

    vpoc_html = ""
    if vpoc:
        v, vah, val = vpoc.get("vpoc"), vpoc.get("vah"), vpoc.get("val")
        above_vpoc = "✅ Above VPOC — buyers in control" if spot >= (v or 0) else "❌ Below VPOC — sellers in control"
        vpoc_html = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px;">
      <div class="price-card">
        <div class="label">VPOC (Point of Control)</div>
        <div class="value blue">${v:.2f}</div>
        <div class="sub">Highest volume price</div>
      </div>
      <div class="price-card">
        <div class="label">VAH (Value Area High)</div>
        <div class="value green">${vah:.2f}</div>
        <div class="sub">Top of 70% vol zone</div>
      </div>
      <div class="price-card">
        <div class="label">VAL (Value Area Low)</div>
        <div class="value red">${val:.2f}</div>
        <div class="sub">Bottom of 70% vol zone</div>
      </div>
      <div class="price-card">
        <div class="label">Current vs VPOC</div>
        <div class="value" style="font-size:13px;color:{"#3fb950" if spot >= (v or 0) else "#f85149"}">{above_vpoc}</div>
      </div>
    </div>"""

    sr_rows = ""
    for lvl in sr[:8]:
        dist_str = f"{lvl['dist_pct']:+.2f}%"
        color = "#f85149" if lvl["type"] == "resistance" else "#3fb950"
        strength_color = "#f85149" if lvl["strength"] == "Strong" else "#d29922" if lvl["strength"] == "Moderate" else "#8b949e"
        sr_rows += (f'<tr>'
                    f'<td><strong style="color:{color}">${lvl["price"]:.2f}</strong></td>'
                    f'<td>{pill(lvl["type"].title(), lvl["strength_cls"])}</td>'
                    f'<td style="color:{strength_color}">{lvl["strength"]} ({lvl["touches"]}× tested)</td>'
                    f'<td>{dist_str} from price</td></tr>')

    sr_html = f"""
    <h3 style="font-size:13px;color:#8b949e;margin:16px 0 8px;">HORIZONTAL S/R — 60-Day History</h3>
    <table>
      <tr><th>Level</th><th>Type</th><th>Strength</th><th>Distance</th></tr>
      {sr_rows}
    </table>""" if sr_rows else ""

    return f"""
  <div class="section">
    <h2><span>📊</span> 8e. Volume Profile &amp; Horizontal S/R</h2>
    {vpoc_html}
    {sr_html}
    <div class="note" style="margin-top:12px">
      <strong>VPOC</strong> = highest volume price today — strongest magnet for price. Price above VAH = buyers control value area.
      Price below VAL = sellers control. <strong>Horizontal S/R</strong> levels detected from 60-day daily highs/lows —
      Strong (3+ touches) levels are the most reliable.
    </div>
  </div>"""


def _build_backtest_section(d: dict) -> str:
    bt = d.get("backtest") or {}
    if not bt or not bt.get("bull"):
        return ""

    def _row(label, stats, direction):
        if not stats:
            return ""
        wr_color = "#3fb950" if stats["win_rate"] >= 55 else "#f85149" if stats["win_rate"] < 45 else "#d29922"
        ret_color = "#3fb950" if stats["avg_return"] > 0 else "#f85149"
        return (f'<tr><td>{label}</td>'
                f'<td style="color:{wr_color}"><strong>{stats["win_rate"]}%</strong></td>'
                f'<td>{stats["count"]}</td>'
                f'<td style="color:{ret_color}">{stats["avg_return"]:+.3f}%</td>'
                f'<td style="color:#3fb950">{stats["avg_win"]:+.3f}%</td>'
                f'<td style="color:#f85149">{stats["avg_loss"]:+.3f}%</td></tr>')

    rows = (_row("🟢 Bull Signal (score ≥60)", bt.get("bull"), "bull") +
            _row("🔴 Bear Signal (score ≤40)", bt.get("bear"), "bear") +
            _row("⚪ Neutral (40–60)", bt.get("neutral"), "neutral"))

    bull_wr = (bt.get("bull") or {}).get("win_rate", 50)
    bear_wr = (bt.get("bear") or {}).get("win_rate", 50)
    calibration = ("✅ Signals are calibrated" if bull_wr >= 55 and bear_wr >= 55
                   else "⚠️ Signals need improvement — treat with caution" if bull_wr < 50 or bear_wr < 50
                   else "ℹ️ Moderate signal accuracy")

    return f"""
  <div class="section">
    <h2><span>📈</span> 8f. Signal Backtest — {bt.get("lookback_days", 120)}-Day History</h2>
    <p style="font-size:13px;color:#8b949e;margin-bottom:12px">
      How often our technical signals (EMA9/21 + RSI + MACD) predicted next-day direction correctly for <strong>{bt.get("ticker","")}</strong>.
    </p>
    <table>
      <tr><th>Signal</th><th>Win Rate</th><th>Samples</th><th>Avg Return</th><th>Avg Win</th><th>Avg Loss</th></tr>
      {rows}
    </table>
    <div class="note" style="margin-top:12px">
      <strong>{calibration}</strong> — Win rate &ge;55% = signals are predictive for this ticker.
      &lt;50% = technicals alone don't work well here; weight options flow signals higher.
      Based on {bt.get("lookback_days",120)} trading days.
    </div>
  </div>"""


def _build_level2_section(d: dict) -> str:
    l2 = d.get("level2")
    if not l2:
        return ""
    ratio = l2.get("bid_ask_ratio")
    cls   = l2.get("l2_cls", "neutral")
    color = "#3fb950" if cls == "bull" else "#f85149" if cls == "bear" else "#d29922"

    bid_rows = "".join(f'<tr><td style="color:#3fb950">${b["price"]:.2f}</td><td>{b["size"]:,}</td></tr>'
                       for b in l2.get("bids", []))
    ask_rows = "".join(f'<tr><td style="color:#f85149">${a["price"]:.2f}</td><td>{a["size"]:,}</td></tr>'
                       for a in l2.get("asks", []))
    return f"""
  <div class="section">
    <h2><span>📋</span> 8g. Level 2 Market Depth (IBKR)</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px;">
      <div class="price-card">
        <div class="label">Total Bid Size</div>
        <div class="value green">{l2.get("total_bid_size","—"):,}</div>
      </div>
      <div class="price-card">
        <div class="label">Total Ask Size</div>
        <div class="value red">{l2.get("total_ask_size","—"):,}</div>
      </div>
      <div class="price-card">
        <div class="label">Bid/Ask Ratio</div>
        <div class="value" style="color:{color}">{ratio or "—"}</div>
        <div class="sub">{l2.get("l2_signal","")}</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">
      <div>
        <h3 style="font-size:13px;color:#3fb950;margin-bottom:8px;">BID STACK</h3>
        <table><tr><th>Price</th><th>Size</th></tr>{bid_rows}</table>
      </div>
      <div>
        <h3 style="font-size:13px;color:#f85149;margin-bottom:8px;">ASK STACK</h3>
        <table><tr><th>Price</th><th>Size</th></tr>{ask_rows}</table>
      </div>
    </div>
    <div class="note" style="margin-top:12px">
      Bid/Ask ratio &gt;1.5 = buyers dominating (bullish). &lt;0.67 = sellers dominating (bearish).
      Large size at a specific bid = institutional support floor. Large ask = supply wall.
    </div>
  </div>"""


def _build_oi_change_section(d: dict) -> str:
    chain   = d.get("chain") or {}
    changes = chain.get("oi_changes")
    if changes is None:   # feature not run
        return ""
    if not changes:
        return f"""
  <div class="section">
    <h2><span>📈</span> Overnight OI Changes — New Money Detection</h2>
    <div class="banner neutral">OI baseline cached today. Run again tomorrow morning to see overnight position changes.</div>
  </div>"""
    rows = ""
    for r in changes[:10]:
        c_chg = r["call_chg"]; p_chg = r["put_chg"]
        c_cls = "green" if c_chg > 0 else "red" if c_chg < 0 else ""
        p_cls = "green" if p_chg > 0 else "red" if p_chg < 0 else ""
        rows += f"""
      <tr>
        <td>${r['strike']:.1f}</td>
        <td class="{c_cls}">{c_chg:+,}</td>
        <td class="{p_cls}">{p_chg:+,}</td>
        <td>{r['call_oi']:,}</td>
        <td>{r['put_oi']:,}</td>
        <td><span class="badge {r['cls']}">{r['signal']}</span></td>
      </tr>"""
    return f"""
  <div class="section">
    <h2><span>📈</span> Overnight OI Changes — New Money Detection</h2>
    <p style="color:#8b949e;font-size:13px;margin-bottom:12px;">Strikes where open interest changed significantly vs yesterday's close — indicates new positions being opened.</p>
    <table class="chain-table">
      <tr><th>Strike</th><th>Call OI Chg</th><th>Put OI Chg</th><th>Call OI</th><th>Put OI</th><th>Signal</th></tr>
      {rows}
    </table>
  </div>"""


def _build_expiry_pcr_section(d: dict) -> str:
    epcr = (d.get("chain") or {}).get("expiry_pcr") or []
    if not epcr:
        return ""
    rows = ""
    for e in epcr:
        pcr = e["pcr_vol"]
        cls = e["cls"]
        bar_bull = round((1 / (1 + pcr)) * 100) if pcr else 50
        bar_bear = 100 - bar_bull
        rows += f"""
      <tr>
        <td>{e['expiry']}</td>
        <td>{e['dte']}d</td>
        <td class="{'green' if cls=='bull' else 'red' if cls=='bear' else ''}">{pcr}</td>
        <td>{e['call_vol']:,}</td>
        <td>{e['put_vol']:,}</td>
        <td>
          <div style="display:flex;height:10px;border-radius:4px;overflow:hidden;width:100px;">
            <div style="width:{bar_bull}%;background:#3fb950;"></div>
            <div style="width:{bar_bear}%;background:#f85149;"></div>
          </div>
        </td>
      </tr>"""
    return f"""
  <div class="section">
    <h2><span>📊</span> Per-Expiry Put/Call Ratio — Where Is Hedging Concentrated?</h2>
    <p style="color:#8b949e;font-size:13px;margin-bottom:12px;">PCR &lt;0.7 = call-heavy (greed), &gt;1.3 = put-heavy (fear). Spikes in a specific expiry reveal where institutions are hedging.</p>
    <table class="chain-table">
      <tr><th>Expiry</th><th>DTE</th><th>PCR (Vol)</th><th>Call Vol</th><th>Put Vol</th><th>Call/Put Split</th></tr>
      {rows}
    </table>
  </div>"""


def _build_news_section(d: dict) -> str:
    news = d.get("news") or {}
    if not news or news.get("bull_count") is None:
        return ""
    cls    = news.get("cls", "neutral")
    signal = news.get("signal", "")
    headlines = news.get("headlines") or []
    rows = ""
    for h in headlines:
        sc = h["sentiment"]
        icon = "🟢" if sc == "bull" else "🔴" if sc == "bear" else "⚪"
        rows += f"<tr><td>{icon}</td><td style='font-size:13px'>{h['title']}</td></tr>"
    table = f"""
    <table class="chain-table" style="margin-top:12px;">
      <tr><th></th><th>Headline (last 3 days)</th></tr>
      {rows}
    </table>""" if rows else ""
    b = news.get("bull_count", 0); be = news.get("bear_count", 0)
    return f"""
  <div class="section">
    <h2><span>📰</span> News Sentiment</h2>
    <div class="banner {cls}">{signal}</div>
    <div class="metric-grid" style="margin:12px 0;">
      <div class="metric-card"><div class="m-label">Bull Headlines</div><div class="m-value green">{b}</div></div>
      <div class="metric-card"><div class="m-label">Bear Headlines</div><div class="m-value red">{be}</div></div>
      <div class="metric-card"><div class="m-label">Net Score</div>
        <div class="m-value {'green' if news.get('net_score',0)>0 else 'red' if news.get('net_score',0)<0 else ''}">{news.get('net_score',0):+d}</div></div>
    </div>
    {table}
  </div>"""


def _build_strike_pressure_section(d: dict) -> str:
    pressure = (d.get("chain") or {}).get("strike_pressure") or []
    if not pressure:
        return ""
    rows = ""
    for p in pressure[:10]:
        icon = "🟢" if p["cls"] == "bull" else "🔴"
        rows += f"""
      <tr>
        <td>{icon} {p['type']}</td>
        <td>${p['strike']:.1f}</td>
        <td class="{'green' if p['pressure']>0 else 'red'}">{p['pressure']:+.1f}%</td>
        <td>{p['vol_oi']:.2f}×</td>
        <td>{p['vol']:,}</td>
        <td class="{'green' if p['score']>0 else 'red'}">{p['score']:+.1f}</td>
      </tr>"""
    return f"""
  <div class="section">
    <h2><span>🎯</span> Strike Buy Pressure — Aggressive Buyers vs Sellers</h2>
    <p style="color:#8b949e;font-size:13px;margin-bottom:12px;">Pressure = how far last print was above/below mid. Positive = bought aggressively (paid ask). Score = pressure × vol/OI ratio.</p>
    <table class="chain-table">
      <tr><th>Type</th><th>Strike</th><th>Pressure</th><th>Vol/OI</th><th>Volume</th><th>Score</th></tr>
      {rows}
    </table>
  </div>"""


def _build_sector_rotation_section(d: dict) -> str:
    macro = d.get("macro") or {}
    rs    = macro.get("sector_rotation_5d")
    if rs is None:
        return ""
    signal  = macro.get("sector_rotation_signal", "")
    cls     = macro.get("sector_rotation_cls", "neutral")
    sec     = macro.get("sector_etf", "")
    sec_5d  = macro.get("sector_5d_pct", 0)
    spy_5d  = macro.get("spy_5d_pct", 0)
    return f"""
  <div class="section">
    <h2><span>🔄</span> Sector Rotation (5-Day vs SPY)</h2>
    <div class="banner {cls}">{signal}</div>
    <div class="metric-grid" style="margin:12px 0;">
      <div class="metric-card"><div class="m-label">{sec} 5d Return</div>
        <div class="m-value {'green' if sec_5d>0 else 'red'}">{sec_5d:+.2f}%</div></div>
      <div class="metric-card"><div class="m-label">SPY 5d Return</div>
        <div class="m-value {'green' if spy_5d>0 else 'red'}">{spy_5d:+.2f}%</div></div>
      <div class="metric-card"><div class="m-label">Relative Strength</div>
        <div class="m-value {'green' if rs>0 else 'red'}">{rs:+.2f}%</div></div>
    </div>
  </div>"""


def _build_uw_flow_section(d: dict) -> str:
    uw = d.get("uw_flow") or {}
    if not uw or uw.get("error"):
        err = (uw.get("error") or "")
        if "No flow" in err or not err:
            return ""
        hint = "Run with <code>--uw-key YOUR_API_KEY</code> to unlock real buy/sell flow direction."
        if "401" in err or "403" in err or "Unauthorized" in err:
            hint = "⚠ Invalid or expired Unusual Whales API key."
        elif "404" in err:
            hint = "⚠ Unusual Whales returned 404 — symbol may not have flow data."
        return f"""
  <div class="section">
    <h2><span>🐋</span> Options Flow (Unusual Whales)</h2>
    <div class="banner neutral">{hint}</div>
  </div>"""

    cls      = uw.get("cls", "neutral")
    signal   = uw.get("signal", "")
    bull_pct = uw.get("bull_pct", 0)
    bear_pct = uw.get("bear_pct", 0)
    net_pct  = uw.get("net_pct", 0)
    bull_pre = uw.get("bull_premium", 0)
    bear_pre = uw.get("bear_premium", 0)
    sw_bull  = uw.get("sweep_bull", 0)
    sw_bear  = uw.get("sweep_bear", 0)
    unu_bull = uw.get("unusual_bull", 0)
    unu_bear = uw.get("unusual_bear", 0)
    total    = uw.get("total_rows", 0)
    top      = uw.get("top_flows", [])

    def fmt_pre(v):
        if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
        if v >= 1_000:     return f"${v/1_000:.0f}K"
        return f"${v:.0f}"

    # Bar showing bull/bear split
    bar_html = f"""
    <div style="margin:12px 0 8px;">
      <div style="display:flex;height:18px;border-radius:6px;overflow:hidden;gap:2px;">
        <div style="width:{bull_pct}%;background:#3fb950;min-width:2px;" title="Bull {bull_pct}%"></div>
        <div style="width:{bear_pct}%;background:#f85149;min-width:2px;" title="Bear {bear_pct}%"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:12px;color:#8b949e;margin-top:4px;">
        <span>🟢 Bull {bull_pct}% ({fmt_pre(bull_pre)})</span>
        <span>🔴 Bear {bear_pct}% ({fmt_pre(bear_pre)})</span>
      </div>
    </div>"""

    stat_cards = f"""
    <div class="metric-grid" style="margin:14px 0;">
      <div class="metric-card"><div class="m-label">Net Flow</div>
        <div class="m-value {'green' if net_pct>0 else 'red' if net_pct<0 else ''}">{net_pct:+.1f}%</div></div>
      <div class="metric-card"><div class="m-label">Bull Sweeps</div>
        <div class="m-value green">{sw_bull}</div></div>
      <div class="metric-card"><div class="m-label">Bear Sweeps</div>
        <div class="m-value red">{sw_bear}</div></div>
      <div class="metric-card"><div class="m-label">Unusual Bull</div>
        <div class="m-value green">{unu_bull}</div></div>
      <div class="metric-card"><div class="m-label">Unusual Bear</div>
        <div class="m-value red">{unu_bear}</div></div>
      <div class="metric-card"><div class="m-label">Total Alerts</div>
        <div class="m-value">{total}</div></div>
    </div>"""

    # Top flows table
    rows_html = ""
    for f in top:
        side_lbl = f["side"]
        t_cls    = "green" if f["bull"] else "red"
        sweep_lbl = " 🔥" if f["sweep"] else ""
        unu_lbl   = " ⭐" if f["unusual"] else ""
        rows_html += f"""
      <tr>
        <td style="color:{'#3fb950' if f['type']=='CALL' else '#f85149'};">{f['type']}</td>
        <td>${f['strike']}</td>
        <td>{f['expiry']}</td>
        <td class="{t_cls}">{side_lbl}{sweep_lbl}{unu_lbl}</td>
        <td class="{t_cls}">{fmt_pre(f['premium'])}</td>
      </tr>"""

    table_html = ""
    if rows_html:
        table_html = f"""
    <table class="chain-table" style="margin-top:12px;">
      <tr><th>Type</th><th>Strike</th><th>Expiry</th><th>Side</th><th>Premium</th></tr>
      {rows_html}
    </table>
    <div style="font-size:11px;color:#8b949e;margin-top:6px;">🔥 sweep &nbsp; ⭐ unusual &nbsp; Showing top {len(top)} prints by premium</div>"""

    return f"""
  <div class="section">
    <h2><span>🐋</span> Options Flow (Unusual Whales)</h2>
    <div class="banner {cls}">{signal}</div>
    {bar_html}
    {stat_cards}
    {table_html}
  </div>"""


def _build_macro_section(d: dict) -> str:
    macro = d.get("macro") or {}
    if not macro:
        return ""
    rows = ""
    labels = [
        ("SPY",   "S&P 500 ETF"),
        ("QQQ",   "Nasdaq 100 ETF"),
        ("NQ_F",  "/NQ Futures"),
        ("ES_F",  "/ES Futures"),
        ("VIX",   "Volatility Index"),
        ("VIX3M", "VIX 3-Month"),
        ("TLT",   "20yr Bond ETF"),
        ("UUP",   "US Dollar (DXY proxy)"),
    ]
    sec_etf = macro.get("sector_etf")
    if sec_etf:
        labels.append((sec_etf, f"Sector ETF ({sec_etf})"))
    for sym, label in labels:
        data = macro.get(sym) or {}
        if not data:
            continue
        p = data.get("price", "—")
        chg = data.get("pct_chg")
        chg_str = f'{chg:+.2f}%' if chg is not None else "—"
        color = "#3fb950" if (chg or 0) > 0 else "#f85149" if (chg or 0) < 0 else "#8b949e"
        rows += (f'<tr><td>{label}</td>'
                 f'<td><strong>${p}</strong></td>'
                 f'<td style="color:{color}">{chg_str}</td></tr>')

    signals = ""
    for key, icon in [("futures_signal","📡"), ("vix_regime","🌡"), ("vix_term","📐"),
                       ("tlt_signal","📉"), ("dxy_signal","💵"), ("sector_signal","🏭")]:
        val = macro.get(key)
        cls = macro.get(key.replace("signal","cls").replace("regime","cls").replace("term","term_cls").replace("futures_cls","futures_cls"), "neutral")
        if val:
            color = "#3fb950" if cls=="bull" else "#f85149" if cls=="bear" else "#d29922"
            signals += (f'<div style="padding:7px 12px;border-left:3px solid {color};'
                        f'margin-bottom:6px;font-size:13px;color:#c9d1d9">{icon} {val}</div>')

    return f"""
  <div class="section">
    <h2><span>🌍</span> 8c. Macro Context — SPY / QQQ / VIX / TLT / DXY / Sector</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
      <div>
        <table>
          <tr><th>Instrument</th><th>Price</th><th>Change</th></tr>
          {rows}
        </table>
      </div>
      <div>{signals}</div>
    </div>
  </div>"""


def _build_gex_section(d: dict) -> str:
    c = d.get("chain") or {}
    gex = c.get("gex_by_strike") or {}
    net_gex = c.get("net_gex")
    pin = c.get("top_pin_strike")
    flip = c.get("top_flip_strike")
    if not gex or net_gex is None:
        return ""

    spot = c.get("spot") or d.get("last", 0)
    # Top 8 strikes around spot by absolute GEX
    near = sorted(gex.items(), key=lambda x: abs(x[0] - spot))[:12]
    near_sorted = sorted(near, key=lambda x: x[0], reverse=True)

    rows = ""
    for k, v in near_sorted:
        bar_pct = min(abs(v) / (max(abs(g) for _, g in near) + 1e-9) * 100, 100)
        color = "#3fb950" if v > 0 else "#f85149"
        atm_mark = " ◀ ATM" if abs(k - spot) < 2.5 else ""
        rows += (f'<tr><td><strong>${k:.2f}</strong>{atm_mark}</td>'
                 f'<td style="color:{color}">{v:+,.1f}</td>'
                 f'<td style="padding:4px 12px"><div style="background:{color};'
                 f'height:8px;border-radius:4px;width:{bar_pct:.0f}%;opacity:0.7"></div></td>'
                 f'<td style="font-size:12px;color:#8b949e">{"📌 Pin zone" if v > 0 else "⚡ Accel zone"}</td></tr>')

    net_color   = "#3fb950" if (net_gex or 0) > 0 else "#f85149"
    regime      = c.get("gex_regime") or ("Pinning" if (net_gex or 0) > 0 else "Trending")
    regime_desc = c.get("gex_regime_desc") or ""
    regime_cls  = c.get("gex_regime_cls") or "neutral"
    regime_color = {"bull": "#3fb950", "bear": "#f85149", "neutral": "#d29922"}.get(regime_cls, "#d29922")

    exp_move   = c.get("gex_expected_move")
    upper_band = c.get("gex_upper_band")
    lower_band = c.get("gex_lower_band")
    resistance = c.get("gex_resistance")
    support    = c.get("gex_support")
    flip_lvl   = c.get("gex_flip_level") or flip
    call_gain  = c.get("gex_call_gain")
    put_gain   = c.get("gex_put_gain")

    prediction_html = ""
    if exp_move and upper_band and lower_band:
        res_str  = f"${resistance:.2f}" if resistance else "—"
        sup_str  = f"${support:.2f}"    if support    else "—"
        flip_str = f"${flip_lvl:.2f}"   if flip_lvl   else "—"
        prediction_html = f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin:16px 0">
      <div style="font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:12px">
        🎯 GEX Price Prediction — Today's Session
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px">
        <div class="price-card">
          <div class="label">GEX Regime</div>
          <div class="value" style="color:{regime_color};font-size:18px">{regime}</div>
          <div class="sub" style="font-size:10px">{regime_desc[:60]}</div>
        </div>
        <div class="price-card">
          <div class="label">Expected Move</div>
          <div class="value" style="color:#d29922">${exp_move:.2f}</div>
          <div class="sub">GEX-adjusted daily range</div>
        </div>
        <div class="price-card">
          <div class="label">Upper Band</div>
          <div class="value green">${upper_band:.2f}</div>
          <div class="sub">Call premium +${call_gain:.2f} est.</div>
        </div>
        <div class="price-card">
          <div class="label">Lower Band</div>
          <div class="value red">${lower_band:.2f}</div>
          <div class="sub">Put premium +${put_gain:.2f} est.</div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px">
        <div class="price-card">
          <div class="label">GEX Resistance Wall</div>
          <div class="value red">{res_str}</div>
          <div class="sub">Highest +GEX above spot — dealers sell here</div>
        </div>
        <div class="price-card">
          <div class="label">GEX Support Wall</div>
          <div class="value green">{sup_str}</div>
          <div class="sub">Highest +GEX below spot — dealers buy here</div>
        </div>
        <div class="price-card">
          <div class="label">Gamma Flip Level</div>
          <div class="value" style="color:#d29922">{flip_str}</div>
          <div class="sub">Break = dealer regime flips, move accelerates</div>
        </div>
      </div>
      <div style="font-size:11px;color:#8b949e;line-height:1.6;border-top:1px solid #30363d;padding-top:10px">
        <strong style="color:#e6edf3">How to use for day trading:</strong>
        {"In <strong>Pinning</strong> mode — sell premium or fade moves toward the pin zone. Breakouts are short-lived unless the flip level is breached."
         if regime == "Pinning" else
         "In <strong>Trending</strong> mode — buy directional calls/puts. Dealer hedging amplifies the move. Ride momentum until next GEX wall."}
        Price is expected to stay in the <strong>${lower_band:.2f}–${upper_band:.2f}</strong> band unless the gamma flip at <strong>{flip_str}</strong> is broken.
        ATM option premium can increase by ~<strong>${call_gain:.2f}</strong> per contract for each ${exp_move:.2f} move in either direction.
      </div>
    </div>"""

    return f"""
  <div class="section">
    <h2><span>⚡</span> 8d. Gamma Exposure (GEX) — Dealer Positioning &amp; Price Prediction</h2>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;">
      <div class="price-card">
        <div class="label">Net GEX</div>
        <div class="value" style="color:{net_color}">{net_gex:+,.1f}</div>
        <div class="sub">{"Positive = pinning" if (net_gex or 0) > 0 else "Negative = acceleration"}</div>
      </div>
      <div class="price-card">
        <div class="label">Top Pin Zone</div>
        <div class="value green">${pin:.2f}</div>
        <div class="sub">Dealers hedge = price sticky here</div>
      </div>
      <div class="price-card">
        <div class="label">Top Flip Zone</div>
        <div class="value red">${flip:.2f}</div>
        <div class="sub">Break here = accelerated move</div>
      </div>
    </div>
    {prediction_html}
    <table>
      <tr><th>Strike</th><th>GEX ($)</th><th>Magnitude</th><th>Role</th></tr>
      {rows}
    </table>
    <div class="note" style="margin-top:12px">
      <strong>How to read GEX:</strong> Positive GEX = dealers long gamma = they sell into rallies &amp; buy dips → price <em>pins</em>.
      Negative GEX = dealers short gamma = they buy into rallies &amp; sell into drops → price <em>accelerates</em>.
      Pin zone = high positive GEX strike. Flip zone = most negative GEX = acceleration if breached.
    </div>
  </div>"""


def _build_confidence_section(d: dict) -> str:
    score = d.get("conf_score", 50)
    cls   = d.get("conf_cls", "neutral")
    reasons = d.get("conf_reasons") or []
    color = "#3fb950" if cls == "bull" else "#f85149" if cls == "bear" else "#d29922"
    label = ("BULLISH" if cls == "bull" else "BEARISH" if cls == "bear" else "NEUTRAL")
    bar   = min(score, 100)

    reasons_html = "".join(
        f'<div style="font-size:12px;color:{"#3fb950" if r.startswith("+") else "#f85149" if r.startswith("-") else "#8b949e"};'
        f'padding:2px 0">{r}</div>'
        for r in reasons
    )

    return f"""
  <div class="section">
    <h2><span>🎯</span> Composite Confidence Score</h2>
    <div style="display:flex;align-items:center;gap:24px;margin-bottom:16px;">
      <div style="text-align:center;min-width:120px">
        <div style="font-size:48px;font-weight:800;color:{color}">{score}</div>
        <div style="font-size:14px;font-weight:700;color:{color}">{label}</div>
        <div style="font-size:11px;color:#8b949e;margin-top:2px">out of 100</div>
      </div>
      <div style="flex:1">
        <div style="background:#21262d;border-radius:8px;height:18px;overflow:hidden;margin-bottom:10px">
          <div style="background:{color};height:100%;width:{bar}%;border-radius:8px;
               transition:width 0.3s;opacity:0.85"></div>
        </div>
        <div style="columns:2;column-gap:16px">{reasons_html}</div>
      </div>
    </div>
    <div class="note">
      Score &ge;60 = Bullish bias → prefer call debit spreads.
      Score &le;40 = Bearish bias → prefer put debit spreads.
      40–60 = Neutral → prefer iron condors or wait for better setup.
      <strong>This score weights: technicals (9pts), options flow (6pts), macro (6pts).</strong>
    </div>
  </div>"""


def _build_5m_section(d: dict) -> str:
    df5 = d.get("df5")
    if df5 is None or df5.empty or len(df5) < 3:
        return ""
    try:
        last_bar = df5.iloc[-1]
        prev_bar = df5.iloc[-2]
        close5   = float(last_bar["Close"])
        ema9_5   = float(last_bar["EMA9"])
        ema21_5  = float(last_bar["EMA21"])
        rsi5     = float(last_bar["RSI"]) if not math.isnan(last_bar["RSI"]) else None
        prev_ema9 = float(prev_bar["EMA9"])

        cross_str = ""
        if prev_ema9 < float(prev_bar["Close"]) and close5 < ema9_5:
            cross_str = '<span style="color:#f85149">⬇ EMA9 crossed below price — bearish signal</span>'
        elif prev_ema9 > float(prev_bar["Close"]) and close5 > ema9_5:
            cross_str = '<span style="color:#3fb950">⬆ EMA9 crossed above price — bullish signal</span>'
        else:
            above = close5 > ema9_5
            cross_str = (f'<span style="color:{"#3fb950" if above else "#f85149"}">'
                         f'Price {"above" if above else "below"} 5m EMA9 — '
                         f'{"bullish" if above else "bearish"} momentum</span>')

        rsi5_str = f"{rsi5:.1f}" if rsi5 is not None else "—"
        rsi5_cls = "bull" if rsi5 and rsi5 > 50 else "bear"
        last_time = df5.index[-1].strftime("%H:%M") if hasattr(df5.index[-1], "strftime") else ""
        vwap5 = float(last_bar["VWAP"]) if "VWAP" in last_bar.index and not math.isnan(float(last_bar.get("VWAP", float("nan")))) else None

        # Build mini bar table (last 6 bars)
        bar_rows = ""
        has_vwap_col = "VWAP" in df5.columns
        for i, (ts, row) in enumerate(df5.tail(6).iterrows()):
            t_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)
            c = float(row["Close"])
            o = float(row["Open"])
            color = "#3fb950" if c >= o else "#f85149"
            vwap_cell = f'<td>${float(row["VWAP"]):.2f}</td>' if has_vwap_col else ""
            bar_rows += (
                f'<tr><td>{t_str}</td>'
                f'<td style="color:{color};font-weight:600">${c:.2f}</td>'
                f'<td>${float(row["EMA9"]):.2f}</td>'
                f'<td>${float(row["EMA21"]):.2f}</td>'
                f'{vwap_cell}'
                f'<td>{int(row["Volume"]):,}</td></tr>'
            )
        vwap5_header = "<th>VWAP</th>" if has_vwap_col else ""

        return f"""
  <div class="section">
    <h2><span>⏱️</span> 8b. 5-Minute Entry Trigger</h2>
    <p style="font-size:13px;color:#8b949e;margin-bottom:12px;">
      5m chart — use EMA9 crossover as actual entry signal; 15m for directional bias.
      Last bar: <strong>{last_time}</strong>
    </p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px;">
      <div class="price-card">
        <div class="label">5m Close</div>
        <div class="value blue">${close5:.2f}</div>
      </div>
      <div class="price-card">
        <div class="label">5m EMA9</div>
        <div class="value {"green" if close5 > ema9_5 else "red"}">${ema9_5:.2f}</div>
        <div class="sub">{'↑ Support' if close5 > ema9_5 else '↓ Resistance'}</div>
      </div>
      <div class="price-card">
        <div class="label">5m EMA21</div>
        <div class="value {"green" if close5 > ema21_5 else "red"}">${ema21_5:.2f}</div>
      </div>
      <div class="price-card">
        <div class="label">5m RSI</div>
        <div class="value {rsi5_cls}">{rsi5_str}</div>
      </div>
      {f'<div class="price-card"><div class="label">5m VWAP</div><div class="value {"green" if close5 > vwap5 else "red"}">${vwap5:.2f}</div><div class="sub">{"Above=bullish" if close5 > vwap5 else "Below=bearish"}</div></div>' if vwap5 else ""}
    </div>
    <div class="bias-box {"bull" if close5 > ema9_5 else "bear"}" style="margin-bottom:14px;">
      <strong>5m Signal:</strong> {cross_str}
      &nbsp;|&nbsp; Entry trigger: wait for 5m candle to close on correct side of EMA9 before entering.
    </div>
    <table>
      <tr><th>Time</th><th>Close</th><th>EMA9</th><th>EMA21</th>{vwap5_header}<th>Volume</th></tr>
      {bar_rows}
    </table>
  </div>"""
    except Exception:
        return ""


def build_html(d: dict) -> str:
    bias_pill = pill(d["bias"], d["bias_class"])
    change_cls = "red" if d["pct_change"] < 0 else "green"
    change_sign = "" if d["pct_change"] >= 0 else ""

    # ── price cards ──────────────────────────────────────────────────────────
    price_cards = ""
    cards = [
        ("Last Price", fmt(d["last"]), "blue", ""),
        ("Session Open", fmt(d["day_open"]), "", ""),
        ("Day High", fmt(d["day_high"]), "green", ""),
        ("Day Low", fmt(d["day_low"]), "red", ""),
        ("Day Change", f"{change_sign}{abs(d['pct_change']):.2f}%", change_cls, fmt(d["last"] - d["day_open"])),
        ("Intraday Range", fmt(d["day_range"], prefix="$"), "",
         f"{d['day_range']/d['day_open']*100:.2f}% of price"),
    ]
    if not math.isnan(d["prior_close"]):
        cards.insert(0, ("Prior Close", fmt(d["prior_close"]), "", ""))
    if not math.isnan(d["pm_high"]):
        cards.append(("Pre-Mkt High", fmt(d["pm_high"]), "green", ""))
        cards.append(("Pre-Mkt Low",  fmt(d["pm_low"]),  "red",   ""))
    for label, value, vcls, sub in cards:
        price_cards += f"""
        <div class="price-card">
          <div class="label">{label}</div>
          <div class="value {vcls}">{value}</div>
          {"<div class='sub'>" + sub + "</div>" if sub else ""}
        </div>"""

    # ── indicator table ───────────────────────────────────────────────────────
    ind_rows = f"""
      <tr><td>EMA 9</td><td><strong>{fmt(d['ema9'])}</strong></td>
          <td>{pill("Resistance" if d['last'] < d['ema9'] else "Support", "bear" if d['last'] < d['ema9'] else "bull")}</td></tr>
      <tr><td>EMA 21</td><td><strong>{fmt(d['ema21'])}</strong></td>
          <td>{pill("Resistance" if d['last'] < d['ema21'] else "Support", "bear" if d['last'] < d['ema21'] else "bull")}</td></tr>
      <tr><td>RSI (14)</td><td><strong>{d['rsi']:.2f}</strong></td>
          <td>{pill(d['rsi_label'], d['rsi_class'])}</td></tr>
      <tr><td>MACD</td><td><strong>{d['macd']:.4f} vs Signal {d['macd_sig']:.4f}</strong></td>
          <td>{pill(d['macd_label'], d['macd_class'])}</td></tr>
      <tr><td>MACD Histogram</td><td><strong>{d['macd_hist']:.4f}</strong></td>
          <td>{pill("Negative — Bearish" if d['macd_hist'] < 0 else "Positive — Bullish", d['macd_class'])}</td></tr>
      <tr><td>Volume (last bar)</td><td><strong>{d['last_vol']:,}</strong></td>
          <td>{pill(f"{d['vol_ratio']:.1f}× avg — {'Distribution' if d['bias_class']=='bear' else 'Accumulation'}", d['bias_class'])}</td></tr>
    """

    # ── key levels ────────────────────────────────────────────────────────────
    def lvl(price, name, role, cls, note):
        if math.isnan(price):
            return ""
        bold = "<strong>" if abs(price - d["last"]) < 0.05 else ""
        bold_end = "</strong>" if bold else ""
        return f"<tr><td>{name}</td><td>{bold}{fmt(price)}{bold_end}</td><td>{pill(role, cls)}</td><td>{note}</td></tr>"

    lvl_rows = ""
    lvl_rows += lvl(d["day_high"],   "Intraday High",      "Resistance", "bear", "Today's HOD")
    lvl_rows += lvl(d["day_open"],   "Session Open",       "Resistance" if d["last"] < d["day_open"] else "Support",
                    "bear" if d["last"] < d["day_open"] else "bull", "Gap reference")
    if not math.isnan(d["pm_high"]):
        lvl_rows += lvl(d["pm_high"], "Pre-Market High",   "Resistance", "bear", "Pre-market HOD")
    lvl_rows += lvl(d["ema21"],      "EMA 21 (dynamic)",  "Resistance" if d["last"] < d["ema21"] else "Support",
                    "bear" if d["last"] < d["ema21"] else "bull", "Slower EMA")
    lvl_rows += lvl(d["ema9"],       "EMA 9 (dynamic)",   "Resistance" if d["last"] < d["ema9"] else "Support",
                    "bear" if d["last"] < d["ema9"] else "bull", "Faster EMA")
    if not math.isnan(d.get("vwap") or float("nan")):
        vwap_role = "Support" if d["last"] >= d["vwap"] else "Resistance"
        vwap_cls  = "bull"   if d["last"] >= d["vwap"] else "bear"
        lvl_rows += lvl(d["vwap"], "VWAP (session)", vwap_role, vwap_cls,
                        "Primary intraday filter — above=bullish, below=bearish")
    lvl_rows += f"""<tr style="background:#1c2128">
        <td><strong>CURRENT PRICE</strong></td>
        <td><strong style="color:#58a6ff">{fmt(d['last'])}</strong></td>
        <td>{pill("Live Quote", "neutral")}</td>
        <td>{d['ema_rel']}</td></tr>"""
    if not math.isnan(d["pm_low"]):
        lvl_rows += lvl(d["pm_low"],  "Pre-Market Low",   "Support", "bull", "Pre-market LOD")
    lvl_rows += lvl(d["day_low"],    "Intraday Low",       "Support", "bull", "Today's LOD — key floor")
    if not math.isnan(d["prior_close"]):
        lvl_rows += lvl(d["prior_close"], "Prior Close",  "Support", "bull", "Previous session close")
    si = d.get("stock_info") or {}
    if si.get("pdh"):
        lvl_rows += lvl(si["pdh"], "Prior Day High (PDH)", "Resistance", "bear", "Yesterday's HOD — key breakout level")
    if si.get("pdc"):
        lvl_rows += lvl(si["pdc"], "Prior Day Close (PDC)", "Support" if d["last"] >= si["pdc"] else "Resistance",
                        "bull" if d["last"] >= si["pdc"] else "bear", "Yesterday's close")
    if si.get("pdl"):
        lvl_rows += lvl(si["pdl"], "Prior Day Low (PDL)", "Support", "bull", "Yesterday's LOD — breakdown level")

    # ── options chain strikes ─────────────────────────────────────────────────
    chain_rows = ""
    for s in sorted(d["strikes"], reverse=True):
        dist = s - d["last"]
        if dist > 0:
            role, cls, note = "Call / OTM Resistance", "bear", "Above market"
        elif abs(dist) < d["round_step"] * 0.6:
            role, cls, note = "ATM Pin Zone", "neutral", "Max pain area"
        else:
            role, cls, note = "Put / OTM Support", "bull", "Below market"
        if abs(s - d["max_pain_est"]) < d["round_step"] * 0.6:
            note += " · Max Pain"
        chain_rows += f"<tr><td><strong>${s:.2f}</strong></td><td>{'Call' if dist >= 0 else 'Put'}</td><td>{pill(role,cls)}</td><td>{note}</td></tr>"

    # ── strategy A rows ───────────────────────────────────────────────────────
    strat_a_html = "".join(f"<tr><td>{r[0]}</td><td><strong>{r[1]}</strong></td></tr>"
                           for r in d["strat_a_rows"])

    # ── iron condor ───────────────────────────────────────────────────────────
    ic_rr = round(d["round_step"] - d["ic_credit_hi"], 2)

    now_str = datetime.now().strftime("%b %d, %Y  %H:%M")

    # ── Pre-compute chain-dependent HTML snippets (avoids nested f-strings) ──
    c = d.get("chain") or {}

    if c.get("atm_iv") is not None:
        # IV Rank row
        ivr_val  = c.get("iv_rank")
        ivr_pct  = c.get("iv_pct")
        ivr_lbl  = c.get("ivr_label", "N/A")
        hv20     = c.get("hv_20")
        hv_lo    = c.get("hv_52w_low")
        hv_hi    = c.get("hv_52w_high")
        ivr_str  = (f'{ivr_val:.0f} (pct: {ivr_pct:.0f}%)' if ivr_val is not None else "N/A")
        hv_str   = (f'HV20={hv20:.1f}% | 52w range {hv_lo:.1f}%–{hv_hi:.1f}%'
                    if hv20 is not None else "")
        # Greeks rows
        ibkr_live   = c.get("ibkr_connected", False)
        greek_src   = "IBKR live" if ibkr_live else "N/A — add --ibkr flag"
        g_delta  = f'{c["atm_delta"]:.3f}' if c.get("atm_delta") is not None else None
        g_gamma  = f'{c["atm_gamma"]:.4f}' if c.get("atm_gamma") is not None else None
        g_theta  = f'{c["atm_theta"]:.4f}' if c.get("atm_theta") is not None else None
        g_vega   = f'{c["atm_vega"]:.4f}'  if c.get("atm_vega")  is not None else None
        atm_stk  = f'${c["atm_strike"]:.2f}' if c.get("atm_strike") else "ATM"
        greek_header_badge = (' <span style="background:#1f6feb;color:#fff;font-size:10px;'
                              'padding:1px 7px;border-radius:10px;vertical-align:middle">IBKR LIVE</span>'
                              if ibkr_live else
                              ' <span style="background:#30363d;color:#8b949e;font-size:10px;'
                              'padding:1px 7px;border-radius:10px;vertical-align:middle">run with --ibkr</span>')
        # 25Δ skew row
        skew_val  = c.get("skew_25d")
        skew_lbl  = c.get("skew_label", "")
        skew_c    = c.get("skew_cls", "neutral")
        iv_c25    = c.get("iv_call_25d")
        iv_p25    = c.get("iv_put_25d")
        stk_c25   = c.get("strike_call_25d")
        stk_p25   = c.get("strike_put_25d")
        skew_detail = (f'Call ${stk_c25:.2f} IV={iv_c25:.1f}% vs Put ${stk_p25:.2f} IV={iv_p25:.1f}%'
                       if iv_c25 is not None and iv_p25 is not None else "")
        skew_row = (
            f'<tr><td>25Δ Risk Reversal (Skew)</td>'
            f'<td><strong style="color:{"#3fb950" if skew_c=="bull" else "#f85149" if skew_c=="bear" else "#d29922"}">'
            f'{skew_val:+.1f}%</strong><br><small style="color:#8b949e">{skew_detail}</small></td>'
            f'<td>{pill(skew_lbl, skew_c)}</td></tr>'
            if skew_val is not None else ""
        )
        # IV term structure
        ts = c.get("term_structure", [])
        ts_shape = c.get("term_shape", "")
        ts_label = c.get("term_label", "")
        if ts:
            ts_cells = "".join(
                f'<td style="text-align:center;padding:6px 10px;">'
                f'<div style="font-size:11px;color:#8b949e">{t["expiry"]}<br>({t["dte"]}d)</div>'
                f'<div style="font-weight:700;color:#58a6ff;font-size:14px">{t["atm_iv"]:.1f}%</div></td>'
                for t in ts if t.get("atm_iv") is not None
            )
            ts_color = "#3fb950" if ts_shape == "contango" else "#f85149" if ts_shape == "backwardation" else "#d29922"
            term_row = (
                f'<tr><td colspan="3" style="padding:0">'
                f'<div style="margin:4px 0;padding:10px 12px;background:#1a2332;border-radius:6px;">'
                f'<div style="font-size:11px;font-weight:600;color:#8b949e;margin-bottom:6px;">'
                f'IV TERM STRUCTURE &nbsp;<span style="color:{ts_color}">{ts_label.upper()}</span></div>'
                f'<table style="width:auto;border-collapse:collapse;margin:0"><tr>{ts_cells}</tr></table>'
                f'</div></td></tr>'
            )
        else:
            term_row = ""

        # IV vs HV spread row
        iv_hv_sp  = c.get("iv_hv_spread")
        iv_hv_sig = c.get("iv_hv_signal", "")
        iv_hv_c   = c.get("iv_hv_cls", "neutral")
        iv_hv_color = "#3fb950" if iv_hv_c=="bull" else "#f85149" if iv_hv_c=="bear" else "#d29922"
        iv_hv_row = (
            f'<tr><td>IV vs Realized Vol (HV20)</td>'
            f'<td><strong style="color:{iv_hv_color}">{iv_hv_sp:+.1f}%</strong></td>'
            f'<td style="color:{iv_hv_color}">{iv_hv_sig}</td></tr>'
            if iv_hv_sp is not None else ""
        )

        iv_rows_html = (
            f'<tr><td>ATM IV ({atm_stk})</td>'
            f'<td><strong>{c["atm_iv"]:.1f}%</strong> ({"IBKR real-time" if ibkr_live else "yfinance ~15min delay"}, {c["expiry_used"]})</td>'
            f'<td style="color:{d["iv_color"]}">{d["iv_regime"]}</td></tr>'
            f'<tr><td>IV Rank (52w HV proxy)</td>'
            f'<td><strong>{ivr_str}</strong><br><small style="color:#8b949e">{hv_str}</small></td>'
            f'<td>{ivr_lbl}</td></tr>'
            f'{skew_row}'
            f'{iv_hv_row}'
            f'{term_row}'
            f'<tr style="background:#1a2332"><td colspan="3" style="padding:8px 12px;'
            f'font-size:12px;color:#8b949e;font-weight:600;">ATM GREEKS — {atm_stk}{greek_header_badge}</td></tr>'
            f'<tr><td>Delta (Δ)</td><td><strong>{g_delta or "—"}</strong></td>'
            f'<td>{"Moves ~${:.2f} per $1 in stock".format(abs(c["atm_delta"])) if c.get("atm_delta") is not None else greek_src}</td></tr>'
            f'<tr><td>Gamma (Γ)</td><td><strong>{g_gamma or "—"}</strong></td>'
            f'<td>{"Delta changes {:.4f} per $1 move".format(c["atm_gamma"]) if c.get("atm_gamma") is not None else greek_src}</td></tr>'
            f'<tr><td>Theta (Θ)</td><td><strong style="color:#f85149">{g_theta or "—"}</strong></td>'
            f'<td>{"Loses ${:.4f}/day to time decay".format(abs(c["atm_theta"])) if c.get("atm_theta") is not None else greek_src}</td></tr>'
            f'<tr><td>Vega (V)</td><td><strong style="color:#58a6ff">{g_vega or "—"}</strong></td>'
            f'<td>{"P&L changes ${:.4f} per 1% IV move".format(c["atm_vega"]) if c.get("atm_vega") is not None else greek_src}</td></tr>'
        )
    else:
        ivr_lbl = c.get("ivr_label", "")
        iv_rows_html = (
            f'<tr><td>Estimated IV</td>'
            f'<td><strong>~{d["est_iv"]*100:.0f}%</strong></td>'
            f'<td style="color:{d["iv_color"]}">{d["iv_regime"]}</td></tr>'
            f'<tr><td>IV Rank (est.)</td>'
            f'<td><strong>~{d["est_ivr_low"]}–{d["est_ivr_high"]}th percentile</strong></td>'
            f'<td>{"Premium selling favoured" if d["est_ivr_high"] >= 55 else "Debit spreads favoured"}</td></tr>'
        )

    if c:
        poi_heavy = "Put-heavy" if c["pcr_oi"] > 1 else "Call-heavy"
        pcr_html = (
            f'<table>'
            f'<tr><th>Metric</th><th>Value</th><th>Sentiment</th></tr>'
            f'<tr><td>PCR by Volume</td>'
            f'<td><strong>{c["pcr_vol"]:.2f}</strong>'
            f' ({c["total_put_vol"]:,} puts / {c["total_call_vol"]:,} calls)</td>'
            f'<td>{pill(c["pcr_sentiment"], c["pcr_cls"])}</td></tr>'
            f'<tr><td>PCR by Open Interest</td>'
            f'<td><strong>{c["pcr_oi"]:.2f}</strong>'
            f' ({c["total_put_oi"]:,} puts / {c["total_call_oi"]:,} calls)</td>'
            f'<td>{poi_heavy}</td></tr>'
            f'<tr><td>Overall Sentiment</td>'
            f'<td colspan="2">{pill(c["pcr_sentiment"], c["pcr_cls"])}</td></tr>'
            f'</table>'
            f'<div class="note"><strong>Live data (yfinance, ~15 min delay).</strong> '
            f'PCR &gt;1.5 = extreme fear. PCR &lt;0.7 = greed/complacency. '
            f'Volume PCR = today\'s flow; OI PCR = accumulated positioning.</div>'
        )
    else:
        implied_pcr = ("Likely &gt;1.2 (put-heavy)" if d["bias_class"] == "bear"
                       else "Likely &lt;0.8 (call-heavy)" if d["bias_class"] == "bull"
                       else "Likely ~1.0 (balanced)")
        pcr_html = (
            f'<p>Options chain unavailable. Sentiment inferred from price action:</p>'
            f'<table><tr><th>Signal</th><th>Observation</th></tr>'
            f'<tr><td>Price vs Open</td><td>{change_sign}{d["pct_change"]:.2f}%</td></tr>'
            f'<tr><td>RSI</td><td>{d["rsi"]:.1f} — {d["rsi_label"]}</td></tr>'
            f'<tr><td>Implied PCR</td><td>{implied_pcr}</td></tr>'
            f'</table>'
        )

    chain_expiry_label = c["expiry_used"] if c.get("expiry_used") else d["trading_date"]

    # Implied move banner
    implied_move_html = ""
    if c.get("implied_move_pct") is not None:
        im_pct = c["implied_move_pct"]
        im_dol = c["implied_move_dollar"]
        liq_c  = c.get("atm_call_spread_pct")
        liq_p  = c.get("atm_put_spread_pct")
        liq_c_flag = (f'<span style="color:#f85149">⚠ Illiquid ({liq_c:.1f}%)</span>' if (liq_c or 0) > 15
                      else f'<span style="color:#3fb950">✅ Liquid ({liq_c:.1f}%)</span>' if liq_c else "")
        liq_p_flag = (f'<span style="color:#f85149">⚠ Illiquid ({liq_p:.1f}%)</span>' if (liq_p or 0) > 15
                      else f'<span style="color:#3fb950">✅ Liquid ({liq_p:.1f}%)</span>' if liq_p else "")
        c_mid_str = f"${c['atm_call_mid']:.2f}" if c.get("atm_call_mid") else "—"
        p_mid_str = f"${c['atm_put_mid']:.2f}" if c.get("atm_put_mid") else "—"
        implied_move_html = (
            f'<div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;'
            f'padding:12px 16px;margin-bottom:14px;">'
            f'<strong style="color:#e3b341">📐 Implied Move (ATM Straddle)</strong>: '
            f'<span style="color:#58a6ff;font-size:1.1em">±${im_dol:.2f} ({im_pct:.2f}%)</span>'
            f' &nbsp;|&nbsp; Call mid: {c_mid_str} {liq_c_flag}'
            f' &nbsp;|&nbsp; Put mid: {p_mid_str} {liq_p_flag}'
            f'</div>'
        )

    if c.get("top_calls") and c.get("top_puts"):
        def _oi_row(r):
            vol_oi = r.get("vol_oi_ratio")
            liq    = r.get("liquidity_flag", "")
            iv_val = r.get("impliedVolatility", 0)
            liq_color = "#f85149" if "Illiquid" in liq else "#3fb950"
            return (
                f'<tr><td><strong>${r["strike"]:.2f}</strong></td>'
                f'<td>{int(r["openInterest"]):,}</td>'
                f'<td>{int(r["volume"]):,}</td>'
                f'<td>{vol_oi:.2f}x</td>' if vol_oi is not None else '<td>—</td>'
                f'<td>{iv_val:.1f}%</td>'
                f'<td style="color:{liq_color};font-size:11px">{liq}</td></tr>'
            )

        call_rows = "".join(_oi_row(r) for r in c["top_calls"])
        put_rows  = "".join(_oi_row(r) for r in c["top_puts"])
        chain_top_oi_html = (
            f'{implied_move_html}'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px;">'
            f'<div><h3 style="font-size:13px;color:#3fb950;margin-bottom:8px;">▲ TOP CALLS BY OI</h3>'
            f'<table><tr><th>Strike</th><th>OI</th><th>Vol</th><th>Vol/OI</th><th>IV%</th><th>Liq</th></tr>'
            f'{call_rows}</table></div>'
            f'<div><h3 style="font-size:13px;color:#f85149;margin-bottom:8px;">▼ TOP PUTS BY OI</h3>'
            f'<table><tr><th>Strike</th><th>OI</th><th>Vol</th><th>Vol/OI</th><th>IV%</th><th>Liq</th></tr>'
            f'{put_rows}</table></div>'
            f'</div>'
        )
    else:
        chain_top_oi_html = ""

    # ── Catalyst / calendar HTML ──────────────────────────────────────────────
    cat = d.get("catalyst") or {}
    cat_alerts = cat.get("alerts", [])
    cat_rows = ""
    ed = cat.get("earnings_date")
    fomc = cat.get("nearest_fomc")
    fomc_days = cat.get("fomc_days_away")
    if ed:
        ew_color = "#f85149" if cat.get("earnings_warning") else "#d29922"
        cat_rows += (
            f'<tr><td>Next Earnings</td>'
            f'<td><strong style="color:{ew_color}">{ed}</strong></td>'
            f'<td>{"🚨 HIGH RISK — within 5d of expiry" if cat.get("earnings_warning") else "Monitor"}</td></tr>'
        )
    if fomc:
        fc_color = "#f85149" if cat.get("fomc_warning") else "#8b949e"
        cat_rows += (
            f'<tr><td>Next FOMC</td>'
            f'<td><strong style="color:{fc_color}">{fomc}</strong>'
            f' ({abs(fomc_days) if fomc_days is not None else "?"} days from expiry)</td>'
            f'<td>{"🚨 Volatility spike risk" if cat.get("fomc_warning") else "Watch for pre-FOMC drift"}</td></tr>'
        )
    if not cat_rows:
        cat_rows = '<tr><td colspan="3" style="color:#8b949e">No earnings or FOMC events within 14 days of expiry.</td></tr>'

    alert_banners = ""
    for alert in cat_alerts:
        is_red = "🚨" in alert
        bc = "#f85149" if is_red else "#d29922"
        alert_banners += (
            f'<div style="background:#1c2128;border-left:4px solid {bc};'
            f'border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:8px;font-size:13px;">'
            f'{alert}</div>'
        )
    if not alert_banners:
        alert_banners = (
            '<div style="background:#1c2128;border-left:4px solid #3fb950;'
            'border-radius:0 8px 8px 0;padding:10px 14px;font-size:13px;">'
            '✅ No high-impact catalyst events within 5 days of expiry. Setup is clean.</div>'
        )

    max_pain_badge = "  ✅ (live)" if c.get("max_pain") is not None else "  ⚠ (estimated)"
    gamma_walls_text = (
        f'Gamma wall above: ${c["call_wall"]} (call OI) · '
        f'Gamma wall below: ${c["put_wall"]} (put OI).'
        if c.get("call_wall") else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{d['ticker']} 0DTE Options Setup — {d['trading_date']}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">

  <header>
    <h1>{d['ticker']} · 0DTE Options Trading Setup</h1>
    <div class="subtitle">{d.get('company', d['ticker'])} &nbsp;|&nbsp; {d['trading_date']} &nbsp;|&nbsp; Generated {now_str}</div>
    <div style="margin-top:12px;">
      <span class="badge {d['bias_class']}">{d['bias']}</span>
      <span class="badge">0DTE</span>
      {'<span class="badge bull">✅ IBKR Live Greeks</span>' if (d.get("chain") or {}).get("ibkr_connected") else '<span class="badge">Data · yfinance</span>'}
      {f'<span class="badge neutral">Short Float: {(d.get("stock_info") or {}).get("short_pct")}%</span>' if (d.get("stock_info") or {}).get("short_pct") is not None else ""}
    </div>
  </header>

  <!-- 0. Catalyst Calendar -->
  <div class="section">
    <h2><span>📅</span> 0. Catalyst Calendar &amp; Risk Flags</h2>
    {alert_banners}
    <table style="margin-top:12px;">
      <tr><th>Event</th><th>Date</th><th>Risk Level</th></tr>
      {cat_rows}
    </table>
    <div class="note" style="margin-top:12px;">
      <strong>Note:</strong> Earnings within 5 days = avoid short premium (IV will not crush as expected).
      FOMC within 2 days = avoid short volatility / iron condors. Verify at earningswhispers.com or your broker calendar.
    </div>
  </div>

  <!-- 1. Price & Trend -->
  <div class="section">
    <h2><span>📈</span> 1. Current Price &amp; Intraday Trend</h2>
    <div class="price-grid">{price_cards}</div>
    <table>
      <tr><th>Indicator</th><th>Value</th><th>Signal</th></tr>
      {ind_rows}
    </table>
    <div class="bias-box {d['bias_class']}">
      <strong>Bias: {d['bias']}.</strong>&nbsp;
      {d['ticker']} opened at {fmt(d['day_open'])}, reached a high of {fmt(d['day_high'])} and a low of {fmt(d['day_low'])}.
      Current price ({fmt(d['last'])}) is {d['ema_rel']}.
      RSI at {d['rsi']:.1f} is {d['rsi_label'].lower()}.
      MACD histogram is {"negative — momentum is bearish" if d['macd_hist'] < 0 else "positive — momentum is bullish"}.
    </div>
  </div>

  <!-- 2. Key Levels -->
  <div class="section">
    <h2><span>🗺️</span> 2. Key Support &amp; Resistance Levels</h2>
    <table>
      <tr><th>Level</th><th>Price</th><th>Type</th><th>Notes</th></tr>
      {lvl_rows}
    </table>
  </div>

  <!-- 3. IV -->
  <div class="section">
    <h2><span>🌡️</span> 3. Implied Volatility &amp; IV Rank</h2>
    <p>Data source: <strong>{d['iv_source']}</strong></p>
    <table>
      <tr><th>Metric</th><th>Value</th><th>Implication</th></tr>
      <tr><td>Intraday Range</td>
          <td><strong>{fmt(d['day_range'])} ({d['day_range']/d['day_open']*100:.2f}%)</strong></td>
          <td>{"Elevated move" if d['day_range']/d['day_open'] > 0.015 else "Normal range"} for {d['ticker']}</td></tr>
      {iv_rows_html}
    </table>
    <div class="note">
      {"At this elevated IV level, <strong>credit spreads and iron condors</strong> are preferred over naked debit buys." if d['est_ivr_high'] >= 55
       else "At this compressed IV level, <strong>debit spreads</strong> offer better risk/reward than credit strategies."}
      For precise IVR history, verify on Thinkorswim, Tastytrade, or IBKR.
    </div>
  </div>

  <!-- 4. PCR -->
  <div class="section">
    <h2><span>📊</span> 4. Put/Call Ratio &amp; Sentiment</h2>
    {pcr_html}
  </div>

  <!-- 5. Options Chain -->
  <div class="section">
    <h2><span>🔗</span> 5. Options Chain Snapshot — {chain_expiry_label}</h2>
    {chain_top_oi_html}
    <h3 style="font-size:13px;color:#8b949e;margin:12px 0 8px;">STRIKE MAP</h3>
    <table>
      <tr><th>Strike</th><th>Type</th><th>Role</th><th>Notes</th></tr>
      {chain_rows}
    </table>
    <div class="bias-box neutral" style="margin-top:16px;">
      <strong>Max Pain: {fmt(d['max_pain_est'])}{max_pain_badge}.</strong>
      {gamma_walls_text}
      Current price ({fmt(d['last'])}) is {"below" if d['last'] < d['max_pain_est'] else "above"} max pain —
      expect {"upward" if d['last'] < d['max_pain_est'] else "downward"} gravitational pull into close.
    </div>
  </div>

  <!-- 6. Strategy -->
  <div class="section">
    <h2><span>⚡</span> 6. Strategy Recommendation</h2>

    <div class="strategy-card">
      <h3>Strategy A — {d['strat_a_name']}</h3>
      <span class="tag {d['strat_a_tag_class']}">{d['strat_a_tag']}</span>
      <table>
        <tr><th>Parameter</th><th>Value</th></tr>
        {strat_a_html}
      </table>
    </div>

    <div class="strategy-card">
      <h3>Strategy B — Iron Condor</h3>
      <span class="tag">SECONDARY · Range / Theta Play</span>
      <p>Best if you believe {d['ticker']} stays range-bound into close.</p>
      <table>
        <tr><th>Wing</th><th>Sell</th><th>Buy</th></tr>
        <tr><td>Upper (Call)</td><td><strong>${d['ic_sell_call']:.2f} Call</strong></td><td><strong>${d['ic_buy_call']:.2f} Call</strong></td></tr>
        <tr><td>Lower (Put)</td><td><strong>${d['ic_sell_put']:.2f} Put</strong></td><td><strong>${d['ic_buy_put']:.2f} Put</strong></td></tr>
      </table>
      <table style="margin-top:10px;">
        <tr><th>Parameter</th><th>Value</th></tr>
        <tr><td>Net Credit (est.)</td><td><strong>${d['ic_credit_lo']:.2f} – ${d['ic_credit_hi']:.2f}</strong></td></tr>
        <tr><td>Max Profit Zone</td><td><strong>${d['ic_sell_put']:.2f} – ${d['ic_sell_call']:.2f} at expiry</strong></td></tr>
        <tr><td>Max Loss</td><td><strong>~${d['ic_max_loss']:.2f} / contract</strong></td></tr>
      </table>
    </div>
  </div>

  <!-- 7. Entry / Target / Stop -->
  <div class="section">
    <h2><span>🎯</span> 7. Entry, Target &amp; Stop-Loss</h2>
    <div class="two-col">
      <div>
        <h3 style="font-size:14px;color:#58a6ff;margin-bottom:12px;">Strategy A — {d['strat_a_name']}</h3>
        <table>
          <tr><th>Parameter</th><th>Value</th></tr>
          <tr><td>Entry Trigger</td><td><strong>{d['entry_a']}</strong></td></tr>
          <tr><td>Confirmation</td><td>RSI direction + EMA alignment</td></tr>
          <tr><td>Profit Target</td><td>{d['target_a']}</td></tr>
          <tr><td>Stop-Loss</td><td>{d['stop_a']}</td></tr>
          <tr><td>Time Stop</td><td>Exit by <strong>3:00 PM ET</strong></td></tr>
        </table>
      </div>
      <div>
        <h3 style="font-size:14px;color:#58a6ff;margin-bottom:12px;">Strategy B — Iron Condor</h3>
        <table>
          <tr><th>Parameter</th><th>Value</th></tr>
          <tr><td>Entry Window</td><td><strong>11:00 AM – 12:30 PM ET</strong></td></tr>
          <tr><td>Profit Target</td><td>50% of max credit</td></tr>
          <tr><td>Stop-Loss</td><td>Exit if price breaches ${d['ic_sell_call']:.2f} or ${d['ic_sell_put']:.2f}</td></tr>
          <tr><td>Time Stop</td><td>Let expire if inside profit zone at 3:45 PM ET</td></tr>
        </table>
      </div>
    </div>
  </div>

  <!-- 8. Risk -->
  <div class="section">
    <h2><span>⚠️</span> 8. Risk &amp; Invalidation</h2>
    <div class="two-col">
      <div>
        <h3 style="font-size:14px;color:#f85149;margin-bottom:12px;">Strategy A</h3>
        <table>
          <tr><th>Risk Factor</th><th>Detail</th></tr>
          <tr><td>Max Loss</td><td><strong>{d['max_risk_a']} per contract</strong></td></tr>
          <tr><td>Invalidation</td><td>{d['inval_a']}</td></tr>
          <tr><td>IV Risk</td><td>{"IV crush helps (short premium)" if d['est_ivr_high'] >= 55 else "IV expansion hurts (long premium)"}</td></tr>
          <tr><td>Time Decay</td><td>{"Theta works for you — let it run" if d['est_ivr_high'] >= 55 else "Exit before 3 PM ET to manage theta"}</td></tr>
          <tr><td>News Risk</td><td>Unexpected catalyst can gap through strikes</td></tr>
        </table>
      </div>
      <div>
        <h3 style="font-size:14px;color:#f85149;margin-bottom:12px;">Strategy B — Iron Condor</h3>
        <table>
          <tr><th>Risk Factor</th><th>Detail</th></tr>
          <tr><td>Max Loss</td><td><strong>~${d['ic_max_loss']:.2f}/contract if wing breached</strong></td></tr>
          <tr><td>Invalidation</td><td>Sustained move outside ${d['ic_sell_put']:.2f}–${d['ic_sell_call']:.2f}</td></tr>
          <tr><td>Macro Risk</td><td>Fed / economic data could spike volatility</td></tr>
          <tr><td>Whipsaw</td><td>Both wings tested if price oscillates</td></tr>
          <tr><td>Assignment Risk</td><td>Near zero; exit by 3:45 PM ET</td></tr>
        </table>
      </div>
    </div>
  </div>

  <!-- 5m Entry Trigger -->
  {_build_5m_section(d)}

  <!-- IV Momentum + Volume Anomaly (inline banners) -->
  {_build_iv_momentum_section(d)}
  {_build_vol_anomaly_inline(d)}

  <!-- Max Pain Gravity -->
  {_build_gravity_section(d)}

  <!-- Position Sizing -->
  {_build_position_size_section(d)}

  <!-- Volume Profile + Horizontal S/R -->
  {_build_vpoc_sr_section(d)}

  <!-- Delta-Adjusted OI (DAP) -->
  {_build_dap_section(d)}

  <!-- OI Changes -->
  {_build_oi_change_section(d)}

  <!-- Per-Expiry PCR -->
  {_build_expiry_pcr_section(d)}

  <!-- Strike Buy Pressure -->
  {_build_strike_pressure_section(d)}

  <!-- News Sentiment -->
  {_build_news_section(d)}

  <!-- Sector Rotation -->
  {_build_sector_rotation_section(d)}

  <!-- Unusual Whales Flow -->
  {_build_uw_flow_section(d)}

  <!-- Macro Context -->
  {_build_macro_section(d)}

  <!-- GEX -->
  {_build_gex_section(d)}

  <!-- Level 2 -->
  {_build_level2_section(d)}

  <!-- Backtest -->
  {_build_backtest_section(d)}

  <!-- Confidence Score -->
  {_build_confidence_section(d)}

  <!-- Summary -->
  <div class="section">
    <h2><span>📋</span> Trade Summary</h2>
    <div class="summary-grid">
      <div class="summary-item">
        <div class="s-label">Ticker</div>
        <div class="s-value" style="color:#58a6ff;">{d['ticker']}</div>
      </div>
      <div class="summary-item">
        <div class="s-label">Bias</div>
        <div class="s-value" style="color:{d['bias_color']};">{d['bias']}</div>
      </div>
      <div class="summary-item">
        <div class="s-label">Last Price</div>
        <div class="s-value">{fmt(d['last'])}</div>
      </div>
      <div class="summary-item">
        <div class="s-label">Primary Trade</div>
        <div class="s-value">{d['strat_a_name']}</div>
      </div>
      <div class="summary-item">
        <div class="s-label">Max Risk (Strat A)</div>
        <div class="s-value" style="color:#f85149;">{d['max_risk_a']}</div>
      </div>
      <div class="summary-item">
        <div class="s-label">Invalidation</div>
        <div class="s-value">{d['inval_a']}</div>
      </div>
      <div class="summary-item">
        <div class="s-label">IV Regime</div>
        <div class="s-value" style="color:{d['iv_color']};">{d['iv_regime']} (~{d['est_ivr_low']}–{d['est_ivr_high']}th pct)</div>
      </div>
      <div class="summary-item">
        <div class="s-label">Expiry</div>
        <div class="s-value">0DTE — {d['trading_date']}</div>
      </div>
    </div>
  </div>

  <div class="disclaimer">
    <strong>Disclaimer:</strong> This report is generated from public market data (yfinance) and is for educational/informational
    purposes only. IV, PCR, max pain, and exact options chain data must be verified on your broker platform before placing any
    trade. Options trading involves significant risk of loss and is not suitable for all investors. Past performance does not
    guarantee future results. This is not financial advice.
  </div>

</div>
</body>
</html>"""
    return html


# ─────────────────────────────────────────────────────────────────────────────
# 7. CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def _run_scan(tickers: list, args) -> None:
    """Scan multiple tickers and print a ranked summary table."""
    trading_date = date.fromisoformat(args.date) if args.date else date.today()
    expiry_date  = date.fromisoformat(args.expiry) if args.expiry else trading_date
    rows = []
    print(f"\n{'─'*80}")
    print(f"  MULTI-TICKER SCAN  |  Expiry: {expiry_date}  |  {len(tickers)} tickers")
    print(f"{'─'*80}\n")

    for sym in tickers:
        sym = sym.upper()
        print(f"  ⏳  Scanning {sym}…", end=" ", flush=True)
        try:
            df = fetch_intraday(sym, trading_date)
            df = add_indicators(df)
            df5 = resample_5m(df)
            prior_close = fetch_prior_close(sym, trading_date)
            pm_high, pm_low = fetch_premarket(sym, trading_date)
            chain = get_options_chain(sym, expiry_date)
            catalyst = get_catalyst_info(sym, expiry_date)
            stock_info = get_stock_info(sym)
            macro = get_macro_context(sym)
            a = analyse(sym, df, prior_close, pm_high, pm_low,
                        chain=chain, catalyst=catalyst,
                        stock_info=stock_info, df5=df5, macro=macro,
                        trading_style=getattr(args, "style", "spread") or "spread")
            rows.append({
                "ticker":     sym,
                "price":      f"${a['last']:.2f}",
                "bias":       a["bias"],
                "score":      a.get("conf_score", 50),
                "score_cls":  a.get("conf_cls", "neutral"),
                "atm_iv":     f"{chain['atm_iv']:.1f}%" if chain and chain.get("atm_iv") else "—",
                "pcr":        f"{chain['pcr_vol']:.2f}" if chain else "—",
                "max_pain":   f"${chain['max_pain']:.2f}" if chain and chain.get("max_pain") else "—",
                "skew":       f"{chain['skew_25d']:+.1f}%" if chain and chain.get("skew_25d") is not None else "—",
                "gex":        f"{chain['net_gex']:+,.0f}" if chain and chain.get("net_gex") is not None else "—",
                "sector":     macro.get("sector_etf") or "—",
                "sector_sig": macro.get("sector_signal", "")[:40] if macro.get("sector_signal") else "—",
                "vix":        f"{(macro.get('VIX') or {}).get('price','?')}",
                "risk":       "🚨 HIGH" if catalyst.get("high_risk") else "✅ OK",
            })
            print(f"score={a.get('conf_score',50)} ({a.get('conf_cls','?')})")
        except Exception as e:
            print(f"FAILED: {e}")
            rows.append({"ticker": sym, "score": -1, "bias": "Error"})

    # Sort by confidence score descending
    rows.sort(key=lambda r: r.get("score", -1), reverse=True)

    # Print ranked table
    print(f"\n{'─'*80}")
    print(f"  RANKED RESULTS  (highest confidence first)")
    print(f"{'─'*80}")
    header = f"{'#':<3} {'Ticker':<7} {'Price':<10} {'Score':<8} {'Bias':<22} {'IV':<8} {'PCR':<7} {'MaxPain':<10} {'Skew':<8} {'Risk'}"
    print(header)
    print("─" * len(header))
    for i, r in enumerate(rows, 1):
        if r.get("score", -1) < 0:
            print(f"{i:<3} {r['ticker']:<7} ERROR")
            continue
        marker = "▲" if r["score_cls"] == "bull" else "▼" if r["score_cls"] == "bear" else "─"
        print(f"{i:<3} {r['ticker']:<7} {r['price']:<10} {marker}{r['score']:<7} {r['bias']:<22} "
              f"{r['atm_iv']:<8} {r['pcr']:<7} {r['max_pain']:<10} {r['skew']:<8} {r['risk']}")

    print(f"\n  VIX: {rows[0].get('vix','?') if rows else '?'}  |  "
          f"Bull leaders: {', '.join(r['ticker'] for r in rows if r.get('score_cls')=='bull') or 'none'}  |  "
          f"Bear leaders: {', '.join(r['ticker'] for r in rows if r.get('score_cls')=='bear') or 'none'}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Generate a 0DTE options trading setup HTML report for any ticker."
    )
    parser.add_argument("ticker", nargs="?", default=None,
                        help="Stock ticker symbol, e.g. MSFT, CSCO, NVDA")
    parser.add_argument("--scan", nargs="+", metavar="TICKER",
                        help="Scan multiple tickers and output ranked summary table")
    parser.add_argument("--date", default=None,
                        help="Trading date YYYY-MM-DD (default: today)")
    parser.add_argument("--expiry", default=None,
                        help="Options expiry date YYYY-MM-DD (default: same as --date)")
    parser.add_argument("--output", default=None,
                        help="Output HTML file path (default: <ticker>_options_<date>.html)")
    parser.add_argument("--open", action="store_true",
                        help="Open the report in the default browser after generating")
    parser.add_argument("--ibkr", action="store_true",
                        help="Connect to IBKR TWS/Gateway for real-time Greeks (requires ib_insync + TWS running)")
    parser.add_argument("--ibkr-port", type=int, default=None,
                        help="TWS/Gateway port (default: 7497=paper TWS, 7496=live TWS, 4002=live Gateway)")
    parser.add_argument("--ibkr-live", action="store_true",
                        help="Use live TWS port 7496 instead of paper 7497")
    parser.add_argument("--account", type=float, default=25000,
                        help="Account size in USD for position sizing (default: 25000)")
    parser.add_argument("--risk", type=float, default=1.0,
                        help="Max risk per trade as %% of account (default: 1.0)")
    parser.add_argument("--uw-key", default=os.environ.get("UW_API_KEY"),
                        metavar="API_KEY",
                        help="Unusual Whales API key for real options flow direction "
                             "(or set UW_API_KEY env var). Get key at unusualwhales.com")
    parser.add_argument("--style", choices=["spread", "daytrader"], default=None,
                        help="Strategy style: 'spread' (credit/debit spreads + iron condor) "
                             "or 'daytrader' (single-leg call/put buy). Prompted if omitted.")
    args = parser.parse_args()

    # ── Prompt for trading style if not supplied via --style ──────────────────
    if args.style is None:
        print("\n┌─────────────────────────────────────────────────┐")
        print("│          Select Report / Strategy Style          │")
        print("├─────────────────────────────────────────────────┤")
        print("│  1  Day Trader  — single-leg call/put buy,       │")
        print("│                   intraday entry/exit            │")
        print("│  2  Spread      — credit/debit spreads +         │")
        print("│                   iron condor (multi-leg)        │")
        print("└─────────────────────────────────────────────────┘")
        while True:
            choice = input("Enter 1 or 2: ").strip()
            if choice == "1":
                args.style = "daytrader"
                break
            elif choice == "2":
                args.style = "spread"
                break
            else:
                print("Please enter 1 or 2.")

    if args.scan:
        _run_scan(args.scan, args)
        return

    if not args.ticker:
        parser.error("ticker is required unless --scan is used")

    ticker = args.ticker.upper()
    trading_date = (date.fromisoformat(args.date) if args.date else date.today())
    expiry_date  = (date.fromisoformat(args.expiry) if args.expiry else trading_date)

    # ── Detect and announce market session ───────────────────────────────────
    session = market_session()
    session_labels = {
        "premarket":  "🌅 PRE-MARKET  (04:00–09:29 ET) — using pre-market bars",
        "open":       "🟢 MARKET OPEN (09:30–16:00 ET) — using live session data",
        "afterhours": "🌙 AFTER HOURS (16:00–20:00 ET) — using full session data",
        "closed":     "🔴 MARKET CLOSED — using most recent session data",
    }
    print(f"\n  {session_labels.get(session, session)}\n")

    print(f"⏳  Fetching intraday data for {ticker} on {trading_date}…")
    df = fetch_intraday(ticker, trading_date)
    df = add_indicators(df)
    df5 = resample_5m(df)

    print(f"⏳  Fetching prior close…")
    prior_close = fetch_prior_close(ticker, trading_date)

    print(f"⏳  Fetching pre-market data…")
    pm_high, pm_low = fetch_premarket(ticker, trading_date)

    print(f"⏳  Fetching live options chain (expiry ≥ {expiry_date})…")
    chain = get_options_chain(ticker, expiry_date)
    if chain:
        print(f"    ✅  Chain loaded: expiry={chain['expiry_used']}, "
              f"max_pain=${chain['max_pain']}, ATM_IV={chain['atm_iv']}%, "
              f"PCR(vol)={chain['pcr_vol']}")
    else:
        print(f"    ⚠   Options chain unavailable — IV/PCR will be estimated.")

    # ── IBKR TWS overlay (real-time Greeks + IV) ─────────────────────────────
    ibkr_greeks = None
    if args.ibkr or args.ibkr_live:
        if not HAS_IB:
            print("    ⚠  ib_insync not installed. Run: pip3 install ib_insync")
        else:
            ibkr_port = args.ibkr_port or (7496 if args.ibkr_live else 7497)
            mode_label = "live TWS" if args.ibkr_live else "paper TWS"
            print(f"⏳  Connecting to IBKR {mode_label} (port {ibkr_port}) for real-time Greeks…")
            atm_for_ibkr = chain["atm_strike"] if chain and chain.get("atm_strike") else None
            if atm_for_ibkr:
                ibkr_greeks = get_greeks_ibkr(ticker, expiry_date, atm_for_ibkr, port=ibkr_port)
                if ibkr_greeks:
                    print(f"    ✅  IBKR Greeks: Δ={ibkr_greeks.get('call_delta')}, "
                          f"Γ={ibkr_greeks.get('call_gamma')}, "
                          f"Θ={ibkr_greeks.get('call_theta')}, "
                          f"V={ibkr_greeks.get('call_vega')}, "
                          f"IV={ibkr_greeks.get('call_iv')}%")
                    # Overlay IBKR Greeks onto chain dict
                    if chain:
                        chain["atm_delta"] = ibkr_greeks.get("call_delta")
                        chain["atm_gamma"] = ibkr_greeks.get("call_gamma")
                        chain["atm_theta"] = ibkr_greeks.get("call_theta")
                        chain["atm_vega"]  = ibkr_greeks.get("call_vega")
                        # Use IBKR IV if available (real-time vs yfinance 15-min delay)
                        if ibkr_greeks.get("call_iv"):
                            chain["atm_iv"] = ibkr_greeks["call_iv"]
                        chain["ibkr_connected"] = True
                        chain["ibkr_port"]      = ibkr_port
            else:
                print("    ⚠  ATM strike unknown — fetch chain first or specify --expiry")

    print(f"⏳  Checking catalyst calendar (earnings + FOMC)…")
    catalyst = get_catalyst_info(ticker, expiry_date)
    if catalyst["alerts"]:
        for alert in catalyst["alerts"]:
            print(f"    {alert}")
    else:
        print(f"    ✅  No high-impact events within 5 days of expiry.")

    print(f"⏳  Fetching stock info (PDH/PDL, short interest)…")
    stock_info = get_stock_info(ticker)

    print(f"⏳  Fetching macro context (SPY/QQQ/VIX/TLT/DXY/futures/sector ETF)…")
    macro = get_macro_context(ticker)
    vix_p = (macro.get("VIX") or {}).get("price", "?")
    spy_d = (macro.get("SPY") or {}).get("pct_chg", "?")
    qqq_d = (macro.get("QQQ") or {}).get("pct_chg", "?")
    nq_d  = (macro.get("NQ_F") or {}).get("pct_chg", "?")
    sec   = macro.get("sector_etf") or "N/A"
    if isinstance(spy_d, (int, float)) and isinstance(qqq_d, (int, float)) and isinstance(nq_d, (int, float)):
        print(f"    ✅  VIX={vix_p}, SPY={spy_d:+.2f}%, QQQ={qqq_d:+.2f}%, /NQ={nq_d:+.2f}%, Sector={sec}")
    else:
        print(f"    ✅  Macro fetched (VIX={vix_p}, Sector={sec})")

    # News sentiment
    print(f"⏳  Fetching news sentiment…")
    news = get_news_sentiment(ticker)
    if news.get("signal"):
        print(f"    📰 News: {news['signal']}")
    else:
        print(f"    ℹ  No recent scored headlines")

    # OI change detection (overnight new money)
    if chain:
        try:
            tk_oi = yf.Ticker(ticker)
            ch_oi = tk_oi.option_chain(chain["expiry_used"])
            oi_changes = get_oi_changes(ticker, chain["expiry_used"],
                                        ch_oi.calls.fillna(0), ch_oi.puts.fillna(0))
            chain["oi_changes"] = oi_changes
            if oi_changes:
                print(f"    📈 OI changes: {len(oi_changes)} strikes with significant overnight moves")
                for oc in oi_changes[:3]:
                    print(f"       ${oc['strike']:.0f} — {oc['signal']}")
        except Exception:
            pass

    # IV momentum (compare to cached yesterday)
    iv_momentum = {}
    if chain and chain.get("atm_iv"):
        iv_momentum = get_iv_momentum(ticker, chain["expiry_used"], chain["atm_iv"])
        if iv_momentum.get("iv_change") is not None:
            print(f"    📊 IV momentum: {iv_momentum['iv_momentum']}")

    # DAP (delta-adjusted OI) — needs DTE
    if chain and chain.get("atm_iv") and chain.get("spot"):
        try:
            exp_d = date.fromisoformat(chain["expiry_used"])
            dte_dap = max((exp_d - date.today()).days, 1)
            T_dap = dte_dap / 252
            tk_tmp = yf.Ticker(ticker)
            ch_tmp = tk_tmp.option_chain(chain["expiry_used"])
            calls_dap = ch_tmp.calls.fillna(0)
            puts_dap  = ch_tmp.puts.fillna(0)
            chain["dap"] = compute_dap(calls_dap, puts_dap, chain["spot"], T_dap)
        except Exception:
            pass

    # Max pain gravity score
    gravity = {}
    if chain and chain.get("max_pain") and chain.get("spot"):
        exp_d2 = date.fromisoformat(chain["expiry_used"])
        dte_g  = max((exp_d2 - date.today()).days, 0)
        gravity = compute_max_pain_gravity(chain["spot"], chain["max_pain"], dte_g)
        if gravity:
            print(f"    🎯 Max pain gravity: {gravity['label']}")

    # Volume anomaly
    vol_anomaly = compute_volume_anomaly(df)
    if vol_anomaly.get("vs_session", 1) > 1.5:
        print(f"    {vol_anomaly['signal']}")

    print(f"⏳  Computing Volume Profile (VPOC/VAH/VAL)…")
    vpoc_data = compute_vpoc(df)
    if vpoc_data:
        print(f"    ✅  VPOC=${vpoc_data['vpoc']}, VAH=${vpoc_data['vah']}, VAL=${vpoc_data['val']}")

    print(f"⏳  Detecting horizontal S/R levels ({60}d history)…")
    sr_levels = get_horizontal_sr(ticker, lookback_days=60)
    print(f"    ✅  Found {len(sr_levels)} S/R levels")

    print(f"⏳  Running backtest (120d technical signal history)…")
    bt = backtest_technicals(ticker, lookback_days=120)
    if bt.get("bull"):
        print(f"    ✅  Bull signal win rate: {bt['bull']['win_rate']}% ({bt['bull']['count']} samples), "
              f"Bear: {(bt.get('bear') or {}).get('win_rate','?')}%")

    # Optional IBKR Level 2
    level2 = None
    if (args.ibkr or args.ibkr_live) and HAS_IB:
        ibkr_port = args.ibkr_port or (7496 if args.ibkr_live else 7497)
        print(f"⏳  Fetching Level 2 market depth from IBKR (port {ibkr_port})…")
        level2 = get_level2_ibkr(ticker, port=ibkr_port)
        if level2:
            print(f"    ✅  L2: bid/ask ratio={level2['bid_ask_ratio']} — {level2['l2_signal']}")

    # Position sizing (uses analysis bias + chain debit estimate)
    position_size = {}
    if chain and chain.get("atm_iv"):
        # Estimate debit for ATM spread as ~40% of spread width
        spread_width = round((chain.get("spot") or 100) * 0.025, 2)
        est_debit    = round(spread_width * 0.40, 2)
        est_max_loss = round(spread_width - est_debit, 2)
        position_size = compute_position_size(
            last=chain.get("spot", 100),
            strategy="debit_spread",
            debit_or_credit=est_debit,
            max_loss_per_contract=est_max_loss,
            account_size=args.account,
            risk_pct=args.risk,
        )
        if position_size:
            print(f"    💰 Position size: {position_size['max_contracts']} contracts "
                  f"(risk ${position_size['total_risk']:,.0f} = {args.risk}% of ${args.account:,.0f})")

    # Unusual Whales options flow (requires API key)
    uw_flow = {}
    if args.uw_key:
        print(f"⏳  Fetching Unusual Whales options flow for {ticker}…")
        uw_flow = get_uw_flow(ticker, chain["expiry_used"] if chain else None, args.uw_key)
        if uw_flow.get("error"):
            print(f"    ⚠  UW flow error: {uw_flow['error']}")
        else:
            print(f"    🐋 UW flow: {uw_flow['signal']} "
                  f"(bull {uw_flow['bull_pct']}% / bear {uw_flow['bear_pct']}%, "
                  f"{uw_flow['sweep_bull']} bull sweeps, {uw_flow['sweep_bear']} bear sweeps)")
    else:
        print(f"    ℹ  Unusual Whales flow skipped — add --uw-key YOUR_KEY (or UW_API_KEY env var)")

    print(f"⏳  Running analysis…")
    analysis = analyse(ticker, df, prior_close, pm_high, pm_low,
                       chain=chain, catalyst=catalyst, stock_info=stock_info,
                       df5=df5, macro=macro, sr_levels=sr_levels,
                       vpoc=vpoc_data, backtest=bt, level2=level2,
                       iv_momentum=iv_momentum, gravity=gravity,
                       vol_anomaly=vol_anomaly, position_size=position_size,
                       uw_flow=uw_flow, news=news,
                       trading_style=args.style)

    # Try to get company name
    try:
        info = yf.Ticker(ticker).info
        analysis["company"] = info.get("longName", ticker)
    except Exception:
        analysis["company"] = ticker

    html = build_html(analysis)

    out_path = args.output or f"{ticker}_options_{trading_date}.html"
    out_path = os.path.expanduser(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅  Report saved → {out_path}")

    if args.open:
        webbrowser.open(f"file://{os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
