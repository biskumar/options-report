"""Simple alert rules evaluated reactively against live ticker updates
(rather than a separate polling timer -- every incoming tick for a watched
contract is checked against the rules that reference it, which is simpler
and more responsive than re-polling on an interval). One IB market data
subscription is shared across all rules watching the same contract."""

import asyncio
import math
import uuid
from datetime import datetime, timezone

from ..broadcaster import broadcaster
from ..models.alerts import AlertCreateRequest, AlertRule
from .contract_builder import build_option, build_stock
from .telegram_notifier import send_telegram


def _clean(value):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _clean_price(value):
    """IB uses -1 as a sentinel for "price not available" on marketPrice()
    (distinct from NaN) when there's no valid last trade or bid/ask -- an
    unfiltered -1 here would spuriously satisfy a price_below alert (or
    silently break price_above), firing on garbage data instead of a real
    price. A real price is never negative."""
    value = _clean(value)
    return None if value is not None and value < 0 else value


class AlertsService:
    def __init__(self, ib_service):
        self.ib_service = ib_service
        self.rules: dict[str, AlertRule] = {}
        self._conid_by_rule: dict[str, int] = {}
        self._watchers_by_conid: dict[int, set[str]] = {}
        self._contract_by_conid: dict[int, object] = {}
        ib_service.ib.pendingTickersEvent += self._on_tickers

    async def create(self, req: AlertCreateRequest) -> AlertRule:
        ib = self.ib_service.ib
        if req.secType == "OPT":
            if not (req.expiry and req.strike and req.right):
                raise ValueError("expiry, strike, and right are required for an option alert")
            contract = build_option(req.symbol.upper(), req.expiry, req.strike, req.right)
        else:
            contract = build_stock(req.symbol.upper())

        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            raise ValueError(f"could not qualify contract for {req.symbol}")
        contract = qualified[0]

        rule = AlertRule(
            id=str(uuid.uuid4()),
            createdAt=datetime.now(timezone.utc).isoformat(),
            **req.model_dump(),
        )
        self.rules[rule.id] = rule
        self._conid_by_rule[rule.id] = contract.conId
        self._contract_by_conid[contract.conId] = contract
        watchers = self._watchers_by_conid.setdefault(contract.conId, set())
        if not watchers:
            generic = "106" if req.secType == "OPT" else ""
            ib.reqMktData(contract, genericTickList=generic, snapshot=False)
        watchers.add(rule.id)
        return rule

    def list(self) -> list[AlertRule]:
        return list(self.rules.values())

    def delete(self, rule_id: str) -> bool:
        if rule_id not in self.rules:
            return False
        self.rules.pop(rule_id)
        self._unwatch(rule_id)
        return True

    def _unwatch(self, rule_id: str):
        con_id = self._conid_by_rule.pop(rule_id, None)
        if con_id is None:
            return
        watchers = self._watchers_by_conid.get(con_id)
        if not watchers:
            return
        watchers.discard(rule_id)
        if not watchers:
            contract = self._contract_by_conid.pop(con_id, None)
            if contract is not None:
                self.ib_service.ib.cancelMktData(contract)
            self._watchers_by_conid.pop(con_id, None)

    def _on_tickers(self, tickers):
        for ticker in tickers:
            watchers = self._watchers_by_conid.get(ticker.contract.conId)
            if not watchers:
                continue
            for rule_id in list(watchers):
                rule = self.rules.get(rule_id)
                if rule is not None and rule.active:
                    self._evaluate(rule, ticker)

    def _evaluate(self, rule: AlertRule, ticker):
        greeks = ticker.modelGreeks
        value_by_condition = {
            "price_above": _clean_price(ticker.marketPrice()),
            "price_below": _clean_price(ticker.marketPrice()),
            "iv_above": _clean(greeks.impliedVol * 100) if greeks and greeks.impliedVol is not None else None,
            "iv_below": _clean(greeks.impliedVol * 100) if greeks and greeks.impliedVol is not None else None,
            "delta_above": _clean(greeks.delta) if greeks and greeks.delta is not None else None,
            "delta_below": _clean(greeks.delta) if greeks and greeks.delta is not None else None,
        }
        value = value_by_condition.get(rule.condition)
        if value is None:
            return

        is_above = rule.condition.endswith("_above")
        fired = value > rule.threshold if is_above else value < rule.threshold
        if not fired:
            return

        rule.active = False
        rule.triggered = True
        rule.triggeredAt = datetime.now(timezone.utc).isoformat()
        rule.lastValue = value
        self._unwatch(rule.id)

        asyncio.create_task(broadcaster.publish("alert_triggered", rule.model_dump()))

        settings = self.ib_service.settings
        if settings.telegram_token and settings.telegram_chat_id:
            message = f"Alert: {rule.symbol} {rule.condition} {rule.threshold} -- now {value:.2f}"
            if rule.note:
                message += f" ({rule.note})"
            send_telegram(settings.telegram_token, settings.telegram_chat_id, message)
