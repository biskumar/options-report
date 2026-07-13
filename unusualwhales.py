"""
Unusual Whales API client
Usage: import unusualwhales as uw; client = uw.UWClient("YOUR_API_KEY")

Set key via env var:  export UW_API_KEY=your_key
Get key at:           https://unusualwhales.com/

Endpoints covered:
  - Options flow        /api/stock/{ticker}/flow
  - Flow alerts         /api/option-trade/flow-alerts
  - Option chain        /api/stock/{ticker}/option-chains
  - Max pain            /api/stock/{ticker}/max-pain
  - IV rank             /api/stock/{ticker}/iv-rank
  - GEX levels          /api/gex-greeks/gex-levels
  - Ticker overview     /api/stock/{ticker}/flow-recent
"""

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


def _load_dotenv() -> None:
    """Load .env from the same directory as this file, if present."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()


BASE_URL = "https://api.unusualwhales.com"
DEFAULT_TIMEOUT = 12


class UWError(Exception):
    pass


class UWClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("UW_API_KEY") or ""
        if not self.api_key:
            raise UWError("No API key. Pass api_key= or set UW_API_KEY env var.")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = f"{BASE_URL}{path}"
        if params:
            from urllib.parse import urlencode
            url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "options-report/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:200]
            except Exception:
                pass
            raise UWError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise UWError(str(e)) from e

    # ── Public methods ────────────────────────────────────────────────────────

    def get_flow(
        self,
        ticker: str,
        expiry: Optional[str] = None,
        limit: int = 200,
    ) -> dict:
        """
        Recent options flow for a ticker.
        Returns aggregated bull/bear premium, sweep counts, unusual counts,
        net flow signal, and top big-money prints.

        expiry: ISO date string "2026-07-10" — filters to that expiry if given.
        """
        raw = self._get(f"/api/stock/{ticker.upper()}/flow-recent", {"limit": limit})
        # flow-recent returns a bare list, not {"data": [...]}
        rows = raw if isinstance(raw, list) else raw.get("data", [])

        if expiry:
            rows = [r for r in rows if (r.get("expiry_date") or r.get("expiry", "")).startswith(expiry)]

        bull_premium = bear_premium = 0.0
        sweep_bull = sweep_bear = unusual_bull = unusual_bear = 0
        top_flows: list = []

        for r in rows:
            opt_type = (r.get("option_type") or r.get("type") or "").upper()
            # UW uses tags: ["ask_side"/"bid_side"] — no direct 'side' field
            tags     = r.get("tags") or []
            if "ask_side" in tags:   side = "ASK"
            elif "bid_side" in tags: side = "BID"
            else:                    side = (r.get("side") or "").upper()
            premium  = float(r.get("premium") or r.get("total_premium") or 0)
            is_sweep = "sweep" in tags or bool(r.get("is_sweep"))
            is_unu   = "unusual" in tags or bool(r.get("is_unusual"))
            strike   = r.get("strike") or r.get("strike_price", "?")
            exp_val  = r.get("expiry_date") or r.get("expiry", "?")

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

            if premium > 50_000:
                top_flows.append({
                    "type":    opt_type,
                    "strike":  strike,
                    "expiry":  exp_val,
                    "side":    "BUY" if side == "ASK" else "SELL",
                    "premium": premium,
                    "sweep":   is_sweep,
                    "unusual": is_unu,
                    "bull":    is_bull,
                })

        total_premium = bull_premium + bear_premium
        if total_premium == 0:
            return {"error": "No premium data in flow", "total_rows": len(rows)}

        bull_pct = round(bull_premium / total_premium * 100, 1)
        bear_pct = round(bear_premium / total_premium * 100, 1)
        net_pct  = round(bull_pct - bear_pct, 1)

        if net_pct >= 15:   signal, cls = f"Strongly bullish (+{net_pct}% net call premium)", "bull"
        elif net_pct >= 5:  signal, cls = f"Mildly bullish (+{net_pct}% net call premium)",  "bull"
        elif net_pct <= -15: signal, cls = f"Strongly bearish ({net_pct}% net put premium)", "bear"
        elif net_pct <= -5:  signal, cls = f"Mildly bearish ({net_pct}% net put premium)",   "bear"
        else:                signal, cls = f"Mixed/neutral ({net_pct:+.1f}% net)",            "neutral"

        top_flows.sort(key=lambda x: x["premium"], reverse=True)
        return {
            "bull_premium": bull_premium,
            "bear_premium": bear_premium,
            "bull_pct":     bull_pct,
            "bear_pct":     bear_pct,
            "net_pct":      net_pct,
            "sweep_bull":   sweep_bull,
            "sweep_bear":   sweep_bear,
            "unusual_bull": unusual_bull,
            "unusual_bear": unusual_bear,
            "total_rows":   len(rows),
            "signal":       signal,
            "cls":          cls,
            "top_flows":    top_flows[:10],
        }

    def get_flow_alerts(
        self,
        ticker: Optional[str] = None,
        min_premium: int = 100_000,
        limit: int = 50,
    ) -> list[dict]:
        """
        Market-wide (or ticker-specific) unusual flow alerts.
        Returns list of alerts sorted by premium descending.

        min_premium: filter out alerts below this dollar value.
        """
        params: dict = {"limit": limit}
        if ticker:
            # ticker-specific endpoint is faster and more relevant
            raw = self._get(f"/api/stock/{ticker.upper()}/flow-alerts", params)
        else:
            raw = self._get("/api/option-trades/flow-alerts", params)
        rows = raw.get("data", [])

        today = date.today()
        alerts = []
        for r in rows:
            premium = float(r.get("total_premium") or r.get("premium") or 0)
            if premium < min_premium:
                continue
            # UW flow-alerts: ask_side = buy pressure (bullish for calls, bearish for puts)
            ask_prem = float(r.get("total_ask_side_prem") or 0)
            bid_prem = float(r.get("total_bid_side_prem") or 0)
            side = "BUY" if ask_prem >= bid_prem else "SELL"

            expiry = r.get("expiry")
            dte = None
            if expiry:
                try:
                    dte = (date.fromisoformat(expiry) - today).days
                except ValueError:
                    dte = None

            vol_oi_ratio = r.get("volume_oi_ratio")
            vol_oi_ratio = float(vol_oi_ratio) if vol_oi_ratio is not None else None

            alerts.append({
                "ticker":           r.get("ticker", "?"),
                "type":             (r.get("type") or "?").upper(),
                "strike":           r.get("strike"),
                "expiry":           expiry,
                "dte":              dte,
                "side":             side,
                "premium":          premium,
                "underlying_price": float(r.get("underlying_price") or 0) or None,
                "sweep":            bool(r.get("has_sweep")),
                "block":            bool(r.get("has_floor")),
                "spread":           bool(r.get("has_multileg")),
                "volume_oi_ratio":  vol_oi_ratio,
                "new_positioning":  bool(vol_oi_ratio is not None and vol_oi_ratio > 1.0),
                "all_opening":      bool(r.get("all_opening_trades")),
                "rule":             r.get("alert_rule", ""),
                "trade_count":      int(r.get("trade_count") or 0),
            })

        alerts.sort(key=lambda x: x["premium"], reverse=True)
        return alerts

    def get_option_chain(
        self,
        ticker: str,
        expiry: Optional[str] = None,
    ) -> dict:
        """
        Full option chain from Unusual Whales.
        Returns calls/puts DataFrames-ready dicts with strike, OI, volume, IV, delta, gamma.

        expiry: "2026-07-10" — if None returns nearest expiry.
        """
        params = {}
        if expiry:
            params["expiry"] = expiry
        raw = self._get(f"/api/stock/{ticker.upper()}/option-chains", params)
        data = raw.get("data", {})

        calls = data.get("calls") or []
        puts  = data.get("puts")  or []

        def _parse(rows: list) -> list[dict]:
            out = []
            for r in rows:
                out.append({
                    "strike":         float(r.get("strike") or 0),
                    "expiry":         r.get("expiry_date") or r.get("expiry"),
                    "last":           float(r.get("last_price") or r.get("lastPrice") or 0),
                    "bid":            float(r.get("bid") or 0),
                    "ask":            float(r.get("ask") or 0),
                    "volume":         int(r.get("volume") or 0),
                    "open_interest":  int(r.get("open_interest") or r.get("openInterest") or 0),
                    "iv":             float(r.get("implied_volatility") or r.get("impliedVolatility") or 0),
                    "delta":          float(r.get("delta") or 0),
                    "gamma":          float(r.get("gamma") or 0),
                    "theta":          float(r.get("theta") or 0),
                    "vega":           float(r.get("vega") or 0),
                })
            return sorted(out, key=lambda x: x["strike"])

        return {
            "ticker": ticker.upper(),
            "expiry": expiry,
            "calls":  _parse(calls),
            "puts":   _parse(puts),
        }

    def get_max_pain(self, ticker: str, expiry: Optional[str] = None) -> dict:
        """
        Max pain strike from Unusual Whales.
        Returns max_pain, call_oi_weighted, put_oi_weighted.

        expiry: "2026-07-10"
        """
        params = {}
        if expiry:
            params["expiry"] = expiry
        raw = self._get(f"/api/stock/{ticker.upper()}/max-pain", params)
        data = raw.get("data", [])
        # data is a list of {expiry, max_pain, close, open, ...}
        # if expiry given, find matching row; else use first
        row = {}
        if isinstance(data, list) and data:
            if expiry:
                row = next((d for d in data if d.get("expiry") == expiry), data[0])
            else:
                row = data[0]
        elif isinstance(data, dict):
            row = data

        return {
            "ticker":            ticker.upper(),
            "expiry":            row.get("expiry", expiry),
            "max_pain":          float(row.get("max_pain") or 0),
            "next_upper_strike": float(row.get("next_upper_strike") or 0),
            "next_lower_strike": float(row.get("next_lower_strike") or 0),
            "close":             float(row.get("close") or 0),
        }

    def get_iv_rank(self, ticker: str) -> dict:
        """
        IV Rank and IV Percentile from Unusual Whales.
        Returns iv_rank (0–100), iv_percentile, current_iv, hv30.
        """
        raw = self._get(f"/api/stock/{ticker.upper()}/iv-rank")
        data = raw.get("data", [])
        # data is a list sorted newest-first: [{date, close, volatility, iv_rank_1y}, ...]
        row = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})

        iv_rank = float(row.get("iv_rank_1y") or row.get("iv_rank") or 0)
        current_iv = float(row.get("volatility") or 0)
        if iv_rank >= 80:   iv_label = "Very High — options expensive"
        elif iv_rank >= 60: iv_label = "High"
        elif iv_rank >= 40: iv_label = "Moderate"
        elif iv_rank >= 20: iv_label = "Low — options cheap, favor buying"
        else:               iv_label = "Very Low — options very cheap"

        return {
            "ticker":     ticker.upper(),
            "iv_rank":    iv_rank,
            "current_iv": current_iv,
            "iv_label":   iv_label,
            "date":       row.get("date", ""),
        }

    def get_gex(
        self,
        ticker: Optional[str] = None,
        expiry: Optional[str] = None,
    ) -> dict:
        """
        Gamma Exposure (GEX) levels from Unusual Whales.
        Returns net_gex, top_pin_strike, gex_flip_strike, top_strikes list.

        ticker: if None returns market-wide GEX.
        """
        params: dict = {}
        if ticker:
            params["ticker"] = ticker.upper()
        if expiry:
            params["expiry"] = expiry
        path = f"/api/stock/{ticker.upper()}/gex-levels" if ticker else "/api/gex-greeks/gex-levels"
        raw = self._get(path, params if not ticker else {k: v for k, v in params.items() if k != "ticker"})
        data = raw.get("data", {})

        if isinstance(data, list):
            # List of {strike, gex} rows
            strikes = []
            for r in data:
                strikes.append({
                    "strike": float(r.get("strike") or 0),
                    "gex":    float(r.get("gex") or r.get("gamma_exposure") or 0),
                })
            strikes.sort(key=lambda x: x["strike"])
            net_gex = sum(s["gex"] for s in strikes)
            top_pin = max(strikes, key=lambda x: x["gex"])   if strikes else {}
            flip    = min(strikes, key=lambda x: x["gex"])   if strikes else {}

            if net_gex > 0:   regime = "Pinning — dealers long gamma, expect mean-reversion"
            elif net_gex < 0: regime = "Trending — dealers short gamma, expect momentum moves"
            else:             regime = "Neutral"

            return {
                "ticker":      ticker,
                "net_gex":     round(net_gex, 2),
                "regime":      regime,
                "top_pin_strike":  top_pin.get("strike"),
                "gex_flip_strike": flip.get("strike"),
                "strikes":     strikes,
            }

        # UW stock gex-levels returns: {call_wall, put_wall, gamma_flip, gamma_magnet}
        call_wall     = data.get("call_wall")
        put_wall      = data.get("put_wall")
        gamma_flip    = data.get("gamma_flip")
        gamma_magnet  = data.get("gamma_magnet")

        regime = "Unknown"
        if gamma_flip is None:
            regime = "No gamma flip — strong directional bias (likely trending)"
        elif gamma_magnet:
            regime = f"Gamma magnet at ${gamma_magnet} — price likely gravitates here"

        return {
            "ticker":         ticker,
            "call_wall":      float(call_wall) if call_wall else None,
            "put_wall":       float(put_wall) if put_wall else None,
            "gamma_flip":     float(gamma_flip) if gamma_flip else None,
            "gamma_magnet":   float(gamma_magnet) if gamma_magnet else None,
            "regime":         regime,
        }

    def get_dark_pool_pct(self, ticker: str, lookback_days: int = 20, max_backtrack: int = 5) -> dict:
        """
        Dark pool print intensity (shares/minute) on the most recent
        completed session vs the average of 3 baseline sessions spaced a
        week apart (`lookback_days`, +7, +14 back) — a proxy for "elevated"
        dark pool activity.

        UW's /api/darkpool/{ticker} is capped at limit=500 rows per call and
        returns individual trade prints, not a daily total — for a liquid
        name 500 prints can be under a full session (e.g. UNH: ~500 prints
        across ~7 trading hours), so getting a true 20-30 day daily % of
        consolidated volume would need dozens of paginated calls per ticker.

        Comparing "now" to "N days ago" doesn't work either: called
        pre-market, "now" only has a couple of thin overnight prints, while
        an arbitrary past timestamp usually lands mid-session — comparing a
        near-empty window to a busy one always reads as "quiet," regardless
        of actual dark pool interest. So this anchors samples to specific
        calendar days via the `date` param (most recent completed session
        for "recent"), each capped at 500 rows, and compares shares/minute
        across each session's own actual print span. A *single* baseline
        day is still noisy — e.g. one landing the day before quarterly
        triple-witching reads as unusually heavy market-wide and makes
        every ticker look "quiet" by comparison — so the baseline averages
        3 sessions a week apart instead of relying on just one.
        """
        ticker = ticker.upper()

        def _session_rate(date_str: str):
            raw = self._get(f"/api/darkpool/{ticker}", {"date": date_str, "limit": 500})
            rows = raw.get("data", []) if isinstance(raw, dict) else (raw or [])
            rows = [r for r in rows if not r.get("canceled")]
            times = []
            for r in rows:
                ts = r.get("executed_at")
                if not ts:
                    continue
                try:
                    times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
                except Exception:
                    continue
            if len(times) < 2:
                return None
            span_min = max((max(times) - min(times)).total_seconds() / 60.0, 1.0)
            total_shares = sum(int(r.get("size") or 0) for r in rows)
            return total_shares / span_min

        def _nearest_session(start: datetime):
            d = start
            for _ in range(max_backtrack):
                if d.weekday() < 5:  # skip Sat/Sun; holidays just fall through to next backtrack
                    rate = _session_rate(d.strftime("%Y-%m-%d"))
                    if rate is not None:
                        return d.strftime("%Y-%m-%d"), rate
                d -= timedelta(days=1)
            return None, None

        recent_date, recent_rate = _nearest_session(datetime.now())
        if recent_rate is None:
            return {"error": "No recent darkpool trades"}

        baseline_samples = []
        for offset in (lookback_days, lookback_days + 7, lookback_days + 14):
            b_date, b_rate = _nearest_session(datetime.now() - timedelta(days=offset))
            if b_rate is not None:
                baseline_samples.append((b_date, b_rate))

        if not baseline_samples:
            return {"error": "No baseline darkpool trades"}

        baseline_rate = sum(r for _, r in baseline_samples) / len(baseline_samples)
        pct_of_baseline = round(recent_rate / baseline_rate * 100, 0) if baseline_rate > 0 else None

        return {
            "ticker":          ticker,
            "recent_date":     recent_date,
            "baseline_dates":  [d for d, _ in baseline_samples],
            "recent_rate":     round(recent_rate, 0),
            "baseline_rate":   round(baseline_rate, 0),
            "pct_of_baseline": pct_of_baseline,
            "elevated":        baseline_rate > 0 and recent_rate > baseline_rate * 1.2,
        }

    def get_greek_exposure_strike(self, ticker: str) -> dict:
        """
        DEX (delta), Vanna, and Charm exposure per strike from Unusual Whales.
        Used to spot dealer hedging pressure building into the open.

        Returns {"strikes": [...], "top_dex_strike": {...}, "top_vanna_strike": {...}}
        where "top" = largest absolute net value across strikes.
        """
        raw = self._get(f"/api/stock/{ticker.upper()}/greek-exposure/strike")
        rows = raw.get("data", [])

        strikes = []
        for r in rows:
            call_delta = float(r.get("call_delta") or 0)
            put_delta  = float(r.get("put_delta") or 0)
            call_vanna = float(r.get("call_vanna") or 0)
            put_vanna  = float(r.get("put_vanna") or 0)
            call_charm = float(r.get("call_charm") or 0)
            put_charm  = float(r.get("put_charm") or 0)
            call_gex   = float(r.get("call_gex") or 0)
            put_gex    = float(r.get("put_gex") or 0)
            strikes.append({
                "strike":     float(r.get("strike") or 0),
                "net_delta":  call_delta + put_delta,
                "net_vanna":  call_vanna + put_vanna,
                "net_charm":  call_charm + put_charm,
                "net_gex":    call_gex + put_gex,
            })
        strikes.sort(key=lambda x: x["strike"])

        top_dex   = max(strikes, key=lambda x: abs(x["net_delta"])) if strikes else {}
        top_vanna = max(strikes, key=lambda x: abs(x["net_vanna"])) if strikes else {}

        return {
            "ticker":           ticker.upper(),
            "strikes":          strikes,
            "top_dex_strike":   top_dex,
            "top_vanna_strike": top_vanna,
        }

    def get_darkpool_prints(
        self,
        ticker: str,
        min_premium: int = 200_000,
        date_str: Optional[str] = None,
        max_backtrack: int = 5,
    ) -> dict:
        """
        Large dark pool prints from the most recent completed session (or a
        given date), filtered to premium >= min_premium. Used to flag blocks
        near pre-market GEX levels.
        """
        ticker = ticker.upper()

        def _prints_for(d: str) -> list:
            raw = self._get(f"/api/darkpool/{ticker}", {"date": d, "limit": 500})
            rows = raw.get("data", []) if isinstance(raw, dict) else (raw or [])
            return [r for r in rows if not r.get("canceled")]

        if date_str:
            session_date, rows = date_str, _prints_for(date_str)
        else:
            d = datetime.now()
            session_date, rows = None, []
            for _ in range(max_backtrack):
                if d.weekday() < 5:
                    candidate = d.strftime("%Y-%m-%d")
                    found = _prints_for(candidate)
                    if found:
                        session_date, rows = candidate, found
                        break
                d -= timedelta(days=1)

        if not rows:
            return {"error": "No darkpool prints found", "ticker": ticker}

        prints = []
        for r in rows:
            premium = float(r.get("premium") or 0)
            if premium < min_premium:
                continue
            prints.append({
                "price":        float(r.get("price") or 0),
                "size":         int(r.get("size") or 0),
                "premium":      premium,
                "executed_at":  r.get("executed_at"),
            })
        prints.sort(key=lambda x: x["premium"], reverse=True)

        return {
            "ticker":       ticker,
            "session_date": session_date,
            "prints":       prints,
        }

    def get_congress_trades(self, ticker: str, lookback_days: int = 60) -> list[dict]:
        """
        Congressional trading filings for a ticker (House + Senate), filtered
        to filings within lookback_days. Empty list if none filed recently.
        """
        raw = self._get("/api/congress/recent-trades", {"ticker": ticker.upper()})
        rows = raw.get("data", [])
        cutoff = date.today() - timedelta(days=lookback_days)

        trades = []
        for r in rows:
            filed = r.get("filed_at_date")
            try:
                if filed and date.fromisoformat(filed) < cutoff:
                    continue
            except ValueError:
                pass
            trades.append({
                "name":              r.get("name", "?"),
                "member_type":       r.get("member_type", ""),
                "txn_type":          r.get("txn_type", ""),
                "amounts":           r.get("amounts", ""),
                "transaction_date":  r.get("transaction_date"),
                "filed_at_date":     filed,
            })
        return trades

    def get_insider_trades(self, ticker: str, lookback_days: int = 90) -> list[dict]:
        """
        Insider (Form 4) transactions for a ticker, filtered to filings
        within lookback_days. Empty list if none filed recently.

        Note: the UW API only respects the `ticker_symbol` query param here —
        `ticker`/`symbol`/`tickers` are silently ignored and return the
        market-wide feed instead.
        """
        raw = self._get("/api/insider/transactions", {"ticker_symbol": ticker.upper()})
        rows = raw.get("data", [])
        cutoff = date.today() - timedelta(days=lookback_days)

        trades = []
        for r in rows:
            filed = r.get("filing_date")
            try:
                if filed and date.fromisoformat(filed) < cutoff:
                    continue
            except ValueError:
                pass
            title = "Officer" if r.get("is_officer") else "Director" if r.get("is_director") \
                else "10% Owner" if r.get("is_ten_percent_owner") else "Insider"
            trades.append({
                "owner_name":           r.get("owner_name", "?"),
                "title":                title,
                "transaction_code":     r.get("transaction_code", ""),
                "amount":               r.get("amount"),
                "price":                float(r.get("stock_price") or 0) or None,
                "shares_owned_before":  r.get("shares_owned_before"),
                "shares_owned_after":   r.get("shares_owned_after"),
                "filing_date":          filed,
            })
        return trades

    def get_full_analysis(
        self,
        ticker: str,
        expiry: Optional[str] = None,
        min_alert_premium: int = 100_000,
    ) -> dict:
        """
        Convenience method: fetch all relevant UW data for a ticker in one call.
        Returns combined dict with keys: flow, flow_alerts, max_pain, iv_rank, gex.
        option_chain is NOT included by default (large payload) — call get_option_chain separately.

        Each sub-dict has an 'error' key set if that endpoint failed.
        """
        results: dict = {
            "ticker": ticker.upper(),
            "expiry": expiry,
        }

        for key, fn, kwargs in [
            ("flow",         self.get_flow,        {"ticker": ticker, "expiry": expiry}),
            ("flow_alerts",  self.get_flow_alerts,  {"ticker": ticker, "min_premium": min_alert_premium}),
            ("max_pain",     self.get_max_pain,     {"ticker": ticker, "expiry": expiry}),
            ("iv_rank",      self.get_iv_rank,      {"ticker": ticker}),
            ("gex",          self.get_gex,          {"ticker": ticker, "expiry": expiry}),
        ]:
            try:
                results[key] = fn(**kwargs)
            except UWError as e:
                results[key] = {"error": str(e)}

        return results

    def print_summary(self, ticker: str, expiry: Optional[str] = None) -> None:
        """Print a human-readable terminal summary for a ticker."""
        print(f"\n{'='*60}")
        print(f"  Unusual Whales — {ticker.upper()}  |  Expiry: {expiry or 'nearest'}")
        print(f"{'='*60}")

        data = self.get_full_analysis(ticker, expiry)

        # Flow
        flow = data.get("flow", {})
        if flow.get("error"):
            print(f"  Flow:     ERROR — {flow['error']}")
        else:
            print(f"  Flow:     {flow.get('signal','?')}")
            print(f"            Bull {flow.get('bull_pct',0):.1f}% / Bear {flow.get('bear_pct',0):.1f}%  |  "
                  f"Sweeps B/B: {flow.get('sweep_bull',0)}/{flow.get('sweep_bear',0)}  |  "
                  f"Unusual B/B: {flow.get('unusual_bull',0)}/{flow.get('unusual_bear',0)}")

        # Max Pain
        mp = data.get("max_pain", {})
        if mp.get("error"):
            print(f"  Max Pain: ERROR — {mp['error']}")
        else:
            print(f"  Max Pain: ${mp.get('max_pain',0):.2f}")

        # IV Rank
        ivr = data.get("iv_rank", {})
        if ivr.get("error"):
            print(f"  IV Rank:  ERROR — {ivr['error']}")
        else:
            print(f"  IV Rank:  {ivr.get('iv_rank',0):.1f}  ({ivr.get('iv_label','')})")
            print(f"            Current IV: {ivr.get('current_iv',0)*100:.1f}%  |  HV30: {ivr.get('hv30',0)*100:.1f}%")

        # GEX
        gex = data.get("gex", {})
        if gex.get("error"):
            print(f"  GEX:      ERROR — {gex['error']}")
        else:
            print(f"  GEX:      Net {gex.get('net_gex',0):+.2f}  |  {gex.get('regime','')}")
            print(f"            Pin: ${gex.get('top_pin_strike','?')}  |  Flip: ${gex.get('gex_flip_strike','?')}")

        # Flow Alerts
        alerts = data.get("flow_alerts", [])
        if isinstance(alerts, dict) and alerts.get("error"):
            print(f"  Alerts:   ERROR — {alerts['error']}")
        elif alerts:
            print(f"\n  Top Flow Alerts (>{min(a['premium'] for a in alerts)/1000:.0f}K):")
            print(f"  {'Type':<6} {'Strike':<8} {'Expiry':<12} {'Side':<6} {'Premium':<10} Flags")
            print(f"  {'-'*55}")
            for a in alerts[:8]:
                flags = ("🔥 " if a["sweep"] else "") + ("🧱 " if a["block"] else "") + ("↔️ " if a["spread"] else "")
                pre_str = f"${a['premium']/1000:.0f}K" if a["premium"] < 1e6 else f"${a['premium']/1e6:.2f}M"
                print(f"  {a['type']:<6} ${a['strike']:<7} {str(a['expiry']):<12} {a['side']:<6} {pre_str:<10} {flags}")

        print(f"{'='*60}\n")


# ── CLI usage ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unusual Whales options data")
    parser.add_argument("ticker", help="Stock ticker (e.g. ORCL)")
    parser.add_argument("--expiry", help="Expiry date YYYY-MM-DD")
    parser.add_argument("--key", default=os.environ.get("UW_API_KEY"), help="API key")
    parser.add_argument("--chain", action="store_true", help="Also fetch option chain")
    parser.add_argument(
        "--endpoint",
        choices=["flow", "alerts", "chain", "maxpain", "ivrank", "gex", "all"],
        default="all",
        help="Which endpoint to call (default: all)"
    )
    args = parser.parse_args()

    if not args.key:
        print("ERROR: Set UW_API_KEY env var or pass --key YOUR_KEY")
        raise SystemExit(1)

    client = UWClient(args.key)

    if args.endpoint == "flow":
        import pprint; pprint.pprint(client.get_flow(args.ticker, args.expiry))
    elif args.endpoint == "alerts":
        import pprint; pprint.pprint(client.get_flow_alerts(args.ticker))
    elif args.endpoint == "chain":
        import pprint; pprint.pprint(client.get_option_chain(args.ticker, args.expiry))
    elif args.endpoint == "maxpain":
        import pprint; pprint.pprint(client.get_max_pain(args.ticker, args.expiry))
    elif args.endpoint == "ivrank":
        import pprint; pprint.pprint(client.get_iv_rank(args.ticker))
    elif args.endpoint == "gex":
        import pprint; pprint.pprint(client.get_gex(args.ticker, args.expiry))
    else:
        client.print_summary(args.ticker, args.expiry)
