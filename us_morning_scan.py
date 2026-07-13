"""
US Morning Watchlist Scanner
Fetches yfinance technicals/fundamentals + Unusual Whales options flow/dark pool + CBOE-style
market sentiment (VIX + SPY options PCR proxy — see note in fetch_market_sentiment()).
Run every morning before market open (8-9 AM ET).
"""

import html
import time
import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from tabulate import tabulate
from colorama import Fore, Back, Style, init

warnings.filterwarnings("ignore")
init(autoreset=True)

try:
    from unusualwhales import UWClient, UWError
except ImportError:
    UWClient, UWError = None, Exception

# ============================================================
# CONFIG
# ============================================================
WATCHLIST = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "NFLX",
    # Semis & hardware
    "SMCI", "MU", "QCOM", "TXN", "ARM", "LRCX", "TSM", "INTC",
    # Software / cloud
    "CRM", "NOW", "PANW", "CRWD", "SNOW", "PLTR", "ORCL",
    # Legacy hardware / networking
    "CSCO", "DELL", "HPE", "NTAP",
    # Financials
    "JPM", "GS", "MS", "V", "MA", "SCHW", "BAC",
    # Fintech
    "HOOD", "SOFI",
    # Consumer / retail
    "COST", "WMT", "HD", "NKE", "SBUX",
    # Healthcare
    "LLY", "UNH", "ISRG", "VRTX",
    # Industrials / defense
    "CAT", "DE", "BA", "LMT", "RTX",
    # Energy
    "XOM", "CVX",
    # Clean energy
    "PLUG",
    # Autos / EV
    "F", "GM", "RIVN", "LCID", "NIO",
    # Airlines
    "UAL", "AAL",
    # Communications / travel / discretionary
    "DIS", "UBER", "ABNB", "SHOP",
    # International ADRs
    "BABA",
    # High-beta momentum
    "COIN", "MSTR", "MARA",
    # Other (thinly-traded / non-standard — verify options liquidity before trading)
    "SPCX",
]

# Override yfinance ticker for symbols that need a different string
# (e.g. dotted share classes like "BRK.B" -> "BRK-B"). Empty by default.
YF_SYMBOL_MAP = {}

BENCHMARK       = "SPY"
MIN_SCORE       = 6
TOP_N           = 10
CAPITAL         = 50_000
RISK_PCT        = 1.0
RR              = 2.0

# ============================================================
# UNUSUAL WHALES CLIENT (optional — set UW_API_KEY in .env to enable)
# ============================================================
def get_uw_client():
    if UWClient is None:
        return None
    try:
        return UWClient()
    except UWError:
        return None

# ============================================================
# FETCH SPY RETURNS FOR RELATIVE STRENGTH (cached, called once)
# ============================================================
_spy_returns = None

def fetch_spy_returns():
    global _spy_returns
    if _spy_returns is not None:
        return _spy_returns
    try:
        df = yf.Ticker(BENCHMARK).history(period="1y", interval="1d")
        if df.empty:
            _spy_returns = {}
            return _spy_returns
        c = df["Close"]
        r1w = float((c.iloc[-1] / c.iloc[-6]  - 1) * 100) if len(c) >= 6  else 0
        r1m = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else 0
        r3m = float((c.iloc[-1] / c.iloc[-63] - 1) * 100) if len(c) >= 63 else 0
        _spy_returns = {"1w": r1w, "1m": r1m, "3m": r3m}
    except Exception:
        _spy_returns = {"1w": 0, "1m": 0, "3m": 0}
    return _spy_returns

# ============================================================
# FETCH MARKET SENTIMENT — VIX (yfinance) + PCR proxy
# ============================================================
def fetch_market_sentiment():
    """
    VIX comes straight from yfinance (^VIX).
    CBOE's own daily Total Put/Call Ratio page is Cloudflare-gated (no free
    JSON/CSV feed for live data — their public CSV archives stop in 2012),
    so PCR here is a volume-based proxy built from SPY's own option chain
    (nearest 2 expiries, put volume / call volume) via yfinance — same
    exchange, same free source, just not the official CBOE index PCR.
    """
    vix_level, vix_chg = None, 0.0
    try:
        vh = yf.Ticker("^VIX").history(period="5d", interval="1d")["Close"]
        if not vh.empty:
            vix_level = float(vh.iloc[-1])
            vix_chg = float((vh.iloc[-1] / vh.iloc[-2] - 1) * 100) if len(vh) > 1 else 0.0
    except Exception:
        pass

    pcr = 0.0
    try:
        tk = yf.Ticker(BENCHMARK)
        call_vol = put_vol = 0.0
        for exp in tk.options[:2]:
            ch = tk.option_chain(exp)
            call_vol += float(ch.calls["volume"].fillna(0).sum())
            put_vol  += float(ch.puts["volume"].fillna(0).sum())
        pcr = round(put_vol / call_vol, 2) if call_vol > 0 else 0.0
    except Exception:
        pass

    if vix_level is not None and vix_level < 20 and 0 < pcr < 1.0:
        sentiment = "BULLISH"
    elif vix_level is not None and (vix_level > 25 or pcr > 1.3):
        sentiment = "BEARISH"
    else:
        sentiment = "MIXED"

    return {"vix": vix_level, "vix_chg": vix_chg, "pcr": pcr, "sentiment": sentiment}

# ============================================================
# FETCH RECENT NEWS (last 48h) FOR A STOCK
# ============================================================
def fetch_news(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, symbol)
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
# FETCH PRICE + TECHNICALS VIA YFINANCE
# ============================================================
def fetch_technicals(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, symbol)
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
        near_52w = price_now >= high_52w * 0.95   # within 5% of 52W high

        weekly_bull = float(c.iloc[-1]) > float(ema21.iloc[-5]) if len(ema21) > 5 else (price_now > e21)

        # Momentum returns
        r1w = float((c.iloc[-1] / c.iloc[-6]  - 1) * 100) if len(c) >= 6  else 0
        r1m = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else 0
        r3m = float((c.iloc[-1] / c.iloc[-63] - 1) * 100) if len(c) >= 63 else 0

        # Momentum score (weighted: 1W×1 + 1M×2 + 3M×3, normalised to 0-10)
        momentum_raw = r1w * 1 + r1m * 2 + r3m * 3
        momentum_score = round(min(max(momentum_raw / 6, 0), 10), 1)

        # VWAP (cumulative typical-price approximation — free daily bars have
        # no intraday tick data, so this trends toward the long-run average
        # rather than a true session VWAP; same approximation as india_morning_scan.py)
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
# FETCH FUNDAMENTALS + SHORT INTEREST VIA YFINANCE
# ============================================================
def fetch_fundamentals(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, symbol)
        ticker = yf.Ticker(yf_sym)
        info   = ticker.info

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        target_mean = info.get("targetMeanPrice")
        upside_pct = ((target_mean - price) / price * 100) if (target_mean and price) else None

        shares_short       = info.get("sharesShort")
        shares_short_prior = info.get("sharesShortPriorMonth")
        short_falling = bool(
            shares_short is not None and shares_short_prior and shares_short < shares_short_prior
        )

        return {
            "pe":                 info.get("trailingPE"),
            "roe":                info.get("returnOnEquity"),
            "debt_eq":            info.get("debtToEquity"),
            "market_cap":         info.get("marketCap"),
            "sector":             info.get("sector", "N/A"),
            "analyst_rec":        info.get("recommendationKey", "N/A"),
            "target_price":       target_mean,
            "upside_pct":         upside_pct,
            "shares_short":       shares_short,
            "shares_short_prior": shares_short_prior,
            "short_falling":      short_falling,
        }
    except Exception:
        return {}

# ============================================================
# FETCH INSTITUTIONAL HOLDINGS (yfinance 13F QoQ change)
# ============================================================
def fetch_institutional(symbol):
    try:
        yf_sym = YF_SYMBOL_MAP.get(symbol, symbol)
        ticker = yf.Ticker(yf_sym)
        ih = ticker.institutional_holders
        if ih is None or ih.empty or "pctChange" not in ih.columns:
            return {}
        changes = ih["pctChange"].dropna()
        if changes.empty:
            return {}
        rising = int((changes > 0).sum())
        total  = len(changes)
        return {
            "rising_count":    rising,
            "total_count":     total,
            "rising_majority": rising > total / 2,
            "avg_change":      float(changes.mean()),
        }
    except Exception:
        return {}

# ============================================================
# FETCH UNUSUAL WHALES DATA (options flow + dark pool %)
# ============================================================
def fetch_unusualwhales(symbol, uw_client):
    result = {"flow_bullish": False, "flow_signal": "N/A", "dp_elevated": False, "dp_pct_of_baseline": None}
    if uw_client is None:
        return result
    try:
        flow = uw_client.get_flow(symbol)
        if not flow.get("error"):
            result["flow_bullish"] = flow.get("cls") == "bull"
            result["flow_signal"]  = flow.get("signal", "N/A")
    except Exception:
        pass
    try:
        dp = uw_client.get_dark_pool_pct(symbol)
        if not dp.get("error"):
            result["dp_elevated"]        = dp.get("elevated", False)
            result["dp_pct_of_baseline"] = dp.get("pct_of_baseline")
    except Exception:
        pass
    return result

# ============================================================
# SCORE EACH STOCK (out of 16)
# ============================================================
def score_stock(tech, fund, inst, uw, spy_ret):
    score = 0
    flags = []

    if not tech:
        return 0, []

    # ── TREND (2 pts) ──
    if tech.get("bull_trend"):
        score += 1; flags.append("Bull Trend")
    if tech.get("weekly_bull"):
        score += 1; flags.append("Weekly Bull")

    # ── MOMENTUM / OSCILLATOR (4 pts) ──
    if 40 <= tech.get("rsi", 100) <= 65:
        score += 1; flags.append(f"RSI {tech['rsi']:.0f}")
    if tech.get("vol_surge"):
        score += 1; flags.append(f"Vol {tech['vol_ratio']}x")
    if tech.get("bb_squeeze"):
        score += 1; flags.append("BB Squeeze")
    if tech.get("momentum_score", 0) >= 5:
        score += 1; flags.append(f"Mom {tech['momentum_score']}")

    # ── RS vs SPY (2 pts) ──
    r1m = tech.get("ret_1m", 0)
    r3m = tech.get("ret_3m", 0)
    spy_1m = spy_ret.get("1m", 0)
    spy_3m = spy_ret.get("3m", 0)
    rs_1m = r1m - spy_1m
    rs_3m = r3m - spy_3m
    if rs_1m > 3:
        score += 1; flags.append(f"RS+{rs_1m:.0f}% 1M")
    if rs_3m > 5:
        score += 1; flags.append(f"RS+{rs_3m:.0f}% 3M")

    # ── VWAP (1 pt) ──
    if tech.get("above_vwap"):
        score += 1; flags.append("Above VWAP")

    # ── UNUSUAL WHALES: FLOW + DARK POOL (2 pts) ──
    if uw.get("flow_bullish"):
        score += 1; flags.append("Bullish Flow")
    if uw.get("dp_elevated"):
        score += 1; flags.append(f"DarkPool {uw.get('dp_pct_of_baseline')}% of baseline")

    # ── INSTITUTIONAL + SHORT INTEREST (2 pts) ──
    if inst.get("rising_majority"):
        score += 1; flags.append("Inst↑ QoQ")
    if fund.get("short_falling"):
        score += 1; flags.append("Short Covering")

    # ── FUNDAMENTALS (3 pts) ──
    roe = fund.get("roe")
    pe  = fund.get("pe")
    upside = fund.get("upside_pct")
    if roe and roe > 0.12:
        score += 1; flags.append(f"ROE {roe*100:.0f}%")
    if pe and 5 < pe < 40:
        score += 1; flags.append(f"PE {pe:.0f}")
    if upside and upside > 10:
        score += 1; flags.append(f"Upside {upside:.0f}%")

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
def calc_levels(tech, capital=CAPITAL, risk_pct=RISK_PCT, rr=RR):
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
# HTML REPORT (same dark theme as options_report.py)
# ============================================================
_HTML_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #0d1117; color: #c9d1d9;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 15px; line-height: 1.7; padding: 32px 16px;
}
.container { max-width: 1180px; margin: 0 auto; }
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
table { width:100%; border-collapse:collapse; font-size:13.5px; margin-top:4px; }
th {
  background:#21262d; color:#8b949e; text-align:left;
  padding:9px 10px; font-weight:600; font-size:11.5px;
  text-transform:uppercase; letter-spacing:.04em; white-space:nowrap;
}
td { padding:9px 10px; border-bottom:1px solid #21262d; color:#c9d1d9; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
tr:hover td { background:#1c2128; }
td strong { color:#e6edf3; }
.flags-col { white-space:normal; color:#8b949e; font-size:12px; max-width:280px; }
.price-grid {
  display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:14px; margin-bottom:6px;
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
.pill {
  display:inline-block; padding:2px 10px; border-radius:12px;
  font-size:12px; font-weight:600;
}
.pill.bear { background:rgba(248,81,73,.15); color:#f85149; border:1px solid rgba(248,81,73,.3); }
.pill.bull { background:rgba(63,185,80,.15); color:#3fb950; border:1px solid rgba(63,185,80,.3); }
.pill.neutral { background:rgba(210,153,34,.15); color:#d29922; border:1px solid rgba(210,153,34,.3); }
.pos { color:#3fb950; }
.neg { color:#f85149; }
.score-bar-track { display:inline-flex; align-items:center; gap:6px; }
.score-bar-bg { width:70px; height:7px; background:#21262d; border-radius:4px; overflow:hidden; }
.score-bar-fill { height:100%; border-radius:4px; }
.score-bar-fill.high { background:#3fb950; }
.score-bar-fill.mid  { background:#d29922; }
.score-bar-fill.low  { background:#f85149; }
.top-pick-card {
  background:#1c2128; border:1px solid #3fb950; border-radius:10px;
  padding:20px 24px; margin-bottom:18px;
}
.top-pick-card h3 { color:#3fb950; font-size:16px; margin-bottom:10px; }
.top-pick-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:12px; }
.top-pick-grid .label { font-size:11px; color:#8b949e; text-transform:uppercase; }
.top-pick-grid .value { font-size:15px; color:#e6edf3; font-weight:600; margin-top:2px; }
.news-item { padding:8px 0; border-bottom:1px solid #21262d; font-size:13.5px; }
.news-item:last-child { border-bottom:none; }
.news-item strong { color:#58a6ff; }
footer { text-align:center; color:#8b949e; font-size:12px; margin-top:24px; }
"""


def _trend_pill(trend):
    cls = "bull" if trend == "BULL" else "bear" if trend == "BEAR" else "neutral"
    return f'<span class="pill {cls}">{trend}</span>'


def _signed(text):
    cls = "pos" if text.strip().startswith("+") else "neg" if text.strip().startswith("-") else ""
    return f'<span class="{cls}">{html.escape(text)}</span>' if cls else html.escape(text)


def _score_bar(score_str, max_score=16):
    try:
        score = int(score_str.split("/")[0])
    except Exception:
        score = 0
    pct = round(score / max_score * 100)
    tier = "high" if score >= max_score * 0.7 else "mid" if score >= max_score * 0.45 else "low"
    return (
        '<div class="score-bar-track">'
        f'<div class="score-bar-bg"><div class="score-bar-fill {tier}" style="width:{pct}%"></div></div>'
        f'<strong>{html.escape(score_str)}</strong></div>'
    )


def _stock_table_rows(rows):
    out = []
    for r in rows:
        out.append(
            "<tr>"
            f'<td><strong>{html.escape(r["Symbol"])}</strong></td>'
            f'<td>{html.escape(r["Price"])}</td>'
            f'<td>{_signed(r["Change"])}</td>'
            f'<td>{_score_bar(r["Score"])}</td>'
            f'<td>{html.escape(r["RSI"])}</td>'
            f'<td>{_trend_pill(r["Trend"])}</td>'
            f'<td>{html.escape(r["Mom"])}</td>'
            f'<td>{_signed(r["RS 1M"])}</td>'
            f'<td>{_signed(r["RS 3M"])}</td>'
            f'<td>{"▲" if r["VWAP"] == "↑" else "▼"}</td>'
            f'<td>{"▲" if r["Inst QoQ"] == "↑" else ("▼" if r["Inst QoQ"] == "↓" else "—")}</td>'
            f'<td>{html.escape(r["Setup"])}</td>'
            f'<td>{html.escape(r["SL"])}</td>'
            f'<td>{html.escape(r["Target"])}</td>'
            f'<td>{_signed(r["Upside%"])}</td>'
            f'<td>{html.escape(r["Qty"])}</td>'
            f'<td class="flags-col">{html.escape(r["Flags"])}</td>'
            "</tr>"
        )
    return "\n".join(out)


_TABLE_HEADERS = (
    "<tr><th>Symbol</th><th>Price</th><th>Change</th><th>Score</th><th>RSI</th><th>Trend</th>"
    "<th>Mom</th><th>RS 1M</th><th>RS 3M</th><th>VWAP</th><th>Inst QoQ</th><th>Setup</th>"
    "<th>SL</th><th>Target</th><th>Upside%</th><th>Qty</th><th>Flags</th></tr>"
)


def generate_html_report(qualified, sentiment, spy_ret, avoid, watchlist_size, top_n=TOP_N):
    now = datetime.now()
    top = qualified[:top_n]

    mkt_cls = "bull" if sentiment["sentiment"] == "BULLISH" else "bear" if sentiment["sentiment"] == "BEARISH" else "neutral"
    vix = sentiment.get("vix")
    vix_html = f'{vix:.2f} <span class="sub">({sentiment.get("vix_chg", 0):+.1f}%)</span>' if vix is not None else "N/A"
    vix_value_cls = "green" if (vix is not None and vix < 20) else "red" if (vix is not None and vix > 25) else "blue"

    top_pick_html = ""
    if top:
        best = top[0]
        news_html = "".join(
            f'<div class="news-item">{html.escape(h[:110])}</div>' for h in best.get("_news", [])
        ) or '<div class="news-item">No news in the last 48h.</div>'
        top_pick_html = f"""
    <div class="top-pick-card">
      <h3>🏆 Top Pick: {html.escape(best['Symbol'])}</h3>
      <div class="top-pick-grid">
        <div><div class="label">Price</div><div class="value">{html.escape(best['Price'])} ({_signed(best['Change'])})</div></div>
        <div><div class="label">Score</div><div class="value">{html.escape(best['Score'])}</div></div>
        <div><div class="label">Setup</div><div class="value">{html.escape(best['Setup'])}</div></div>
        <div><div class="label">Stop Loss</div><div class="value">{html.escape(best['SL'])}</div></div>
        <div><div class="label">Target</div><div class="value">{html.escape(best['Target'])} ({_signed(best['Upside%'])})</div></div>
        <div><div class="label">Qty</div><div class="value">{html.escape(best['Qty'])} sh-equiv</div></div>
      </div>
      <div style="margin-top:14px;color:#8b949e;font-size:13px;">{html.escape(best['Flags'])}</div>
      <div style="margin-top:14px;">{news_html}</div>
    </div>"""

    avoid_html = ""
    if avoid:
        avoid_rows = "".join(
            f'<tr><td><strong>{html.escape(r["Symbol"])}</strong></td><td>{html.escape(r["Score"])}</td>'
            f'<td>{html.escape(r["RSI"])}</td><td>{_signed(r["RS 1M"])}</td></tr>'
            for r in avoid[:5]
        )
        avoid_html = f"""
  <div class="section">
    <h2>⚠️ Stocks to Avoid (Bearish)</h2>
    <table><tr><th>Symbol</th><th>Score</th><th>RSI</th><th>RS 1M</th></tr>{avoid_rows}</table>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>US Morning Watchlist Scan — {now.strftime('%d %b %Y')}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<div class="container">

  <header>
    <h1>US Morning Watchlist Scan</h1>
    <div class="subtitle">{now.strftime('%A, %d %B %Y — %I:%M %p')} · {watchlist_size} stocks scanned · {len(qualified)} qualified</div>
    <span class="badge {mkt_cls}">Sentiment: {sentiment['sentiment']}</span>
    <span class="badge">VIX {vix:.2f}</span>
    <span class="badge">SPY PCR {sentiment.get('pcr', 0)}</span>
    <span class="badge">SPY 1M {spy_ret.get('1m', 0):+.1f}%</span>
    <span class="badge">SPY 3M {spy_ret.get('3m', 0):+.1f}%</span>
  </header>

  <div class="section">
    <h2>Market Overview</h2>
    <div class="price-grid">
      <div class="price-card">
        <div class="label">Sentiment</div>
        <div class="value {mkt_cls if mkt_cls != 'neutral' else 'blue'}">{sentiment['sentiment']}</div>
      </div>
      <div class="price-card">
        <div class="label">VIX</div>
        <div class="value {vix_value_cls}">{vix_html}</div>
      </div>
      <div class="price-card">
        <div class="label">SPY PCR (volume)</div>
        <div class="value blue">{sentiment.get('pcr', 0)}</div>
      </div>
      <div class="price-card">
        <div class="label">SPY 1M / 3M</div>
        <div class="value blue" style="font-size:17px;">{spy_ret.get('1m',0):+.1f}% / {spy_ret.get('3m',0):+.1f}%</div>
        <div class="sub">benchmark for RS</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Top {len(top)} Swing Trade Candidates</h2>
    <table>{_TABLE_HEADERS}{_stock_table_rows(top)}</table>
  </div>

  {top_pick_html}

  <div class="section">
    <h2>All {len(qualified)} Qualified Stocks</h2>
    <table>{_TABLE_HEADERS}{_stock_table_rows(qualified)}</table>
  </div>

  {avoid_html}

  <footer>Generated by us_morning_scan.py · Not financial advice · Verify levels before trading</footer>
</div>
</body>
</html>"""


# ============================================================
# MAIN SCAN
# ============================================================
def run_morning_scan():
    print(f"\n{Back.BLUE}{Fore.WHITE}{'='*70}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}   US MORNING WATCHLIST SCAN — {datetime.now().strftime('%d %b %Y %I:%M %p')}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{Fore.WHITE}{'='*70}{Style.RESET_ALL}\n")

    print(f"{Fore.CYAN}[1/5] Connecting to Unusual Whales...{Style.RESET_ALL}")
    uw_client = get_uw_client()
    if uw_client is None:
        print(f"  {Fore.YELLOW}UW_API_KEY not set in .env — flow/dark-pool signals will be skipped.{Style.RESET_ALL}")

    print(f"{Fore.CYAN}[2/5] Fetching VIX, PCR proxy & SPY returns...{Style.RESET_ALL}")
    sentiment = fetch_market_sentiment()
    spy_ret   = fetch_spy_returns()
    time.sleep(0.5)

    print(f"{Fore.CYAN}[3/5] Scanning {len(WATCHLIST)} stocks...{Style.RESET_ALL}")
    results = []

    for i, symbol in enumerate(WATCHLIST):
        print(f"  {Fore.WHITE}{i+1:3d}/{len(WATCHLIST)} {symbol:<8}{Style.RESET_ALL}", end="", flush=True)

        tech = fetch_technicals(symbol)
        fund = fetch_fundamentals(symbol)
        inst = fetch_institutional(symbol)
        uw   = fetch_unusualwhales(symbol, uw_client)
        score, flags = score_stock(tech, fund, inst, uw, spy_ret)
        setup = detect_setup(tech)
        sl, tp, qty = calc_levels(tech)

        if tech:
            chg = tech.get("pct_change", 0)
            chg_str = f"{Fore.GREEN}+{chg:.1f}%{Style.RESET_ALL}" if chg > 0 else f"{Fore.RED}{chg:.1f}%{Style.RESET_ALL}"
            rs_str  = f"RS:{tech['ret_1m']:+.0f}%/1M"
            print(f" ${tech['price']:>8.2f} {chg_str}  Score:{score}/16  Mom:{tech['momentum_score']}  {rs_str}  {setup}")
        else:
            print(f"  {Fore.YELLOW}No data{Style.RESET_ALL}")

        if tech:
            results.append({
                "Symbol":    symbol,
                "Price":     f"${tech['price']:.2f}",
                "Change":    f"{tech['pct_change']:+.1f}%",
                "Score":     f"{score}/16",
                "RSI":       f"{tech['rsi']:.0f}",
                "Trend":     "BULL" if tech["bull_trend"] else "BEAR" if tech["bear_trend"] else "NEUT",
                "Mom":       f"{tech['momentum_score']}",
                "RS 1M":     f"{tech['ret_1m'] - spy_ret.get('1m',0):+.1f}%",
                "RS 3M":     f"{tech['ret_3m'] - spy_ret.get('3m',0):+.1f}%",
                "VWAP":      "↑" if tech.get("above_vwap") else "↓",
                "Inst QoQ":  "↑" if inst.get("rising_majority") else ("↓" if inst else "N/A"),
                "Setup":     setup,
                "SL":        f"${sl}" if sl else "N/A",
                "Target":    f"${tp}" if tp else "N/A",
                "Upside%":   f"{((tp - tech['price']) / tech['price'] * 100):+.1f}%" if tp else "N/A",
                "Qty":       str(qty) if qty else "N/A",
                "Flags":     " | ".join(flags[:4]),
                "_score":    score,
                "_momentum": tech["momentum_score"],
                "_rsi":      tech["rsi"],
                "_news":     [],  # filled below
            })

        time.sleep(0.3)

    # Step 4: Fetch news for top candidates only (saves time)
    print(f"\n{Fore.CYAN}[4/5] Fetching news for top candidates...{Style.RESET_ALL}")
    qualified = [r for r in results if r["_score"] >= MIN_SCORE]
    qualified.sort(key=lambda x: (x["_score"], x["_momentum"]), reverse=True)
    top = qualified[:TOP_N]
    for r in top:
        headlines = fetch_news(r["Symbol"])
        r["_news"] = headlines
        time.sleep(0.2)

    print(f"{Fore.CYAN}[5/5] Generating report...{Style.RESET_ALL}\n")

    # ── MARKET OVERVIEW ──
    print(f"{Back.BLUE}{Fore.WHITE} MARKET OVERVIEW {Style.RESET_ALL}")
    mkt_color = Fore.GREEN if sentiment["sentiment"] == "BULLISH" else Fore.RED if sentiment["sentiment"] == "BEARISH" else Fore.YELLOW
    print(f"  Sentiment    : {mkt_color}{sentiment['sentiment']}{Style.RESET_ALL}")
    if sentiment["vix"] is not None:
        vix_color = Fore.GREEN if sentiment["vix"] < 20 else Fore.RED if sentiment["vix"] > 25 else Fore.YELLOW
        print(f"  VIX          : {vix_color}{sentiment['vix']:.2f} ({sentiment['vix_chg']:+.1f}%){Style.RESET_ALL}")
    else:
        print(f"  VIX          : N/A")
    pcr = sentiment["pcr"]
    pcr_color = Fore.GREEN if pcr > 1.0 else Fore.RED if 0 < pcr < 0.7 else Fore.YELLOW
    pcr_note  = "Oversold (Bullish)" if pcr > 1.2 else "Overbought (Bearish)" if 0 < pcr < 0.7 else "Neutral"
    print(f"  SPY PCR (vol): {pcr_color}{pcr} — {pcr_note}{Style.RESET_ALL}")
    s1m = spy_ret.get("1m", 0)
    s3m = spy_ret.get("3m", 0)
    print(f"  SPY 1M/3M    : {s1m:+.1f}% / {s3m:+.1f}%  (benchmark for RS)")
    print()

    # ── TOP 10 TABLE ──
    if top:
        display_cols = ["Symbol","Price","Change","Score","RSI","Trend","Mom","RS 1M","RS 3M","VWAP","Inst QoQ","Setup","SL","Target","Upside%","Qty"]
        display_data = [{k: v for k, v in r.items() if k in display_cols} for r in top]

        print(f"{Back.GREEN}{Fore.BLACK} TOP {len(top)} SWING TRADE CANDIDATES {Style.RESET_ALL}")
        print(tabulate(display_data, headers="keys", tablefmt="rounded_outline"))
        print()

        # ── SIGNAL BREAKDOWN ──
        print(f"{Back.BLUE}{Fore.WHITE} SIGNAL BREAKDOWN {Style.RESET_ALL}")
        for r in top:
            score_val = r["_score"]
            bar   = "█" * score_val + "░" * (16 - score_val)
            color = Fore.GREEN if score_val >= 12 else Fore.YELLOW if score_val >= 8 else Fore.WHITE
            print(f"  {color}{r['Symbol']:<8}{Style.RESET_ALL} [{bar}] {score_val}/16  {r['Flags']}")
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
        print(f"  Momentum   : {best['Mom']} | RS vs SPY: {best['RS 1M']} (1M) / {best['RS 3M']} (3M)")
        print(f"  VWAP       : {'Above' if best['VWAP'] == '↑' else 'Below'} | Inst QoQ: {best['Inst QoQ']}")
        print(f"  Stop Loss  : {best['SL']}")
        print(f"  Target     : {best['Target']}  ({best['Upside%']})")
        print(f"  Quantity   : {best['Qty']} shares (single-leg call/put contracts sized to same $ risk)")
        print(f"  Signals    : {best['Flags']}")
        if best["_news"]:
            print(f"  News       : {best['_news'][0][:80]}")
        print()

    else:
        print(f"{Fore.YELLOW}No stocks met the minimum score of {MIN_SCORE}/16 today.{Style.RESET_ALL}\n")

    # ── AVOID LIST ──
    avoid = [r for r in results if r["_score"] < MIN_SCORE and r.get("Trend") == "BEAR"]
    if avoid:
        print(f"{Back.RED}{Fore.WHITE} STOCKS TO AVOID (Bearish) {Style.RESET_ALL}")
        for r in avoid[:5]:
            print(f"  {Fore.RED}{r['Symbol']:<8}{Style.RESET_ALL} Score:{r['Score']}  RSI:{r['RSI']}  RS:{r['RS 1M']}/1M")
        print()

    print(f"{Fore.CYAN}Scan complete. {len(qualified)} stocks qualified out of {len(WATCHLIST)} scanned.{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Run this script daily at 8-9 AM ET before market opens.{Style.RESET_ALL}\n")

    # Save to CSV + HTML
    if qualified:
        today = datetime.now().strftime("%Y-%m-%d")
        csv_name = f"us_watchlist_{today}.csv"
        save_cols = [k for k in qualified[0].keys() if not k.startswith("_")]
        df = pd.DataFrame(qualified)[save_cols]
        df.to_csv(csv_name, index=False)
        print(f"{Fore.GREEN}Saved to {csv_name}{Style.RESET_ALL}")

        html_name = f"us_watchlist_{today}.html"
        report = generate_html_report(qualified, sentiment, spy_ret, avoid, len(WATCHLIST))
        with open(html_name, "w") as f:
            f.write(report)
        print(f"{Fore.GREEN}Saved to {html_name}{Style.RESET_ALL}\n")

    return qualified

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    run_morning_scan()
