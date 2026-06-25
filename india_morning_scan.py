"""
India Morning Watchlist Scanner
Fetches NSE data: delivery %, FII/DII, technicals, fundamentals
Run every morning before market open (8-9 AM)
"""

import requests
import pandas as pd
import yfinance as yf
import json
import time
import warnings
from datetime import datetime, timedelta
from tabulate import tabulate
from colorama import Fore, Back, Style, init

warnings.filterwarnings("ignore")
init(autoreset=True)

# ============================================================
# CONFIG
# ============================================================
WATCHLIST = [
    # From TradingView watchlist (Indian_39434)
    "APOLLO", "LUMAXTECH", "LAURUSLABS", "UNITDSPR", "ASTRAL",
    "SYRMA", "HDFCBANK", "RAIN", "REFEX",
    # Adani Group
    "ADANIPOWER", "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ADANIENSOL",
    # Misc
    "PREMEXPLN", "SOLARINDS",
    # Section 1
    "FCL", "CHAMBLFERT", "SPARC", "NAVKARCORP", "AMBUJACEM",
    "SUZLON", "KPITTECH", "DEEPAKFERT", "PRICOLLTD", "M&M",
    "LT", "UNOMINDA", "EICHERMOT", "HAL", "MAZDOCK",
    "MARKSANS", "TITAN", "RAMCOSYS", "WHEELS", "CEATLTD",
    "TRENT", "SUNPHARMA", "KAYNES", "DIXON", "KEC",
    "FORTIS", "SALZERELEC", "BRIGADE", "SHILCTECH", "OLAELEC",
    "NATCOPHARM", "JAGSNPHARM", "ALICON", "HITECH", "SUBROS", "WENDT",
    # BSE-only extras kept as NSE equivalents where possible
    "YASHHV", "BONDADA",
]

# Yahoo Finance uses .NS suffix; some symbols differ from NSE display names
YF_SYMBOL_MAP = {
    "M&M":      "M%26M.NS",
    "LT":       "LT.NS",
    "APOLLO":   "APOLLOHOSP.NS",
    "WHEELS":   "WHEELS.NS",
    "YASHHV":   "YASHHV.BO",
    "BONDADA":  "BONDADA.BO",
    "PRICOLLTD":"PRICOLLTD.NS",
    "PREMEXPLN":"PREMEXPLN.NS",
}

MIN_DELIVERY_PCT  = 40.0   # minimum delivery % for quality trades
MIN_SCORE         = 5      # minimum score out of 10 to appear in watchlist
TOP_N             = 10     # number of stocks in final watchlist

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# ============================================================
# NSE SESSION
# ============================================================
def get_nse_session():
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=10)
        session.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
    except Exception:
        pass
    return session

# ============================================================
# FETCH DELIVERY % FROM NSE
# ============================================================
def fetch_delivery(session, symbol):
    try:
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}&section=trade_info"
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            mkt = data.get("marketDeptOrderBook", {})
            trd = data.get("securityWiseDP", {})
            delv_qty = trd.get("deliveryQuantity", 0)
            trd_qty  = trd.get("tradedQuantity",   0)
            delv_pct = trd.get("deliveryToTradedQuantity", 0)
            return {
                "delivery_pct": float(delv_pct) if delv_pct else 0.0,
                "traded_qty":   trd_qty,
            }
    except Exception:
        pass
    return {"delivery_pct": 0.0, "traded_qty": 0}

# ============================================================
# FETCH FII/DII DATA FROM NSE
# ============================================================
def fetch_fii_dii(session):
    try:
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                latest = data[0]
                fii_net = float(latest.get("fiiNet", 0))
                dii_net = float(latest.get("diiNet", 0))
                date    = latest.get("date", "")
                return {
                    "fii_net": fii_net,
                    "dii_net": dii_net,
                    "date":    date,
                    "fii_buy": float(latest.get("fiiBuy",  0)),
                    "fii_sell":float(latest.get("fiiSell", 0)),
                    "dii_buy": float(latest.get("diiBuy",  0)),
                    "dii_sell":float(latest.get("diiSell", 0)),
                }
    except Exception:
        pass
    return {"fii_net": 0.0, "dii_net": 0.0, "date": "N/A"}

# ============================================================
# FETCH PCR (PUT CALL RATIO) FROM NSE
# ============================================================
def fetch_pcr(session, symbol="NIFTY"):
    try:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            filtered = data.get("filtered", {})
            ce_oi = filtered.get("CE", {}).get("totOI", 0)
            pe_oi = filtered.get("PE", {}).get("totOI", 0)
            pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else 0.0
            return pcr
    except Exception:
        pass
    return 0.0

# ============================================================
# FETCH PRICE + TECHNICALS VIA YFINANCE
# ============================================================
def fetch_technicals(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, f"{symbol}.NS")
        ticker = yf.Ticker(yf_sym)
        df = ticker.history(period="1y", interval="1d")

        if df.empty or len(df) < 50:
            return None

        df = df.copy()
        c = df["Close"]
        h = df["High"]
        l = df["Low"]
        v = df["Volume"]

        # EMAs
        ema21  = c.ewm(span=21,  adjust=False).mean()
        ema50  = c.ewm(span=50,  adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()

        # RSI
        delta = c.diff()
        gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
        loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
        rs    = gain / loss
        rsi   = 100 - (100 / (1 + rs))

        # Volume avg
        vol_avg  = v.rolling(20).mean()
        vol_surge = float(v.iloc[-1]) > float(vol_avg.iloc[-1]) * 1.5

        # 52W high/low
        high_52w = h.rolling(252).max().iloc[-1]
        low_52w  = l.rolling(252).min().iloc[-1]

        # BB squeeze
        bb_mid   = c.rolling(20).mean()
        bb_std   = c.rolling(20).std()
        bb_width = (bb_mid + 2*bb_std - (bb_mid - 2*bb_std)) / bb_mid
        bb_sq    = float(bb_width.iloc[-1]) < float(bb_width.rolling(50).min().iloc[-1]) * 1.1

        # ADX (simplified)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()

        price_now = float(c.iloc[-1])
        e21  = float(ema21.iloc[-1])
        e50  = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])

        bull = e21 > e50 and e50 > e200
        bear = e21 < e50 and e50 < e200

        # Distance from 200 DMA
        dma_dist = (price_now - e200) / e200 * 100 if e200 > 0 else 0

        # Near 52W high breakout
        near_52w = price_now >= high_52w * 0.98

        # Weekly trend (last 5 bars)
        w_close  = float(c.iloc[-1])
        w_ema21  = float(ema21.iloc[-5]) if len(ema21) > 5 else e21
        weekly_bull = w_close > w_ema21

        return {
            "price":       price_now,
            "ema21":       e21,
            "ema50":       e50,
            "ema200":      e200,
            "rsi":         float(rsi.iloc[-1]),
            "vol_surge":   vol_surge,
            "atr":         float(atr14.iloc[-1]),
            "bb_squeeze":  bb_sq,
            "high_52w":    float(high_52w),
            "low_52w":     float(low_52w),
            "dma_dist":    dma_dist,
            "near_52w":    near_52w,
            "bull_trend":  bull,
            "bear_trend":  bear,
            "weekly_bull": weekly_bull,
            "pct_change":  float(c.pct_change().iloc[-1] * 100),
            "volume":      float(v.iloc[-1]),
        }
    except Exception as e:
        return None

# ============================================================
# FETCH FUNDAMENTALS VIA YFINANCE
# ============================================================
def fetch_fundamentals(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, f"{symbol}.NS")
        ticker = yf.Ticker(yf_sym)
        info   = ticker.info
        return {
            "pe":          info.get("trailingPE",         None),
            "roe":         info.get("returnOnEquity",     None),
            "debt_eq":     info.get("debtToEquity",       None),
            "eps":         info.get("trailingEps",        None),
            "market_cap":  info.get("marketCap",          None),
            "sector":      info.get("sector",             "N/A"),
            "analyst_rec": info.get("recommendationKey",  "N/A"),
            "target_price":info.get("targetMeanPrice",    None),
            "revenue_gr":  info.get("revenueGrowth",      None),
            "earn_gr":     info.get("earningsGrowth",     None),
        }
    except Exception:
        return {}

# ============================================================
# SCORE EACH STOCK (out of 10)
# ============================================================
def score_stock(tech, fund, delv, fii_dii, pcr):
    score  = 0
    flags  = []

    if not tech:
        return 0, []

    # Technical (5 points)
    if tech.get("bull_trend"):
        score += 1; flags.append("Bull Trend")
    if tech.get("weekly_bull"):
        score += 1; flags.append("Weekly Bull")
    if tech.get("rsi", 100) < 70 and tech.get("rsi", 0) > 40:
        score += 1; flags.append(f"RSI {tech['rsi']:.0f}")
    if tech.get("vol_surge"):
        score += 1; flags.append("Vol Surge")
    if tech.get("bb_squeeze"):
        score += 1; flags.append("BB Squeeze")

    # Delivery & FII (3 points)
    if delv.get("delivery_pct", 0) >= MIN_DELIVERY_PCT:
        score += 1; flags.append(f"Delv {delv['delivery_pct']:.0f}%")
    if fii_dii.get("fii_net", 0) > 0:
        score += 1; flags.append("FII Buying")
    if fii_dii.get("dii_net", 0) > 0:
        score += 1; flags.append("DII Buying")

    # Fundamentals (2 points)
    roe = fund.get("roe")
    pe  = fund.get("pe")
    if roe and roe > 0.12:
        score += 1; flags.append(f"ROE {roe*100:.0f}%")
    if pe and 5 < pe < 50:
        score += 1; flags.append(f"PE {pe:.0f}")

    return score, flags

# ============================================================
# SETUP DETECTION
# ============================================================
def detect_setup(tech):
    if not tech:
        return "N/A"
    setups = []
    p  = tech["price"]
    if tech.get("near_52w"):
        setups.append("52W Breakout")
    if tech.get("bb_squeeze"):
        setups.append("BB Squeeze")
    if tech.get("bull_trend") and abs(p - tech["ema21"]) / p < 0.015:
        setups.append("EMA Pullback")
    if tech.get("rsi", 100) < 40 and tech.get("bull_trend"):
        setups.append("Oversold Bounce")
    return ", ".join(setups) if setups else "Trend Following"

# ============================================================
# CALCULATE SL & TARGET
# ============================================================
def calc_levels(tech, capital=500000, risk_pct=1.0, rr=2.0):
    if not tech:
        return None, None, None
    atr   = tech.get("atr", 0)
    price = tech.get("price", 0)
    low52 = tech.get("low_52w", price * 0.9)
    sl    = round(price - atr * 1.5, 2)
    tp    = round(price + (price - sl) * rr, 2)
    risk  = capital * risk_pct / 100
    qty   = int(risk / (price - sl)) if (price - sl) > 0 else 0
    return sl, tp, qty

# ============================================================
# MAIN SCAN
# ============================================================
def run_morning_scan():
    print(f"\n{Back.BLUE}{Fore.WHITE}{'='*65}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}   INDIA MORNING WATCHLIST SCAN — {datetime.now().strftime('%d %b %Y %I:%M %p')}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'='*65}{Style.RESET_ALL}\n")

    # Step 1: NSE session + market data
    print(f"{Fore.CYAN}[1/4] Connecting to NSE...{Style.RESET_ALL}")
    session = get_nse_session()
    time.sleep(1)

    # Step 2: FII/DII + PCR (market-wide)
    print(f"{Fore.CYAN}[2/4] Fetching FII/DII data & PCR...{Style.RESET_ALL}")
    fii_dii = fetch_fii_dii(session)
    pcr     = fetch_pcr(session, "NIFTY")
    time.sleep(1)

    # Market sentiment
    fii_net = fii_dii.get("fii_net", 0)
    dii_net = fii_dii.get("dii_net", 0)
    market_sentiment = "BULLISH" if fii_net > 0 and dii_net > 0 else \
                       "BEARISH" if fii_net < 0 and dii_net < 0 else "MIXED"

    # Step 3: Scan each stock
    print(f"{Fore.CYAN}[3/4] Scanning {len(WATCHLIST)} stocks...{Style.RESET_ALL}")
    results = []

    for i, symbol in enumerate(WATCHLIST):
        print(f"  {Fore.WHITE}{i+1:2d}/{len(WATCHLIST)} {symbol:<15}{Style.RESET_ALL}", end="", flush=True)

        tech   = fetch_technicals(symbol)
        fund   = fetch_fundamentals(symbol)
        delv   = fetch_delivery(session, symbol)
        score, flags = score_stock(tech, fund, delv, fii_dii, pcr)
        setup  = detect_setup(tech)
        sl, tp, qty = calc_levels(tech)

        if tech:
            chg = tech.get("pct_change", 0)
            chg_str = f"{Fore.GREEN}+{chg:.1f}%{Style.RESET_ALL}" if chg > 0 else f"{Fore.RED}{chg:.1f}%{Style.RESET_ALL}"
            print(f" ₹{tech['price']:>8.2f} {chg_str}  Score: {score}/10  {setup}")
        else:
            print(f"  {Fore.YELLOW}No data{Style.RESET_ALL}")

        if score >= MIN_SCORE and tech:
            results.append({
                "Symbol":    symbol,
                "Price":     f"₹{tech['price']:.2f}",
                "Change":    f"{tech['pct_change']:+.1f}%",
                "Score":     f"{score}/10",
                "RSI":       f"{tech['rsi']:.0f}",
                "Trend":     "BULL" if tech["bull_trend"] else "BEAR" if tech["bear_trend"] else "NEUT",
                "Delivery%": f"{delv['delivery_pct']:.0f}%",
                "DMA Dist":  f"{tech['dma_dist']:+.1f}%",
                "Setup":     setup,
                "SL":        f"₹{sl}" if sl else "N/A",
                "Target":    f"₹{tp}" if tp else "N/A",
                "Qty":       str(qty) if qty else "N/A",
                "Flags":     " | ".join(flags[:3]),
                "_score":    score,
                "_rsi":      tech["rsi"],
            })

        time.sleep(0.5)

    # Step 4: Sort and display
    print(f"\n{Fore.CYAN}[4/4] Generating watchlist...{Style.RESET_ALL}\n")
    results.sort(key=lambda x: x["_score"], reverse=True)
    top = results[:TOP_N]

    # ── MARKET OVERVIEW ──
    print(f"{Back.BLUE}{Fore.WHITE} MARKET OVERVIEW {Style.RESET_ALL}")
    mkt_color = Fore.GREEN if market_sentiment == "BULLISH" else Fore.RED if market_sentiment == "BEARISH" else Fore.YELLOW
    print(f"  Sentiment  : {mkt_color}{market_sentiment}{Style.RESET_ALL}")
    fii_color = Fore.GREEN if fii_net > 0 else Fore.RED
    dii_color = Fore.GREEN if dii_net > 0 else Fore.RED
    print(f"  FII Net    : {fii_color}₹{fii_net:,.0f} Cr{Style.RESET_ALL}  ({fii_dii.get('date','N/A')})")
    print(f"  DII Net    : {dii_color}₹{dii_net:,.0f} Cr{Style.RESET_ALL}")
    pcr_color = Fore.GREEN if pcr > 1.0 else Fore.RED if pcr < 0.7 else Fore.YELLOW
    pcr_note  = "Oversold (Bullish)" if pcr > 1.2 else "Overbought (Bearish)" if pcr < 0.7 else "Neutral"
    print(f"  Nifty PCR  : {pcr_color}{pcr} — {pcr_note}{Style.RESET_ALL}")
    print()

    # ── WATCHLIST TABLE ──
    if top:
        display_cols = ["Symbol","Price","Change","Score","RSI","Trend","Delivery%","DMA Dist","Setup","SL","Target","Qty"]
        display_data = [{k: v for k, v in r.items() if k in display_cols} for r in top]

        print(f"{Back.GREEN}{Fore.BLACK} TOP {len(top)} SWING TRADE CANDIDATES {Style.RESET_ALL}")
        print(tabulate(display_data, headers="keys", tablefmt="rounded_outline"))
        print()

        # ── DETAILED BREAKDOWN ──
        print(f"{Back.BLUE}{Fore.WHITE} SIGNAL BREAKDOWN {Style.RESET_ALL}")
        for r in top:
            score_val = r["_score"]
            bar = "█" * score_val + "░" * (10 - score_val)
            color = Fore.GREEN if score_val >= 7 else Fore.YELLOW if score_val >= 5 else Fore.RED
            print(f"  {color}{r['Symbol']:<15}{Style.RESET_ALL} [{bar}] {score_val}/10  {r['Flags']}")
        print()

        # ── TOP PICK ──
        if top:
            best = top[0]
            print(f"{Back.GREEN}{Fore.BLACK} TOP PICK: {best['Symbol']} {Style.RESET_ALL}")
            print(f"  Price    : {best['Price']}  ({best['Change']})")
            print(f"  Setup    : {best['Setup']}")
            print(f"  Score    : {best['Score']}")
            print(f"  Stop Loss: {best['SL']}")
            print(f"  Target   : {best['Target']}")
            print(f"  Quantity : {best['Qty']} shares")
            print(f"  Signals  : {best['Flags']}")
            print()
    else:
        print(f"{Fore.YELLOW}No stocks met the minimum score of {MIN_SCORE}/10 today.{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}Consider lowering MIN_SCORE in config.{Style.RESET_ALL}\n")

    # ── AVOID LIST ──
    avoid = [r for r in results if r["_score"] < MIN_SCORE and r.get("Trend") == "BEAR"]
    if avoid:
        print(f"{Back.RED}{Fore.WHITE} STOCKS TO AVOID (Bearish) {Style.RESET_ALL}")
        for r in avoid[:5]:
            print(f"  {Fore.RED}{r['Symbol']:<15}{Style.RESET_ALL} Score:{r['Score']}  {r['Trend']}  RSI:{r['RSI']}")
        print()

    print(f"{Fore.CYAN}Scan complete. {len(results)} stocks qualified out of {len(WATCHLIST)} scanned.{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Run this script daily at 8-9 AM before market opens.{Style.RESET_ALL}\n")

    # Save to CSV
    if results:
        today = datetime.now().strftime("%Y-%m-%d")
        fname = f"watchlist_{today}.csv"
        df = pd.DataFrame(results).drop(columns=["_score","_rsi"])
        df.to_csv(fname, index=False)
        print(f"{Fore.GREEN}Saved to {fname}{Style.RESET_ALL}\n")

    return results

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    run_morning_scan()
