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
from datetime import datetime, timedelta, timezone
from tabulate import tabulate
from colorama import Fore, Back, Style, init
from bs4 import BeautifulSoup

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
    # User added 25 Jun 2026
    "AUROPHARMA", "LTF", "ASHOKLEY", "GESHIP", "GREAVESCOT",
    "GODREJIND", "NH", "ZYDUSWELL", "VMM", "AVANTIFEED",
    # User added 25 Jun 2026 batch 2
    "HSCL", "FORTIS", "GOLDIAM", "JSWENERGY", "TRIVENI",
    "CHENNPETRO", "EXIDEIND", "VBL", "KIMS", "BAJAJHFL",
    "TARIL", "HDBFS", "GABRIEL", "TEJASNET", "RICOAUTO",
    "JAYBARMARU", "MMTC",
    # User added 01 Jul 2026
    "SGMART", "WAAREEENER", "PTCIL", "NIBE", "RPEL",
    # User added 02 Jul 2026
    "AEGISLOG",
    "MARICO", "TORNTPHARM", "BHARTIARTL", "INDUSTOWER", "FEDERALBNK",
    "MUTHOOTFIN", "ABSLAMC", "AUBANK",
    "BRITANNIA", "LUPIN", "NTPC", "JBCHEPHARM", "AJANTPHARM", "TECHM",
    "KOTAKBANK", "BAJFINANCE", "DMART", "ICICIBANK", "APLAPOLLO", "HCG",
    "NESTLEIND", "ETERNAL", "UJJIVANSFB", "CHALET", "MINDACORP", "DALBHARAT",
    "SARDAEN",
    # User added 06 Jul 2026 — batch 1 (auto/industrial/small-cap)
    "IDEAFORGE", "DIFFENG", "RISHABHINST", "PARAMCAB",
    "RATNAVEER", "CAPTPL", "ESABINDIA", "UNIVCABLES",
    "NDRAUTO", "DYCL", "MENONBE", "KPGEL",
    "TALBROS", "STYLAM", "DYNACONS", "CONTROLPR",
    "PRAKASHPIPE", "HPADHESIVE", "SHIVALIC",
    "KHAITANCH", "RBMINFRA", "MACHINOPL", "EMMFORCE", "INSOLENERGY",
    # User added 06 Jul 2026 — batch 2 (diversified)
    "KDDL", "HINDFOODS", "CARERATING", "GRINDWELL",
    "CIEINDIA", "LEMONTREE", "POWERMECH",
    "KRISHNAPH", "WABAG", "APARINDS", "EPL",
    "BECTORFOOD", "SUPREMEIND", "DEEPAKNTR",
    "BANCOINDIA", "SANSERA", "SANDHAR", "LTFOODS",
    "INDRAMEDCO", "CERA", "ABDL", "BLS", "INDEGENE",
    "BHARATSEATS", "ELECON", "KPENERGY",
    "SIRCA", "UDS", "EUREKAFORBE", "TAJGVK",
    "AGIGREENPAC", "GARFIBRES", "DALMIASUG", "SHRIPISTON", "DHANUKA",
    "RRKABEL", "MAYURUNIQ", "SHKELKAR", "YATHARTH",
    "SHARDACROP", "VSTIND", "EIDPARRY",
    "ROLEXRINGS", "CARYSIL", "RKFORGE", "PAUSHAK",
    "TIMETECHNO", "FIEM", "LAOPALA",
    "SHARDAMOTR", "TDPOWERSYS", "KEWALKIRN",
    "MAHSEAMLES", "ACE", "TGVSRAAC", "SARLAPOLY",
    "GNAAXLES", "LGBBROS", "ANUP", "VOLTAMP",
    "NRBBEARING", "FAIRCHEMOR", "KRSNAA",
    "NAVA", "SHEELAFOAM", "BMWINDIA", "KOVAI", "BIGBLOC", "AMAL",
]

YF_SYMBOL_MAP = {
    "M&M":      "M%26M.NS",
    "LT":       "LT.NS",
    "APOLLO":   "APOLLOHOSP.NS",
    "WHEELS":   "WHEELS.NS",
    "YASHHV":   "YASHHV.BO",
    "BONDADA":  "BONDADA.BO",
    "PRICOLLTD":"PRICOLLTD.NS",
    "PREMEXPLN":"PREMEXPLN.NS",
    "LTF":      "LTF.NS",
    "GESHIP":   "GESHIP.NS",
    "GREAVESCOT":"GREAVESCOT.NS",
    "GODREJIND":"GODREJIND.NS",
    "NH":       "NH.NS",
    "ZYDUSWELL":"ZYDUSWELL.NS",
    "VMM":      "VMM.NS",
    "AVANTIFEED":"AVANTIFEED.NS",
    "ASHOKLEY": "ASHOKLEY.NS",
    "AUROPHARMA":"AUROPHARMA.NS",
    "SGMART":    "SGMART.NS",
    "WAAREEENER":"WAAREEENER.NS",
    "PTCIL":     "PTCIL.NS",
    "NIBE":      "NIBE.NS",
    "RPEL":      "RPEL.NS",
    "AEGISLOG":  "AEGISLOG.NS",
    "MARICO":    "MARICO.NS",
    "TORNTPHARM":"TORNTPHARM.NS",
    "BHARTIARTL":"BHARTIARTL.NS",
    "INDUSTOWER":"INDUSTOWER.NS",
    "FEDERALBNK":"FEDERALBNK.NS",
    "MUTHOOTFIN":"MUTHOOTFIN.NS",
    "ABSLAMC":   "ABSLAMC.NS",
    "AUBANK":      "AUBANK.NS",
    "BRITANNIA":   "BRITANNIA.NS",
    "LUPIN":       "LUPIN.NS",
    "NTPC":        "NTPC.NS",
    "JBCHEPHARM":  "JBCHEPHARM.NS",
    "AJANTPHARM":  "AJANTPHARM.NS",
    "TECHM":       "TECHM.NS",
    "KOTAKBANK":   "KOTAKBANK.NS",
    "BAJFINANCE":  "BAJFINANCE.NS",
    "DMART":       "DMART.NS",
    "ICICIBANK":   "ICICIBANK.NS",
    "APLAPOLLO":   "APLAPOLLO.NS",
    "HCG":         "HCG.NS",
    "NESTLEIND":   "NESTLEIND.NS",
    "ETERNAL":     "ETERNAL.NS",
    "UJJIVANSFB":  "UJJIVANSFB.NS",
    "CHALET":      "CHALET.NS",
    "MINDACORP":   "MINDACORP.NS",
    "DALBHARAT":   "DALBHARAT.NS",
    "SARDAEN":     "SARDAEN.NS",
    # 06 Jul 2026 additions — batch 1
    "IDEAFORGE":   "IDEAFORGE.NS",
    "DIFFENG":     "DIFFENG.NS",
    "RISHABHINST": "RISHABHINST.NS",
    "PARAMCAB":    "PARAMCABLES.NS",
    "RATNAVEER":   "RATNAVEER.NS",
    "CAPTPL":      "CAPTPL.NS",
    "ESABINDIA":   "ESABINDIA.NS",
    "UNIVCABLES":  "UNIVCABLES.NS",
    "NDRAUTO":     "NDRAUTO.NS",
    "DYCL":        "DYCL.NS",
    "MENONBE":     "MENONBE.NS",
    "KPGEL":       "KPGEL.NS",
    "TALBROS":     "TALBROS.NS",
    "STYLAM":      "STYLAM.NS",
    "DYNACONS":    "DYNACONS.BO",
    "CONTROLPR":   "CONTROLPR.NS",
    "PRAKASHPIPE": "PRAKASHPIPE.NS",
    "HPADHESIVE":  "HPADHESIVE.NS",
    "SHIVALIC":    "SHIVALIC.NS",
    "KHAITANCH":   "KHAITANCH.NS",
    "RBMINFRA":    "RBMINFRA.NS",
    "MACHINOPL":   "MACHINOPL.NS",
    "EMMFORCE":    "EMMFORCE.NS",
    "INSOLENERGY": "INSOLENERGY.NS",
    # 06 Jul 2026 additions — batch 2
    "KDDL":        "KDDL.NS",
    "HINDFOODS":   "HNDFDS.NS",
    "CARERATING":  "CARERATING.NS",
    "GRINDWELL":   "GRINDWELL.NS",
    "CIEINDIA":    "CIEINDIA.NS",
    "LEMONTREE":   "LEMONTREE.NS",
    "POWERMECH":   "POWERMECH.NS",
    "KRISHNAPH":   "KRISHNAPH.NS",
    "WABAG":       "WABAG.NS",
    "APARINDS":    "APARINDS.NS",
    "EPL":         "EPL.NS",
    "BECTORFOOD":  "BECTORFOOD.NS",
    "SUPREMEIND":  "SUPREMEIND.NS",
    "DEEPAKNTR":   "DEEPAKNTR.NS",
    "BANCOINDIA":  "BANCOINDIA.NS",
    "SANSERA":     "SANSERA.NS",
    "SANDHAR":     "SANDHAR.NS",
    "LTFOODS":     "LTFOODS.NS",
    "INDRAMEDCO":  "INDRAMEDCO.NS",
    "CERA":        "CERA.NS",
    "ABDL":        "ABDL.NS",
    "BLS":         "BLS.NS",
    "INDEGENE":    "INDEGENE.NS",
    "BHARATSEATS": "BHARATSEATS.NS",
    "ELECON":      "ELECON.NS",
    "KPENERGY":    "KPENERGY.NS",
    "SIRCA":       "SIRCA.NS",
    "UDS":         "UDS.NS",
    "EUREKAFORBE": "EUREKAFORBE.NS",
    "TAJGVK":      "TAJGVK.NS",
    "AGIGREENPAC": "AGIGREENPAC.NS",
    "GARFIBRES":   "GARFIBRES.NS",
    "DALMIASUG":   "DALMIASUG.NS",
    "SHRIPISTON":  "SHRIPISTON.NS",
    "DHANUKA":     "DHANUKA.NS",
    "RRKABEL":     "RRKABEL.NS",
    "MAYURUNIQ":   "MAYURUNIQ.NS",
    "SHKELKAR":    "SHKELKAR.NS",
    "YATHARTH":    "YATHARTH.NS",
    "SHARDACROP":  "SHARDACROP.NS",
    "VSTIND":      "VSTIND.NS",
    "EIDPARRY":    "EIDPARRY.NS",
    "ROLEXRINGS":  "ROLEXRINGS.NS",
    "CARYSIL":     "CARYSIL.NS",
    "RKFORGE":     "RKFORGE.NS",
    "PAUSHAK":     "PAUSHAK.BO",
    "TIMETECHNO":  "TIMETECHNO.NS",
    "FIEM":        "FIEM.NS",
    "LAOPALA":     "LAOPALA.NS",
    "SHARDAMOTR":  "SHARDAMOTR.NS",
    "TDPOWERSYS":  "TDPOWERSYS.NS",
    "KEWALKIRN":   "KEWALKIRN.NS",
    "MAHSEAMLES":  "MAHSEAMLES.NS",
    "ACE":         "ACE.NS",
    "TGVSRAAC":    "TGVSRAAC.NS",
    "SARLAPOLY":   "SARLAPOLY.NS",
    "GNAAXLES":    "GNAAXLES.NS",
    "LGBBROS":     "LGBBROS.NS",
    "ANUP":        "ANUP.NS",
    "VOLTAMP":     "VOLTAMP.NS",
    "NRBBEARING":  "NRBBEARING.NS",
    "FAIRCHEMOR":  "FAIRCHEMOR.NS",
    "KRSNAA":      "KRSNAA.NS",
    "NAVA":        "NAVA.NS",
    "SHEELAFOAM":  "SFL.NS",
    "BMWINDIA":    "BMWINDIA.BO",
    "KOVAI":       "KOVAI.NS",
    "BIGBLOC":     "BIGBLOC.NS",
    "AMAL":        "AMAL.NS",
}

MIN_DELIVERY_PCT  = 40.0
MIN_SCORE         = 5
TOP_N             = 10

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
            trd = data.get("securityWiseDP", {})
            delv_pct = trd.get("deliveryToTradedQuantity", 0)
            trd_qty  = trd.get("tradedQuantity", 0)
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
                return {
                    "fii_net":  float(latest.get("fiiNet",  0)),
                    "dii_net":  float(latest.get("diiNet",  0)),
                    "date":     latest.get("date", ""),
                    "fii_buy":  float(latest.get("fiiBuy",  0)),
                    "fii_sell": float(latest.get("fiiSell", 0)),
                    "dii_buy":  float(latest.get("diiBuy",  0)),
                    "dii_sell": float(latest.get("diiSell", 0)),
                }
    except Exception:
        pass
    return {"fii_net": 0.0, "dii_net": 0.0, "date": "N/A"}

# ============================================================
# FETCH PCR FROM NSE
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
            return round(pe_oi / ce_oi, 2) if ce_oi > 0 else 0.0
    except Exception:
        pass
    return 0.0

# ============================================================
# FETCH NIFTY RETURNS FOR RELATIVE STRENGTH
# ============================================================
_nifty_returns = None

def get_nifty_returns():
    global _nifty_returns
    if _nifty_returns is not None:
        return _nifty_returns
    try:
        tk = yf.Ticker("^NSEI")
        df = tk.history(period="1y", interval="1d")
        if df.empty:
            _nifty_returns = {}
            return _nifty_returns
        c = df["Close"]
        r1w = float((c.iloc[-1] / c.iloc[-6]  - 1) * 100) if len(c) >= 6  else 0
        r1m = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else 0
        r3m = float((c.iloc[-1] / c.iloc[-63] - 1) * 100) if len(c) >= 63 else 0
        _nifty_returns = {"1w": r1w, "1m": r1m, "3m": r3m}
    except Exception:
        _nifty_returns = {"1w": 0, "1m": 0, "3m": 0}
    return _nifty_returns

# ============================================================
# FETCH RECENT NEWS (last 48h) FOR A STOCK
# ============================================================
def fetch_news(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, f"{symbol}.NS")
        tk = yf.Ticker(yf_sym)
        news = tk.news or []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        headlines = []
        for item in news:
            content = item.get("content", item)
            pub_str = content.get("pubDate") or content.get("displayTime") or ""
            title   = content.get("title", item.get("title", ""))
            if not pub_str or not title:
                continue
            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt >= cutoff:
                    headlines.append(title)
            except Exception:
                pass
        return headlines[:2]
    except Exception:
        return []

# ============================================================
# FETCH SCREENER.IN SHAREHOLDING (FII QoQ change)
# ============================================================
def fetch_screener_holdings(symbol):
    try:
        url = f"https://www.screener.in/company/{symbol}/"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")

        # Find shareholding table
        holdings = {}
        for section in soup.find_all("section"):
            h2 = section.find("h2")
            if h2 and "shareholding" in h2.text.lower():
                rows = section.find_all("tr")
                headers_row = rows[0].find_all("th") if rows else []
                # Get last 2 quarters
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if not cells:
                        continue
                    label = cells[0].get_text(strip=True).lower()
                    vals  = [c.get_text(strip=True).replace("%","") for c in cells[1:]]
                    if "fii" in label or "foreign" in label:
                        try:
                            holdings["fii_curr"] = float(vals[-1]) if vals else None
                            holdings["fii_prev"] = float(vals[-2]) if len(vals) > 1 else None
                        except Exception:
                            pass
                    elif "dii" in label or "domestic inst" in label:
                        try:
                            holdings["dii_curr"] = float(vals[-1]) if vals else None
                            holdings["dii_prev"] = float(vals[-2]) if len(vals) > 1 else None
                        except Exception:
                            pass
                break
        return holdings
    except Exception:
        return {}

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

        # Volume
        vol_avg   = v.rolling(20).mean()
        vol_ratio = float(v.iloc[-1]) / float(vol_avg.iloc[-1]) if float(vol_avg.iloc[-1]) > 0 else 1
        vol_surge = vol_ratio > 1.5

        # 52W high/low
        high_52w = h.rolling(252).max().iloc[-1]
        low_52w  = l.rolling(252).min().iloc[-1]

        # BB squeeze
        bb_mid   = c.rolling(20).mean()
        bb_std   = c.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid
        bb_sq    = float(bb_width.iloc[-1]) < float(bb_width.rolling(50).min().iloc[-1]) * 1.1

        # ATR
        tr    = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()

        price_now = float(c.iloc[-1])
        e21  = float(ema21.iloc[-1])
        e50  = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])

        bull = e21 > e50 and e50 > e200
        bear = e21 < e50 and e50 < e200

        dma_dist = (price_now - e200) / e200 * 100 if e200 > 0 else 0
        near_52w = price_now >= high_52w * 0.95   # tightened to 5%

        weekly_bull = float(c.iloc[-1]) > float(ema21.iloc[-5]) if len(ema21) > 5 else (price_now > e21)

        # Momentum returns
        r1w = float((c.iloc[-1] / c.iloc[-6]  - 1) * 100) if len(c) >= 6  else 0
        r1m = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else 0
        r3m = float((c.iloc[-1] / c.iloc[-63] - 1) * 100) if len(c) >= 63 else 0

        # Momentum score (weighted: 1W×1 + 1M×2 + 3M×3, normalised to 0-10)
        momentum_raw = r1w * 1 + r1m * 2 + r3m * 3
        momentum_score = round(min(max(momentum_raw / 6, 0), 10), 1)

        # VWAP (session approximation using typical price × volume / cumulative volume)
        typical = (h + l + c) / 3
        vwap = float((typical * v).cumsum().iloc[-1] / v.cumsum().iloc[-1]) if v.cumsum().iloc[-1] > 0 else price_now
        above_vwap = price_now > vwap

        return {
            "price":          price_now,
            "ema21":          e21,
            "ema50":          e50,
            "ema200":         e200,
            "rsi":            float(rsi.iloc[-1]),
            "vol_surge":      vol_surge,
            "vol_ratio":      round(vol_ratio, 1),
            "atr":            float(atr14.iloc[-1]),
            "bb_squeeze":     bb_sq,
            "high_52w":       float(high_52w),
            "low_52w":        float(low_52w),
            "dma_dist":       dma_dist,
            "near_52w":       near_52w,
            "bull_trend":     bull,
            "bear_trend":     bear,
            "weekly_bull":    weekly_bull,
            "pct_change":     float(c.pct_change().iloc[-1] * 100),
            "volume":         float(v.iloc[-1]),
            "ret_1w":         round(r1w, 1),
            "ret_1m":         round(r1m, 1),
            "ret_3m":         round(r3m, 1),
            "momentum_score": momentum_score,
            "vwap":           round(vwap, 2),
            "above_vwap":     above_vwap,
        }
    except Exception:
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
            "pe":           info.get("trailingPE",        None),
            "roe":          info.get("returnOnEquity",    None),
            "debt_eq":      info.get("debtToEquity",      None),
            "eps":          info.get("trailingEps",       None),
            "market_cap":   info.get("marketCap",         None),
            "sector":       info.get("sector",            "N/A"),
            "analyst_rec":  info.get("recommendationKey", "N/A"),
            "target_price": info.get("targetMeanPrice",   None),
            "revenue_gr":   info.get("revenueGrowth",     None),
            "earn_gr":      info.get("earningsGrowth",    None),
        }
    except Exception:
        return {}

# ============================================================
# SCORE EACH STOCK (out of 14)
# ============================================================
def score_stock(tech, fund, delv, fii_dii, pcr, holdings, nifty_ret):
    score = 0
    flags = []

    if not tech:
        return 0, []

    # ── TECHNICAL (5 pts) ──
    if tech.get("bull_trend"):
        score += 1; flags.append("Bull Trend")
    if tech.get("weekly_bull"):
        score += 1; flags.append("Weekly Bull")
    if 40 < tech.get("rsi", 100) < 70:
        score += 1; flags.append(f"RSI {tech['rsi']:.0f}")
    if tech.get("vol_surge"):
        score += 1; flags.append(f"Vol {tech['vol_ratio']}x")
    if tech.get("bb_squeeze"):
        score += 1; flags.append("BB Squeeze")

    # ── MOMENTUM vs NIFTY (3 pts) ──
    r1m = tech.get("ret_1m", 0)
    r3m = tech.get("ret_3m", 0)
    nifty_1m = nifty_ret.get("1m", 0)
    nifty_3m = nifty_ret.get("3m", 0)
    rs_1m = r1m - nifty_1m   # relative strength vs Nifty 1M
    rs_3m = r3m - nifty_3m   # relative strength vs Nifty 3M
    if rs_1m > 3:
        score += 1; flags.append(f"RS+{rs_1m:.0f}% 1M")
    if rs_3m > 5:
        score += 1; flags.append(f"RS+{rs_3m:.0f}% 3M")
    if tech.get("momentum_score", 0) >= 5:
        score += 1; flags.append(f"Mom {tech['momentum_score']}")

    # ── VWAP (1 pt) ──
    if tech.get("above_vwap"):
        score += 1; flags.append("Above VWAP")

    # ── INSTITUTIONAL FLOW (2 pts) ──
    fii_curr = holdings.get("fii_curr")
    fii_prev = holdings.get("fii_prev")
    dii_curr = holdings.get("dii_curr")
    dii_prev = holdings.get("dii_prev")
    if fii_curr is not None and fii_prev is not None and fii_curr > fii_prev:
        score += 1; flags.append(f"FII↑{fii_curr:.1f}%")
    elif fii_dii.get("fii_net", 0) > 0:
        score += 1; flags.append("FII Buying")
    if dii_curr is not None and dii_prev is not None and dii_curr > dii_prev:
        score += 1; flags.append(f"DII↑{dii_curr:.1f}%")
    elif fii_dii.get("dii_net", 0) > 0:
        score += 1; flags.append("DII Buying")

    # ── DELIVERY % (1 pt) ──
    if delv.get("delivery_pct", 0) >= MIN_DELIVERY_PCT:
        score += 1; flags.append(f"Delv {delv['delivery_pct']:.0f}%")

    # ── FUNDAMENTALS (2 pts) ──
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
    p = tech["price"]
    if tech.get("near_52w"):
        setups.append("52W Breakout")
    if tech.get("bb_squeeze"):
        setups.append("BB Squeeze")
    if tech.get("bull_trend") and abs(p - tech["ema21"]) / p < 0.02:
        setups.append("EMA Pullback")
    if tech.get("rsi", 100) < 40 and tech.get("bull_trend"):
        setups.append("Oversold Bounce")
    if tech.get("above_vwap") and tech.get("vol_surge"):
        setups.append("VWAP Breakout")
    return ", ".join(setups) if setups else "Trend Following"

# ============================================================
# CALCULATE SL & TARGET
# ============================================================
def calc_levels(tech, capital=500000, risk_pct=1.0, rr=2.0):
    if not tech:
        return None, None, None
    atr   = tech.get("atr", 0)
    price = tech.get("price", 0)
    sl    = round(price - atr * 1.5, 2)
    tp    = round(price + (price - sl) * rr, 2)
    risk  = capital * risk_pct / 100
    qty   = int(risk / (price - sl)) if (price - sl) > 0 else 0
    return sl, tp, qty

# ============================================================
# MAIN SCAN
# ============================================================
def run_morning_scan():
    print(f"\n{Back.BLUE}{Fore.WHITE}{'='*70}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}   INDIA MORNING WATCHLIST SCAN — {datetime.now().strftime('%d %b %Y %I:%M %p')}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'='*70}{Style.RESET_ALL}\n")

    print(f"{Fore.CYAN}[1/5] Connecting to NSE...{Style.RESET_ALL}")
    session = get_nse_session()
    time.sleep(1)

    print(f"{Fore.CYAN}[2/5] Fetching FII/DII data, PCR & Nifty returns...{Style.RESET_ALL}")
    fii_dii    = fetch_fii_dii(session)
    pcr        = fetch_pcr(session, "NIFTY")
    nifty_ret  = get_nifty_returns()
    time.sleep(1)

    fii_net = fii_dii.get("fii_net", 0)
    dii_net = fii_dii.get("dii_net", 0)
    market_sentiment = "BULLISH" if fii_net > 0 and dii_net > 0 else \
                       "BEARISH" if fii_net < 0 and dii_net < 0 else "MIXED"

    print(f"{Fore.CYAN}[3/5] Scanning {len(WATCHLIST)} stocks...{Style.RESET_ALL}")
    results = []

    for i, symbol in enumerate(WATCHLIST):
        print(f"  {Fore.WHITE}{i+1:3d}/{len(WATCHLIST)} {symbol:<15}{Style.RESET_ALL}", end="", flush=True)

        tech     = fetch_technicals(symbol)
        fund     = fetch_fundamentals(symbol)
        delv     = fetch_delivery(session, symbol)
        holdings = fetch_screener_holdings(symbol)
        score, flags = score_stock(tech, fund, delv, fii_dii, pcr, holdings, nifty_ret)
        setup    = detect_setup(tech)
        sl, tp, qty = calc_levels(tech)

        if tech:
            chg = tech.get("pct_change", 0)
            chg_str = f"{Fore.GREEN}+{chg:.1f}%{Style.RESET_ALL}" if chg > 0 else f"{Fore.RED}{chg:.1f}%{Style.RESET_ALL}"
            rs_str  = f"RS:{tech['ret_1m']:+.0f}%/1M"
            print(f" ₹{tech['price']:>8.2f} {chg_str}  Score:{score}/14  Mom:{tech['momentum_score']}  {rs_str}  {setup}")
        else:
            print(f"  {Fore.YELLOW}No data{Style.RESET_ALL}")

        if score >= MIN_SCORE and tech:
            fii_chg = ""
            if holdings.get("fii_curr") is not None and holdings.get("fii_prev") is not None:
                diff = holdings["fii_curr"] - holdings["fii_prev"]
                fii_chg = f"{diff:+.1f}%"
            results.append({
                "Symbol":    symbol,
                "Price":     f"₹{tech['price']:.2f}",
                "Change":    f"{tech['pct_change']:+.1f}%",
                "Score":     f"{score}/14",
                "RSI":       f"{tech['rsi']:.0f}",
                "Trend":     "BULL" if tech["bull_trend"] else "BEAR" if tech["bear_trend"] else "NEUT",
                "Mom":       f"{tech['momentum_score']}",
                "RS 1M":     f"{tech['ret_1m'] - nifty_ret.get('1m',0):+.1f}%",
                "RS 3M":     f"{tech['ret_3m'] - nifty_ret.get('3m',0):+.1f}%",
                "VWAP":      "↑" if tech.get("above_vwap") else "↓",
                "FII QoQ":   fii_chg if fii_chg else "N/A",
                "DMA Dist":  f"{tech['dma_dist']:+.1f}%",
                "Setup":     setup,
                "SL":        f"₹{sl}" if sl else "N/A",
                "Target":    f"₹{tp}" if tp else "N/A",
                "Upside%":   f"{((tp - tech['price']) / tech['price'] * 100):+.1f}%" if tp else "N/A",
                "Qty":       str(qty) if qty else "N/A",
                "Flags":     " | ".join(flags[:4]),
                "_score":    score,
                "_momentum": tech["momentum_score"],
                "_rsi":      tech["rsi"],
                "_news":     [],  # filled below
            })

        time.sleep(0.5)

    # Step 4: Fetch news for top candidates only (saves time)
    print(f"\n{Fore.CYAN}[4/5] Fetching news for top candidates...{Style.RESET_ALL}")
    results.sort(key=lambda x: (x["_score"], x["_momentum"]), reverse=True)
    top = results[:TOP_N]
    for r in top:
        headlines = fetch_news(r["Symbol"])
        r["_news"] = headlines
        time.sleep(0.2)

    print(f"{Fore.CYAN}[5/5] Generating report...{Style.RESET_ALL}\n")

    # ── MARKET OVERVIEW ──
    print(f"{Back.BLUE}{Fore.WHITE} MARKET OVERVIEW {Style.RESET_ALL}")
    mkt_color = Fore.GREEN if market_sentiment == "BULLISH" else Fore.RED if market_sentiment == "BEARISH" else Fore.YELLOW
    print(f"  Sentiment    : {mkt_color}{market_sentiment}{Style.RESET_ALL}")
    fii_color = Fore.GREEN if fii_net > 0 else Fore.RED
    dii_color = Fore.GREEN if dii_net > 0 else Fore.RED
    print(f"  FII Net      : {fii_color}₹{fii_net:,.0f} Cr{Style.RESET_ALL}  ({fii_dii.get('date','N/A')})")
    print(f"  DII Net      : {dii_color}₹{dii_net:,.0f} Cr{Style.RESET_ALL}")
    pcr_color = Fore.GREEN if pcr > 1.0 else Fore.RED if pcr < 0.7 else Fore.YELLOW
    pcr_note  = "Oversold (Bullish)" if pcr > 1.2 else "Overbought (Bearish)" if pcr < 0.7 else "Neutral"
    print(f"  Nifty PCR    : {pcr_color}{pcr} — {pcr_note}{Style.RESET_ALL}")
    n1m = nifty_ret.get("1m", 0)
    n3m = nifty_ret.get("3m", 0)
    print(f"  Nifty 1M/3M  : {n1m:+.1f}% / {n3m:+.1f}%  (benchmark for RS)")
    print()

    # ── TOP 10 TABLE ──
    if top:
        display_cols = ["Symbol","Price","Change","Score","RSI","Trend","Mom","RS 1M","RS 3M","VWAP","FII QoQ","Setup","SL","Target","Upside%","Qty"]
        display_data = [{k: v for k, v in r.items() if k in display_cols} for r in top]

        print(f"{Back.GREEN}{Fore.BLACK} TOP {len(top)} SWING TRADE CANDIDATES {Style.RESET_ALL}")
        print(tabulate(display_data, headers="keys", tablefmt="rounded_outline"))
        print()

        # ── SIGNAL BREAKDOWN ──
        print(f"{Back.BLUE}{Fore.WHITE} SIGNAL BREAKDOWN {Style.RESET_ALL}")
        for r in top:
            score_val = r["_score"]
            bar   = "█" * score_val + "░" * (14 - score_val)
            color = Fore.GREEN if score_val >= 10 else Fore.YELLOW if score_val >= 6 else Fore.WHITE
            print(f"  {color}{r['Symbol']:<15}{Style.RESET_ALL} [{bar}] {score_val}/14  {r['Flags']}")
        print()

        # ── NEWS ALERTS ──
        news_found = [(r["Symbol"], r["_news"]) for r in top if r["_news"]]
        if news_found:
            print(f"{Back.YELLOW}{Fore.BLACK} NEWS IN LAST 48H {Style.RESET_ALL}")
            for sym, headlines in news_found:
                print(f"  {Fore.YELLOW}{sym}{Style.RESET_ALL}")
                for h in headlines:
                    print(f"    → {h[:90]}")
            print()

        # ── TOP PICK ──
        best = top[0]
        print(f"{Back.GREEN}{Fore.BLACK} TOP PICK: {best['Symbol']} {Style.RESET_ALL}")
        print(f"  Price      : {best['Price']}  ({best['Change']})")
        print(f"  Setup      : {best['Setup']}")
        print(f"  Score      : {best['Score']}")
        print(f"  Momentum   : {best['Mom']} | RS vs Nifty: {best['RS 1M']} (1M) / {best['RS 3M']} (3M)")
        print(f"  VWAP       : {'Above' if best['VWAP'] == '↑' else 'Below'} | FII QoQ: {best['FII QoQ']}")
        print(f"  Stop Loss  : {best['SL']}")
        print(f"  Target     : {best['Target']}  ({best['Upside%']})")
        print(f"  Quantity   : {best['Qty']} shares")
        print(f"  Signals    : {best['Flags']}")
        if best["_news"]:
            print(f"  News       : {best['_news'][0][:80]}")
        print()

    else:
        print(f"{Fore.YELLOW}No stocks met the minimum score of {MIN_SCORE}/14 today.{Style.RESET_ALL}\n")

    # ── AVOID LIST ──
    avoid = [r for r in results if r["_score"] < MIN_SCORE and r.get("Trend") == "BEAR"]
    if avoid:
        print(f"{Back.RED}{Fore.WHITE} STOCKS TO AVOID (Bearish) {Style.RESET_ALL}")
        for r in avoid[:5]:
            print(f"  {Fore.RED}{r['Symbol']:<15}{Style.RESET_ALL} Score:{r['Score']}  RSI:{r['RSI']}  RS:{r['RS 1M']}/1M")
        print()

    print(f"{Fore.CYAN}Scan complete. {len(results)} stocks qualified out of {len(WATCHLIST)} scanned.{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Run this script daily at 8-9 AM before market opens.{Style.RESET_ALL}\n")

    # Save to CSV
    if results:
        today = datetime.now().strftime("%Y-%m-%d")
        fname = f"watchlist_{today}.csv"
        save_cols = [k for k in results[0].keys() if not k.startswith("_")]
        df = pd.DataFrame(results)[save_cols]
        df.to_csv(fname, index=False)
        print(f"{Fore.GREEN}Saved to {fname}{Style.RESET_ALL}\n")

    return results

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    run_morning_scan()
