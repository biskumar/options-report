from app.services.contract_builder import build_option, build_stock


def test_build_stock():
    s = build_stock("AAPL")
    assert s.symbol == "AAPL"
    assert s.exchange == "SMART"
    assert s.currency == "USD"


def test_build_option():
    o = build_option("AAPL", "20260718", 200.0, "C")
    assert o.symbol == "AAPL"
    assert o.lastTradeDateOrContractMonth == "20260718"
    assert o.strike == 200.0
    assert o.right == "C"
    assert o.exchange == "SMART"
    assert o.currency == "USD"
