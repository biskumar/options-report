from app.services.recommendation_store import RecommendationStore


def _rec(**overrides):
    base = {
        "symbol": "ORCL",
        "expiry": "20260717",
        "strike": 145.0,
        "right": "C",
        "side": "buy",
        "quantity": 1,
        "entryLimitPrice": 2.0,
        "targetLimitPrice": 3.5,
        "stopPrice": 1.0,
        "source": "options-analyzer",
        "note": "breakout setup",
    }
    base.update(overrides)
    return base


def test_add_assigns_id_and_received_at():
    store = RecommendationStore()
    stored = store.add(_rec())
    assert stored["id"]
    assert stored["receivedAt"]
    assert stored["symbol"] == "ORCL"


def test_list_pending_returns_all_unconsumed_in_insertion_order():
    store = RecommendationStore()
    a = store.add(_rec(symbol="ORCL"))
    b = store.add(_rec(symbol="AAPL"))
    pending = store.list_pending()
    assert [p["id"] for p in pending] == [a["id"], b["id"]]


def test_consume_removes_and_returns_true():
    store = RecommendationStore()
    stored = store.add(_rec())
    assert store.consume(stored["id"]) is True
    assert store.list_pending() == []


def test_consume_unknown_id_returns_false():
    store = RecommendationStore()
    assert store.consume("does-not-exist") is False


def test_consumed_recommendation_does_not_reappear():
    store = RecommendationStore()
    a = store.add(_rec(symbol="ORCL"))
    b = store.add(_rec(symbol="AAPL"))
    store.consume(a["id"])
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["id"] == b["id"]
