"""Bridges to the repo-root unusualwhales.py client (Unusual Whales REST
API), adapting ticker_option_analyzer.py's watchlist_scan() for this app's
US watchlist. Deliberately NOT cached like legacy_bridge.get_watchlist()'s
15-minute TTL -- the user wants every page load to pull fresh flow/IV/GEX
data, since that's the whole point of an "unusual flow" screen.

Each ticker needs 3 sequential UW HTTP calls (~1.6s total observed) run
synchronously inside the UWClient; run_in_executor alone would still do
all ~37 tickers one after another (~60s). A small thread pool fans the
per-ticker work out concurrently so a full watchlist refresh takes only a
few seconds instead of a minute."""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_MIN_PREMIUM = 250_000
MAX_WORKERS = 10


def _analyze_one(client, ticker: str, min_premium: int) -> dict:
    from unusualwhales import UWError

    try:
        gex = client.get_gex(ticker)
    except UWError:
        gex = {"error": True}
    try:
        iv = client.get_iv_rank(ticker)
    except UWError:
        iv = {"error": True}
    try:
        alerts = client.get_flow_alerts(ticker, min_premium=min_premium, limit=30)
    except UWError:
        alerts = []

    qualifying = [a for a in alerts if a["sweep"] or a["block"]]
    call_premium = sum(a["premium"] for a in qualifying if a["type"] == "CALL")
    put_premium = sum(a["premium"] for a in qualifying if a["type"] == "PUT")
    flow_dir = "bull" if call_premium > put_premium else "bear" if put_premium > call_premium else "neutral"

    score = 0
    score += 1 if len(qualifying) >= 2 else 0
    score += 1 if (not iv.get("error") and iv.get("iv_rank", 0) > 60) else 0
    score += 1 if any(not a["spread"] for a in qualifying) else 0
    score += 1 if flow_dir != "neutral" else 0

    return {
        "ticker": ticker,
        "score": score,
        "flowDir": flow_dir,
        "callPremium": call_premium,
        "putPremium": put_premium,
        "sweepCount": sum(1 for a in qualifying if a["sweep"]),
        "blockCount": sum(1 for a in qualifying if a["block"]),
        "qualifyingCount": len(qualifying),
        "ivRank": None if iv.get("error") else round(iv.get("iv_rank", 0), 1),
        "gexRegime": None if gex.get("error") else gex.get("regime"),
        "callWall": None if gex.get("error") else gex.get("call_wall"),
        "putWall": None if gex.get("error") else gex.get("put_wall"),
    }


def _scan_blocking(tickers: list[str], min_premium: int) -> list[dict]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from unusualwhales import UWClient, UWError

    client = UWClient()
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_analyze_one, client, t, min_premium): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            try:
                results.append(fut.result())
            except UWError as e:
                results.append({"ticker": ticker, "error": str(e)})
            except Exception as e:
                results.append({"ticker": ticker, "error": str(e)})

    # Highest signal-quality score first; alphabetical within a score so
    # the table doesn't visibly reshuffle rows with the same score on
    # every refresh.
    results.sort(key=lambda r: (-r.get("score", -1), r["ticker"]))
    return results


async def scan_watchlist(tickers: list[str], min_premium: int = DEFAULT_MIN_PREMIUM) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scan_blocking, tickers, min_premium)
