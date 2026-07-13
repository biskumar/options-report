"""
Deep Stock Analyzer
Fetches data from screener.in + groww.in + yfinance
Usage: python3.12 stock_analyzer.py SYMBOL
       python3.12 stock_analyzer.py ADANIENT
"""

import sys
import re
import time
import warnings
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from colorama import Fore, Back, Style, init

warnings.filterwarnings("ignore")
init(autoreset=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── SCREENER.IN ────────────────────────────────────────────

def fetch_screener(symbol):
    """Scrape key fundamentals from screener.in"""
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            # Try standalone (non-consolidated)
            url = f"https://www.screener.in/company/{symbol}/"
            r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, url

        soup = BeautifulSoup(r.text, "html.parser")
        data = {}

        # ── Top ratios (the pill badges at top)
        ratios = soup.select("#top-ratios li")
        for item in ratios:
            name_el = item.select_one(".name")
            val_el  = item.select_one(".number, .value")
            if name_el and val_el:
                key = name_el.get_text(strip=True)
                val = val_el.get_text(strip=True).replace(",","").replace("₹","").strip()
                data[key] = val

        # ── Shareholding pattern (latest quarter)
        sh_table = soup.find("table", {"class": re.compile("data-table")})
        promoter_holding = None
        fii_holding      = None
        dii_holding      = None

        sh_section = soup.find("section", {"id": "shareholding"})
        if sh_section:
            tables = sh_section.find_all("table")
            for tbl in tables:
                rows = tbl.find_all("tr")
                for row in rows:
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if not cells: continue
                    label = cells[0].lower()
                    val   = cells[-1].replace("%","").strip() if len(cells) > 1 else None
                    if "promoter" in label and "pledged" not in label:
                        promoter_holding = val
                    elif "fii" in label or "foreign" in label:
                        fii_holding = val
                    elif "dii" in label or "domestic inst" in label:
                        dii_holding = val

        data["Promoter Holding"] = f"{promoter_holding}%" if promoter_holding else "N/A"
        data["FII Holding"]      = f"{fii_holding}%"      if fii_holding      else "N/A"
        data["DII Holding"]      = f"{dii_holding}%"      if dii_holding      else "N/A"

        # ── Quarterly results (last 4 quarters)
        quarterly = {}
        q_section = soup.find("section", {"id": "quarters"})
        if q_section:
            tbl = q_section.find("table")
            if tbl:
                headers_row = [th.get_text(strip=True) for th in tbl.find_all("th")]
                for row in tbl.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells: continue
                    label = cells[0].get_text(strip=True)
                    vals  = [c.get_text(strip=True).replace(",","") for c in cells[1:]]
                    if label in ("Sales", "Net Profit", "EPS"):
                        quarterly[label] = dict(zip(headers_row[1:], vals))

        data["Quarterly"] = quarterly

        # ── Profit & Loss highlights (annual)
        annual = {}
        pl_section = soup.find("section", {"id": "profit-loss"})
        if pl_section:
            tbl = pl_section.find("table")
            if tbl:
                headers_row = [th.get_text(strip=True) for th in tbl.find_all("th")]
                for row in tbl.find_all("tr"):
                    cells = row.find_all("td")
                    if not cells: continue
                    label = cells[0].get_text(strip=True)
                    vals  = [c.get_text(strip=True).replace(",","") for c in cells[1:]]
                    if label in ("Sales", "Net Profit", "EPS", "Dividend Payout %"):
                        annual[label] = dict(zip(headers_row[1:], vals))

        data["Annual"] = annual

        return data, url

    except Exception as e:
        return None, str(e)


# ─── MONEYCONTROL ───────────────────────────────────────────

# Map NSE symbols to Moneycontrol search slugs
MC_SLUG_MAP = {
    "ADANIENT":   "adani-enterprises/ADE",
    "ADANIPOWER": "adani-power/ADP",
    "ADANIPORTS": "adani-ports-special-economic-zone/APSE",
    "ADANIGREEN": "adani-green-energy/ADANIGRE",
    "ADANIENSOL": "adani-energy-solutions/ADANIENSOL",
    "HDFCBANK":   "hdfc-bank/HDF02",
    "RELIANCE":   "reliance-industries/RI",
    "INFY":       "infosys/IT",
    "TCS":        "tata-consultancy-services/TCS",
    "LAURUSLABS": "laurus-labs/LL",
    "LUMAXTECH":  "lumax-auto-technologies/LAT",
    "SUNPHARMA":  "sun-pharmaceutical-industries/SP1",
    "DIXON":      "dixon-technologies-india/DT",
    "SUZLON":     "suzlon-energy/SE3",
    "LT":         "larsen-toubro/LT",
    "EICHERMOT":  "eicher-motors/EM",
    "HAL":        "hindustan-aeronautics/HAL",
    "TITAN":      "titan-company/TC",
    "KPITTECH":   "kpit-technologies/KPITTECH",
    "M&M":        "mahindra-mahindra/MM",
}

def fetch_moneycontrol(symbol):
    """Fetch analyst ratings and targets from Moneycontrol"""
    slug = MC_SLUG_MAP.get(symbol)
    if not slug:
        # Try generic search
        try:
            search_url = f"https://www.moneycontrol.com/stocks/cptmarket/compsearchnew.php?search_data={symbol}&cid=&mbsearch_str=&topsearch_type=1&search_str={symbol}"
            r = requests.get(search_url, headers=HEADERS, timeout=10)
            # Just return None if not in map — avoids wrong matches
        except Exception:
            pass
        return None, f"https://www.moneycontrol.com (no slug for {symbol})"

    url = f"https://www.moneycontrol.com/india/stockpricequote/miscellaneous/{slug}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None, url

        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        data = {"url": url}

        # ── Analyst ratings (cap at 99 to avoid year matches like 2026)
        def safe_analyst(m):
            if not m: return "N/A"
            val = int(m.group(1))
            return str(val) if val <= 99 else "N/A"

        buy_m  = re.search(r"(\d{1,2})\s*(?:analysts?\s*)?(?:recommend\s*)?Buy",  text, re.IGNORECASE)
        hold_m = re.search(r"(\d{1,2})\s*(?:analysts?\s*)?(?:recommend\s*)?Hold", text, re.IGNORECASE)
        sell_m = re.search(r"(\d{1,2})\s*(?:analysts?\s*)?(?:recommend\s*)?Sell", text, re.IGNORECASE)
        data["Analyst Buy"]  = safe_analyst(buy_m)
        data["Analyst Hold"] = safe_analyst(hold_m)
        data["Analyst Sell"] = safe_analyst(sell_m)

        # ── Target price
        tgt_m = re.search(r"Target\s*(?:Price)?[:\s]*Rs\.?\s*([0-9,]+)", text, re.IGNORECASE)
        if not tgt_m:
            tgt_m = re.search(r"Avg\.\s*Target[:\s]*Rs\.?\s*([0-9,]+)", text, re.IGNORECASE)
        data["Analyst Target"] = f"₹{tgt_m.group(1)}" if tgt_m else "N/A"

        # ── 52W
        h52_m = re.search(r"52\s*Week\s*High[:\s]*([0-9,]+\.?[0-9]*)", text, re.IGNORECASE)
        l52_m = re.search(r"52\s*Week\s*Low[:\s]*([0-9,]+\.?[0-9]*)",  text, re.IGNORECASE)
        data["52W High"] = f"₹{h52_m.group(1)}" if h52_m else "N/A"
        data["52W Low"]  = f"₹{l52_m.group(1)}" if l52_m else "N/A"

        # ── P/E
        pe_m = re.search(r"P/E\s*(?:Ratio)?[:\s]*([0-9.]+)", text, re.IGNORECASE)
        data["P/E"] = pe_m.group(1) if pe_m else "N/A"

        return data, url

    except Exception as e:
        return None, str(e)


# ─── TIJORI / TICKERTAPE FALLBACK ──────────────────────────

def fetch_tickertape(symbol):
    """Fetch analyst data from tickertape.in as fallback"""
    url = f"https://www.tickertape.in/stocks/{symbol.lower()}-NSE"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return None, url
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        data = {}

        buy_m  = re.search(r"(\d+)\s*Buy",  text, re.IGNORECASE)
        hold_m = re.search(r"(\d+)\s*Hold", text, re.IGNORECASE)
        sell_m = re.search(r"(\d+)\s*Sell", text, re.IGNORECASE)
        data["Analyst Buy"]  = buy_m.group(1)  if buy_m  else "N/A"
        data["Analyst Hold"] = hold_m.group(1) if hold_m else "N/A"
        data["Analyst Sell"] = sell_m.group(1) if sell_m else "N/A"

        tgt_m = re.search(r"Target[:\s₹]*([0-9,]+)", text, re.IGNORECASE)
        data["Analyst Target"] = f"₹{tgt_m.group(1)}" if tgt_m else "N/A"

        score_m = re.search(r"(?:Score|Rating)[:\s]*([0-9.]+\s*/\s*10)", text, re.IGNORECASE)
        data["Score"] = score_m.group(1) if score_m else "N/A"

        data["source"] = "tickertape.in"
        return data, url
    except Exception as e:
        return None, str(e)


# ─── YFINANCE TECHNICALS ────────────────────────────────────

def fetch_technicals(symbol):
    yf_map = {"M&M": "M%26M.NS", "LT": "LT.NS", "APOLLO": "APOLLOHOSP.NS"}
    yf_sym = yf_map.get(symbol, f"{symbol}.NS")
    ticker = yf.Ticker(yf_sym)
    df     = ticker.history(period="1y", interval="1d")
    info   = ticker.info

    if df.empty or len(df) < 50:
        return None, None

    c = df["Close"]; h = df["High"]; l = df["Low"]; v = df["Volume"]

    ema21  = c.ewm(span=21,  adjust=False).mean()
    ema50  = c.ewm(span=50,  adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()

    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi   = 100 - (100 / (1 + gain / loss))

    bb_mid = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_up  = bb_mid + 2 * bb_std
    bb_dn  = bb_mid - 2 * bb_std

    tr  = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    vol_avg = v.rolling(20).mean()
    high_52 = float(h.max())
    low_52  = float(l.min())

    p    = float(c.iloc[-1])
    e21  = float(ema21.iloc[-1])
    e50  = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    r    = float(rsi.iloc[-1])
    a    = float(atr.iloc[-1])

    sl  = round(p - a * 1.5, 2)
    tp1 = round(p + (p - sl) * 1.5, 2)
    tp2 = round(p + (p - sl) * 2.5, 2)
    qty = int(5000 / (p - sl)) if (p - sl) > 0 else 0

    tech = {
        "price": p, "ema21": e21, "ema50": e50, "ema200": e200,
        "rsi": r, "atr": a, "sl": sl, "tp1": tp1, "tp2": tp2, "qty": qty,
        "vol": float(v.iloc[-1]), "vol_avg": float(vol_avg.iloc[-1]),
        "bb_up": float(bb_up.iloc[-1]), "bb_dn": float(bb_dn.iloc[-1]),
        "high_52": high_52, "low_52": low_52,
        "bull": p > e21 > e50 > e200,
        "bear": p < e21 < e50 < e200,
        "chg1d": float(c.pct_change().iloc[-1] * 100),
        "chg1w": float((c.iloc[-1] / c.iloc[-5] - 1) * 100),
        "chg1m": float((c.iloc[-1] / c.iloc[-22] - 1) * 100),
        "chg3m": float((c.iloc[-1] / c.iloc[-66] - 1) * 100),
        "dma_dist": (p - e200) / e200 * 100,
    }
    return tech, info


# ─── PRINT REPORT ───────────────────────────────────────────

def print_report(symbol, tech, info, screener, groww):
    p   = tech["price"]
    sep = f"{Fore.BLUE}{'─'*58}{Style.RESET_ALL}"

    print(f"\n{Back.BLUE}{Fore.WHITE}{'='*58}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}  {symbol} — DEEP ANALYSIS{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'='*58}{Style.RESET_ALL}")

    # ── PRICE ACTION
    print(f"\n{Fore.CYAN}PRICE ACTION{Style.RESET_ALL}")
    print(sep)
    chg_color = lambda x: Fore.GREEN if x > 0 else Fore.RED
    print(f"  CMP       : {Fore.YELLOW}₹{p:.2f}{Style.RESET_ALL}")
    print(f"  1D        : {chg_color(tech['chg1d'])}{tech['chg1d']:+.2f}%{Style.RESET_ALL}")
    print(f"  1W        : {chg_color(tech['chg1w'])}{tech['chg1w']:+.2f}%{Style.RESET_ALL}")
    print(f"  1M        : {chg_color(tech['chg1m'])}{tech['chg1m']:+.2f}%{Style.RESET_ALL}")
    print(f"  3M        : {chg_color(tech['chg3m'])}{tech['chg3m']:+.2f}%{Style.RESET_ALL}")
    print(f"  52W High  : ₹{tech['high_52']:.2f}  ({(p/tech['high_52']-1)*100:+.1f}% from high)")
    print(f"  52W Low   : ₹{tech['low_52']:.2f}  ({(p/tech['low_52']-1)*100:+.1f}% from low)")

    # ── TECHNICAL
    print(f"\n{Fore.CYAN}TECHNICALS{Style.RESET_ALL}")
    print(sep)
    trend_str = f"{Fore.GREEN}STRONG BULL{Style.RESET_ALL}" if tech["bull"] else \
                f"{Fore.RED}BEAR{Style.RESET_ALL}"          if tech["bear"] else \
                f"{Fore.YELLOW}NEUTRAL{Style.RESET_ALL}"
    print(f"  Trend     : {trend_str}")
    ab = lambda val, ref: f"{Fore.GREEN}ABOVE{Style.RESET_ALL}" if val > ref else f"{Fore.RED}BELOW{Style.RESET_ALL}"
    print(f"  EMA 21    : ₹{tech['ema21']:.2f}  Price {ab(p, tech['ema21'])}")
    print(f"  EMA 50    : ₹{tech['ema50']:.2f}  Price {ab(p, tech['ema50'])}")
    print(f"  EMA 200   : ₹{tech['ema200']:.2f}  Price {ab(p, tech['ema200'])}  ({tech['dma_dist']:+.1f}%)")
    rsi_color = Fore.RED if tech["rsi"] > 70 else Fore.GREEN if tech["rsi"] < 40 else Fore.WHITE
    rsi_note  = "Overbought — CAUTION" if tech["rsi"] > 70 else "Oversold — BUY ZONE" if tech["rsi"] < 40 else "Healthy"
    print(f"  RSI (14)  : {rsi_color}{tech['rsi']:.1f}  {rsi_note}{Style.RESET_ALL}")
    print(f"  ATR (14)  : ₹{tech['atr']:.2f}")
    vol_ratio = tech["vol"] / tech["vol_avg"] if tech["vol_avg"] else 0
    vol_note  = f"{Fore.GREEN}SURGE ({vol_ratio:.1f}x){Style.RESET_ALL}" if vol_ratio > 1.5 else f"{vol_ratio:.1f}x avg"
    print(f"  Volume    : {tech['vol']:,.0f}  ({vol_note})")
    print(f"  BB Upper  : ₹{tech['bb_up']:.2f}   BB Lower: ₹{tech['bb_dn']:.2f}")

    # ── SCREENER.IN
    print(f"\n{Fore.CYAN}FUNDAMENTALS — screener.in{Style.RESET_ALL}")
    print(sep)
    if screener:
        key_ratios = ["Market Cap", "Current Price", "High / Low", "Stock P/E",
                      "Book Value", "Dividend Yield", "ROCE", "ROE", "Face Value",
                      "Promoter Holding", "FII Holding", "DII Holding"]
        for k in key_ratios:
            if k in screener:
                color = Fore.GREEN if k in ("ROCE", "ROE") and screener[k] not in ("N/A","") else Fore.WHITE
                print(f"  {k:<22}: {color}{screener[k]}{Style.RESET_ALL}")

        # Quarterly results
        q = screener.get("Quarterly", {})
        if q:
            print(f"\n  {Fore.YELLOW}Quarterly Results (latest 4){Style.RESET_ALL}")
            for metric, vals in q.items():
                periods = list(vals.keys())[-4:]
                row = "  ".join([f"{p}: {vals[p]}" for p in periods if p in vals])
                print(f"  {metric:<12}: {row}")

        # Annual highlights
        ann = screener.get("Annual", {})
        if ann and "Sales" in ann:
            print(f"\n  {Fore.YELLOW}Annual Sales (last 3 years){Style.RESET_ALL}")
            sales = ann["Sales"]
            years = list(sales.keys())[-3:]
            print("  " + "   ".join([f"{y}: ₹{sales[y]}Cr" for y in years if y in sales]))
        if ann and "Net Profit" in ann:
            profit = ann["Net Profit"]
            years  = list(profit.keys())[-3:]
            print("  " + "   ".join([f"{y}: ₹{profit[y]}Cr" for y in years if y in profit]))
    else:
        print(f"  {Fore.YELLOW}Could not fetch screener.in data{Style.RESET_ALL}")

    # ── ANALYST RATINGS (from screener.in peer data + direct links)
    print(f"\n{Fore.CYAN}ANALYST RATINGS & LINKS{Style.RESET_ALL}")
    print(sep)
    # Use yfinance analyst data which is reliable
    if info:
        rec    = info.get("recommendationKey", "N/A").upper()
        n_anal = info.get("numberOfAnalystOpinions", "N/A")
        target = info.get("targetMeanPrice", None)
        t_high = info.get("targetHighPrice",  None)
        t_low  = info.get("targetLowPrice",   None)

        rec_color = Fore.GREEN if "BUY" in rec else Fore.RED if "SELL" in rec else Fore.YELLOW
        print(f"  Recommendation : {rec_color}{rec}{Style.RESET_ALL}  ({n_anal} analysts)")
        if target:
            upside = (target / p - 1) * 100
            u_color = Fore.GREEN if upside > 10 else Fore.RED if upside < 0 else Fore.YELLOW
            print(f"  Mean Target    : {Fore.GREEN}₹{target:.0f}{Style.RESET_ALL}  ({u_color}{upside:+.1f}% upside{Style.RESET_ALL})")
        if t_low and t_high:
            print(f"  Target Range   : ₹{t_low:.0f} — ₹{t_high:.0f}")
    print(f"\n  {Fore.YELLOW}Open for full analyst breakdown:{Style.RESET_ALL}")
    print(f"  → Screener   : https://www.screener.in/company/{symbol}/")
    print(f"  → Tickertape : https://www.tickertape.in/stocks/{symbol.lower()}-NSE")
    print(f"  → Groww      : https://groww.in/stocks/{symbol.lower()}")
    print(f"  → MC         : https://www.moneycontrol.com/india/stockpricequote/{symbol.lower()}")

    # ── YFINANCE FUNDAMENTALS
    if info:
        print(f"\n{Fore.CYAN}FUNDAMENTALS — yfinance{Style.RESET_ALL}")
        print(sep)
        fields = [
            ("Sector",          info.get("sector",             "N/A")),
            ("Industry",        info.get("industry",           "N/A")),
            ("Market Cap",      f"₹{info.get('marketCap',0)/1e9:.1f}B"),
            ("P/E Ratio",       info.get("trailingPE",         "N/A")),
            ("Forward P/E",     info.get("forwardPE",          "N/A")),
            ("EPS (TTM)",       info.get("trailingEps",        "N/A")),
            ("ROE",             f"{info.get('returnOnEquity',0)*100:.1f}%" if info.get("returnOnEquity") else "N/A"),
            ("Revenue Growth",  f"{info.get('revenueGrowth',0)*100:.1f}%" if info.get("revenueGrowth")  else "N/A"),
            ("Earnings Growth", f"{info.get('earningsGrowth',0)*100:.1f}%" if info.get("earningsGrowth") else "N/A"),
            ("Debt/Equity",     info.get("debtToEquity",       "N/A")),
            ("Current Ratio",   info.get("currentRatio",       "N/A")),
            ("Promoter Hold",   info.get("heldPercentInsiders", None)),
        ]
        for name, val in fields:
            if val and val != "N/A":
                print(f"  {name:<22}: {val}")

    # ── TRADE PLAN
    print(f"\n{Fore.CYAN}TRADE PLAN  (₹5L capital · 1% risk = ₹5,000){Style.RESET_ALL}")
    print(sep)
    print(f"  Entry      : {Fore.YELLOW}₹{p:.2f}{Style.RESET_ALL}")
    print(f"  Stop Loss  : {Fore.RED}₹{tech['sl']:.2f}{Style.RESET_ALL}  (1.5× ATR)")
    print(f"  Target 1   : {Fore.GREEN}₹{tech['tp1']:.2f}{Style.RESET_ALL}  (1.5:1 RR)")
    print(f"  Target 2   : {Fore.GREEN}₹{tech['tp2']:.2f}{Style.RESET_ALL}  (2.5:1 RR)")
    print(f"  Quantity   : {tech['qty']} shares")
    print(f"  Risk/Trade : ₹{round((p - tech['sl']) * tech['qty']):.0f}")

    # ── VERDICT
    print(f"\n{Back.BLUE}{Fore.WHITE} VERDICT {Style.RESET_ALL}")
    signals = []
    if tech["bull"]:          signals.append(f"{Fore.GREEN}Bull trend{Style.RESET_ALL}")
    if tech["rsi"] < 40:      signals.append(f"{Fore.GREEN}Oversold RSI{Style.RESET_ALL}")
    if tech["rsi"] > 70:      signals.append(f"{Fore.RED}Overbought RSI{Style.RESET_ALL}")
    if tech["vol"] > tech["vol_avg"] * 1.5: signals.append(f"{Fore.GREEN}Volume surge{Style.RESET_ALL}")
    if tech["dma_dist"] > 30: signals.append(f"{Fore.YELLOW}Stretched above 200 DMA{Style.RESET_ALL}")

    if signals:
        print("  " + "  |  ".join(signals))

    buy_count = 0
    try:
        buy_count = int(groww.get("Analyst Buy", 0)) if groww else 0
        sell_count = int(groww.get("Analyst Sell", 0)) if groww else 0
    except: pass

    overall = "WAIT"
    if tech["bull"] and tech["rsi"] < 70 and buy_count >= 3:
        overall = "BUY ZONE"
    elif tech["bear"] or tech["rsi"] > 75:
        overall = "AVOID"

    color = Fore.GREEN if overall == "BUY ZONE" else Fore.RED if overall == "AVOID" else Fore.YELLOW
    print(f"\n  Overall: {color}{overall}{Style.RESET_ALL}\n")

    print(f"  screener.in    : https://www.screener.in/company/{symbol}/")
    print(f"  moneycontrol   : https://www.moneycontrol.com/india/stockpricequote/{symbol.lower()}")
    print(f"  tickertape.in  : https://www.tickertape.in/stocks/{symbol.lower()}-NSE")
    print()


# ─── MAIN ───────────────────────────────────────────────────

def analyze(symbol):
    symbol = symbol.upper().strip()
    print(f"\n{Fore.CYAN}Fetching data for {symbol}...{Style.RESET_ALL}")

    print(f"  [1/4] yfinance technicals...", end=" ", flush=True)
    tech, info = fetch_technicals(symbol)
    print("done" if tech else "FAILED")

    print(f"  [2/4] screener.in...", end=" ", flush=True)
    screener, sc_url = fetch_screener(symbol)
    print("done" if screener else f"failed ({sc_url})")

    print(f"  [3/4] tickertape.in...", end=" ", flush=True)
    analyst, tt_url = fetch_tickertape(symbol)
    print("done" if analyst else "trying moneycontrol...")

    if not analyst:
        print(f"  [4/4] moneycontrol...", end=" ", flush=True)
        analyst, mc_url = fetch_moneycontrol(symbol)
        print("done" if analyst else "failed")
    else:
        print(f"  [4/4] skipped (tickertape succeeded)")

    if not tech:
        print(f"{Fore.RED}No price data found for {symbol}. Check the symbol.{Style.RESET_ALL}")
        return

    print_report(symbol, tech, info, screener, analyst)


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else input("Enter stock symbol: ").strip()
    analyze(symbol)
