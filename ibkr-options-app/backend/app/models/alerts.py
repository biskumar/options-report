from typing import Literal

from pydantic import BaseModel

AlertCondition = Literal["price_above", "price_below", "iv_above", "iv_below", "delta_above", "delta_below"]
SecType = Literal["STK", "OPT"]
Right = Literal["C", "P"]


class AlertCreateRequest(BaseModel):
    symbol: str
    secType: SecType = "STK"
    expiry: str | None = None
    strike: float | None = None
    right: Right | None = None
    condition: AlertCondition
    threshold: float
    note: str | None = None


class AlertRule(AlertCreateRequest):
    id: str
    active: bool = True
    triggered: bool = False
    triggeredAt: str | None = None
    lastValue: float | None = None
    createdAt: str
