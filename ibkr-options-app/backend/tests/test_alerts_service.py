import asyncio
from types import SimpleNamespace

from ib_insync import IB, Option

from app.config import Settings
from app.models.alerts import AlertRule
from app.services.alerts_service import AlertsService, _clean


class FakeGreeks:
    def __init__(self, delta=None, impliedVol=None):
        self.delta = delta
        self.impliedVol = impliedVol


class FakeTicker:
    def __init__(self, contract, last=None, modelGreeks=None):
        self.contract = contract
        self.last = last
        self.modelGreeks = modelGreeks

    def marketPrice(self):
        return self.last if self.last is not None else float("nan")


def make_service():
    ib_service = SimpleNamespace(ib=IB(), settings=Settings(telegram_token="", telegram_chat_id=""))
    return AlertsService(ib_service)


def make_rule(**overrides):
    defaults = dict(id="r1", symbol="AAPL", secType="OPT", condition="price_above", threshold=5.0, createdAt="now")
    defaults.update(overrides)
    return AlertRule(**defaults)


def run_evaluate(svc, rule, ticker):
    async def _body():
        svc._evaluate(rule, ticker)
        await asyncio.sleep(0)  # let the broadcast task scheduled inside _evaluate run

    asyncio.run(_body())


def test_clean_handles_nan_and_none():
    assert _clean(None) is None
    assert _clean(float("nan")) is None
    assert _clean(5.0) == 5.0


def test_price_above_triggers():
    svc = make_service()
    contract = Option("AAPL", "20260718", 200, "C", "SMART", currency="USD")
    contract.conId = 111
    rule = make_rule(id="r1", condition="price_above", threshold=5.0)
    svc.rules["r1"] = rule
    svc._conid_by_rule["r1"] = 111
    svc._watchers_by_conid[111] = {"r1"}

    run_evaluate(svc, rule, FakeTicker(contract, last=6.5))

    assert rule.triggered is True
    assert rule.active is False
    assert rule.lastValue == 6.5


def test_price_below_does_not_trigger_when_above_threshold():
    svc = make_service()
    contract = Option("AAPL", "20260718", 200, "C", "SMART", currency="USD")
    contract.conId = 112
    rule = make_rule(id="r2", condition="price_below", threshold=5.0)

    run_evaluate(svc, rule, FakeTicker(contract, last=6.5))

    assert rule.triggered is False
    assert rule.active is True


def test_price_below_ignores_ib_no_data_sentinel():
    # IB returns marketPrice() == -1 when there's no valid last trade or
    # bid/ask (account lacks a data entitlement for the symbol). Unfiltered,
    # -1 would spuriously satisfy almost any price_below threshold.
    svc = make_service()
    contract = Option("AAPL", "20260718", 200, "C", "SMART", currency="USD")
    contract.conId = 116
    rule = make_rule(id="r7", condition="price_below", threshold=300.0)

    run_evaluate(svc, rule, FakeTicker(contract, last=-1.0))

    assert rule.triggered is False


def test_iv_above_uses_model_greeks():
    svc = make_service()
    contract = Option("AAPL", "20260718", 200, "C", "SMART", currency="USD")
    contract.conId = 113
    rule = make_rule(id="r3", condition="iv_above", threshold=30.0)
    svc.rules["r3"] = rule
    svc._conid_by_rule["r3"] = 113
    svc._watchers_by_conid[113] = {"r3"}

    run_evaluate(svc, rule, FakeTicker(contract, modelGreeks=FakeGreeks(impliedVol=0.35)))

    assert rule.triggered is True
    assert rule.lastValue == 35.0


def test_delta_below_uses_model_greeks():
    svc = make_service()
    contract = Option("AAPL", "20260718", 200, "P", "SMART", currency="USD")
    contract.conId = 114
    rule = make_rule(id="r4", condition="delta_below", threshold=-0.3)
    svc.rules["r4"] = rule
    svc._conid_by_rule["r4"] = 114
    svc._watchers_by_conid[114] = {"r4"}

    run_evaluate(svc, rule, FakeTicker(contract, modelGreeks=FakeGreeks(delta=-0.5)))

    assert rule.triggered is True
    assert rule.lastValue == -0.5


def test_missing_greeks_does_not_trigger_or_crash():
    svc = make_service()
    contract = Option("AAPL", "20260718", 200, "C", "SMART", currency="USD")
    contract.conId = 115
    rule = make_rule(id="r5", condition="iv_above", threshold=30.0)

    run_evaluate(svc, rule, FakeTicker(contract, modelGreeks=None))

    assert rule.triggered is False


def test_delete_removes_rule():
    svc = make_service()
    rule = make_rule(id="r6")
    svc.rules["r6"] = rule
    assert svc.delete("r6") is True
    assert "r6" not in svc.rules
    assert svc.delete("r6") is False
