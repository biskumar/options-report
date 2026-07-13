import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from unusualwhales import UWError  # noqa: E402

from app.services import unusual_whales_service  # noqa: E402
from app.services.unusual_whales_service import _analyze_one  # noqa: E402


class FakeClient:
    def __init__(self, gex=None, iv=None, alerts=None, raise_on=()):
        self._gex = gex if gex is not None else {"regime": "Pinning"}
        self._iv = iv if iv is not None else {"iv_rank": 50.0}
        self._alerts = alerts if alerts is not None else []
        self._raise_on = raise_on

    def get_gex(self, ticker):
        if "gex" in self._raise_on:
            raise UWError("gex failed")
        return self._gex

    def get_iv_rank(self, ticker):
        if "iv" in self._raise_on:
            raise UWError("iv failed")
        return self._iv

    def get_flow_alerts(self, ticker, min_premium=0, limit=30):
        if "alerts" in self._raise_on:
            raise UWError("alerts failed")
        return self._alerts


def _alert(type_, premium, sweep=False, block=False, spread=False):
    return {"type": type_, "premium": premium, "sweep": sweep, "block": block, "spread": spread}


def test_analyze_one_bullish_flow_scores_and_direction():
    alerts = [
        _alert("CALL", 300_000, sweep=True),
        _alert("CALL", 400_000, sweep=True),
    ]
    client = FakeClient(iv={"iv_rank": 70.0}, alerts=alerts)
    result = _analyze_one(client, "AAPL", min_premium=250_000)

    assert result["ticker"] == "AAPL"
    assert result["flowDir"] == "bull"
    assert result["callPremium"] == 700_000
    assert result["putPremium"] == 0
    assert result["sweepCount"] == 2
    assert result["qualifyingCount"] == 2
    # score: >=2 qualifying (1) + iv_rank>60 (1) + single-leg available (1) + flow_dir != neutral (1) = 4
    assert result["score"] == 4
    assert result["ivRank"] == 70.0
    assert result["gexRegime"] == "Pinning"


def test_analyze_one_filters_out_non_sweep_non_block_alerts():
    alerts = [_alert("CALL", 1_000_000, sweep=False, block=False)]
    client = FakeClient(alerts=alerts)
    result = _analyze_one(client, "TSLA", min_premium=250_000)
    assert result["qualifyingCount"] == 0
    assert result["flowDir"] == "neutral"
    assert result["score"] == 0


def test_analyze_one_spread_only_flow_does_not_count_as_single_leg():
    alerts = [_alert("PUT", 500_000, block=True, spread=True)]
    client = FakeClient(iv={"iv_rank": 80.0}, alerts=alerts)
    result = _analyze_one(client, "NVDA", min_premium=250_000)
    assert result["qualifyingCount"] == 1
    # 1 qualifying but <2 (0) + iv_rank>60 (1) + no single-leg available (0) + bear flow (1) = 2
    assert result["score"] == 2
    assert result["flowDir"] == "bear"


def test_analyze_one_gracefully_degrades_on_upstream_errors():
    client = FakeClient(raise_on=("gex", "iv", "alerts"))
    result = _analyze_one(client, "META", min_premium=250_000)
    assert result["ivRank"] is None
    assert result["gexRegime"] is None
    assert result["flowDir"] == "neutral"
    assert result["score"] == 0


def test_scan_watchlist_sorts_highest_score_first(monkeypatch):
    # _scan_blocking constructs a real UWClient (cheap -- no network call in
    # __init__, just reads UW_API_KEY) but fans out per-ticker work through
    # _analyze_one, which we fake here to avoid real HTTP calls and to
    # return scores out of order, proving _scan_blocking's sort runs.
    fake_scores = {"LOW": 0, "HIGH": 3, "MID": 1}

    def fake_analyze_one(client, ticker, min_premium):
        return {"ticker": ticker, "score": fake_scores[ticker]}

    monkeypatch.setattr(unusual_whales_service, "_analyze_one", fake_analyze_one)
    results = asyncio.run(unusual_whales_service.scan_watchlist(["LOW", "HIGH", "MID"]))
    assert [r["ticker"] for r in results] == ["HIGH", "MID", "LOW"]
