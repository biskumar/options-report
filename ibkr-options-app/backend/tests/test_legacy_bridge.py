import asyncio

from app.services import legacy_bridge


def test_concurrent_get_watchlist_only_scans_once(monkeypatch):
    # Reproduces the incident: multiple requests arriving while the cache
    # is cold used to each kick off their own multi-minute
    # run_morning_scan(), starving the event loop. Concurrent callers must
    # share a single in-flight scan.
    monkeypatch.setitem(legacy_bridge._watchlist_cache, "results", None)
    monkeypatch.setitem(legacy_bridge._watchlist_cache, "fetchedAt", 0)

    call_count = 0

    def fake_scan():
        nonlocal call_count
        call_count += 1
        return [{"Symbol": "TEST"}]

    monkeypatch.setattr(legacy_bridge, "_run_morning_scan_blocking", fake_scan)

    async def run():
        return await asyncio.gather(*[legacy_bridge.get_watchlist() for _ in range(5)])

    results = asyncio.run(run())

    assert call_count == 1
    for r in results:
        assert r["results"] == [{"Symbol": "TEST"}]


def test_force_refresh_after_cache_warm_still_scans_again(monkeypatch):
    monkeypatch.setitem(legacy_bridge._watchlist_cache, "results", [{"Symbol": "OLD"}])
    monkeypatch.setitem(legacy_bridge._watchlist_cache, "fetchedAt", legacy_bridge.time.time())

    call_count = 0

    def fake_scan():
        nonlocal call_count
        call_count += 1
        return [{"Symbol": "NEW"}]

    monkeypatch.setattr(legacy_bridge, "_run_morning_scan_blocking", fake_scan)

    result = asyncio.run(legacy_bridge.get_watchlist(force_refresh=True))

    assert call_count == 1
    assert result["results"] == [{"Symbol": "NEW"}]
