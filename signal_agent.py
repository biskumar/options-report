"""
TradingView MCP → Telegram Signal Agent
Polls TradingView MCP for RSI/MACD/EMA signals and sends Telegram alerts.

Usage:
  python3 signal_agent.py                        # run once
  python3 signal_agent.py --loop 300             # run every 5 minutes

Requirements:
  pip install requests mcp-client   (or use the MCP subprocess approach below)

Config: edit TELEGRAM_TOKEN, CHAT_ID, and WATCHLIST below.
"""

import argparse
import json
import subprocess
import time
import requests
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = "YOUR_BOT_TOKEN_HERE"        # from @BotFather
CHAT_ID        = "YOUR_CHAT_ID_HERE"          # your Telegram chat/user id

WATCHLIST = ["MSFT", "AMZN", "META", "AAPL", "CSCO"]

# Signal thresholds
RSI_OVERSOLD    = 30     # RSI below this → potential BUY
RSI_OVERBOUGHT  = 70     # RSI above this → potential SELL
MACD_HIST_MIN   = 0.05   # histogram must be at least this positive for BUY
VOL_MULTIPLIER  = 1.2    # volume must be >= this × avg for confirmation

# MCP server command (adjust path to match your setup)
MCP_CMD = ["node", "/Users/bishwajitkumar/tradingview-mcp/build/index.js"]

# ── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_notification": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[Telegram error] {e}")


# ── MCP CALLER ───────────────────────────────────────────────────────────────

def call_mcp(tool: str, params: dict) -> dict:
    """
    Call a TradingView MCP tool via stdio JSON-RPC.
    Returns the parsed result dict, or {} on error.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": params},
    }
    try:
        proc = subprocess.run(
            MCP_CMD,
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
        for line in reversed(lines):
            try:
                resp = json.loads(line)
                if "result" in resp:
                    content = resp["result"].get("content", [])
                    if content and isinstance(content, list):
                        return json.loads(content[0].get("text", "{}"))
            except Exception:
                continue
    except Exception as e:
        print(f"[MCP error] {tool}: {e}")
    return {}


# ── SIGNAL ENGINE ─────────────────────────────────────────────────────────────

def analyse_ticker(ticker: str) -> dict | None:
    """
    Pull live data for a ticker and return a signal dict, or None if no signal.
    Signal dict keys: ticker, signal, price, rsi, macd_hist, ema9, ema21, reason
    """
    # 1. Switch chart
    call_mcp("chart_set_symbol", {"symbol": ticker})
    time.sleep(2)

    # 2. Get quote
    quote = call_mcp("quote_get", {"symbol": ticker})
    price = quote.get("last") or quote.get("close")
    if not price:
        return None

    # 3. Get indicators
    studies = call_mcp("data_get_study_values", {})
    if not studies.get("success"):
        return None

    rsi = macd_hist = ema9 = ema21 = None
    rsi_ma = None
    bullish_div = bearish_div = False

    for study in studies.get("studies", []):
        name = study.get("name", "")
        vals = study.get("values", {})

        if "Relative Strength Index" in name:
            rsi    = float(vals.get("RSI", 0) or 0)
            rsi_ma = float(vals.get("RSI-based MA", 0) or 0)
            bullish_div = "Regular Bullish" in vals
            bearish_div = "Regular Bearish" in vals

        elif "Moving Average Convergence" in name:
            h = vals.get("Histogram", "0")
            macd_hist = float(str(h).replace("−", "-").replace("–", "-") or 0)

        elif "Moving Average Exponential" in name:
            v = float(vals.get("EMA", 0) or 0)
            if ema9 is None:
                ema9 = v
            else:
                ema21 = v

    if None in (rsi, macd_hist, ema9, ema21):
        return None

    # 4. Signal logic
    signal = None
    reasons = []

    above_ema9  = price > ema9
    above_ema21 = price > ema21

    # ── BUY conditions ──
    if rsi < RSI_OVERSOLD:
        reasons.append(f"RSI oversold ({rsi:.1f})")
    if bullish_div:
        reasons.append("Regular Bullish Divergence")
    if macd_hist > MACD_HIST_MIN and above_ema9:
        reasons.append(f"MACD hist positive ({macd_hist:+.3f}) + above EMA9")
    if above_ema9 and above_ema21:
        reasons.append("Price above both EMAs")

    buy_score = sum([
        rsi < RSI_OVERSOLD,
        bullish_div,
        macd_hist > MACD_HIST_MIN,
        above_ema9 and above_ema21,
        rsi_ma and rsi > rsi_ma,
    ])

    # ── SELL conditions ──
    sell_reasons = []
    if rsi > RSI_OVERBOUGHT:
        sell_reasons.append(f"RSI overbought ({rsi:.1f})")
    if bearish_div:
        sell_reasons.append("Regular Bearish Divergence")
    if macd_hist < -MACD_HIST_MIN and not above_ema9:
        sell_reasons.append(f"MACD hist negative ({macd_hist:+.3f}) + below EMA9")

    sell_score = sum([
        rsi > RSI_OVERBOUGHT,
        bearish_div,
        macd_hist < -MACD_HIST_MIN,
        not above_ema9 and not above_ema21,
        rsi_ma and rsi < rsi_ma,
    ])

    if buy_score >= 2:
        signal = "BUY"
    elif sell_score >= 2:
        signal = "SELL"
        reasons = sell_reasons

    if not signal:
        return None

    return {
        "ticker":    ticker,
        "signal":    signal,
        "price":     price,
        "rsi":       rsi,
        "macd_hist": macd_hist,
        "ema9":      ema9,
        "ema21":     ema21,
        "reason":    " | ".join(reasons),
    }


# ── ALERT FORMATTER ───────────────────────────────────────────────────────────

SIGNAL_EMOJI = {"BUY": "🟢", "SELL": "🔴"}

def format_alert(sig: dict) -> str:
    e = SIGNAL_EMOJI.get(sig["signal"], "⚪")
    ts = datetime.now().strftime("%H:%M:%S ET")
    above_below = "above" if sig["price"] > sig["ema21"] else "below"
    return (
        f"{e} <b>{sig['signal']} SIGNAL — {sig['ticker']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💲 Price:      <b>${sig['price']:.2f}</b>\n"
        f"📊 RSI:        <b>{sig['rsi']:.2f}</b>\n"
        f"📈 MACD Hist:  <b>{sig['macd_hist']:+.4f}</b>\n"
        f"〽️ EMA9:       ${sig['ema9']:.2f}\n"
        f"〽️ EMA21:      ${sig['ema21']:.2f}  ({above_below} EMA21)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Reason: {sig['reason']}\n"
        f"🕐 {ts}"
    )


# ── MAIN ─────────────────────────────────────────────────────────────────────

# Track sent alerts to avoid duplicates within a session
_sent: dict[str, str] = {}   # ticker → last signal sent

def run_once():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning {len(WATCHLIST)} tickers...")
    alerts_sent = 0

    for ticker in WATCHLIST:
        print(f"  → {ticker}", end=" ", flush=True)
        sig = analyse_ticker(ticker)

        if sig is None:
            print("no signal")
            continue

        # Skip if same signal was already sent this session
        if _sent.get(ticker) == sig["signal"]:
            print(f"(duplicate {sig['signal']} skipped)")
            continue

        msg = format_alert(sig)
        print(f"\n{msg}\n")
        send_telegram(msg)
        _sent[ticker] = sig["signal"]
        alerts_sent += 1
        time.sleep(1)  # rate limit

    if alerts_sent == 0:
        print("  No new signals this scan.")
    else:
        print(f"  {alerts_sent} alert(s) sent.")


def main():
    parser = argparse.ArgumentParser(description="TradingView → Telegram signal agent")
    parser.add_argument("--loop", type=int, default=0,
                        help="Repeat every N seconds (0 = run once)")
    args = parser.parse_args()

    if not TELEGRAM_TOKEN.startswith("YOUR"):
        send_telegram("🤖 <b>Signal Agent Started</b>\nWatching: " + ", ".join(WATCHLIST))

    if args.loop > 0:
        print(f"Running every {args.loop}s. Ctrl+C to stop.")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[Error] {e}")
            time.sleep(args.loop)
    else:
        run_once()


if __name__ == "__main__":
    main()
