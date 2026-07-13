from pydantic import BaseModel


class ConnectionStatus(BaseModel):
    status: str
    host: str
    port: int
    clientId: int
    lastError: str | None = None


class KillSwitchState(BaseModel):
    engaged: bool
    engagedAt: str | None = None
    reason: str | None = None


class AccountSummary(BaseModel):
    account: str
    netLiquidation: float | None = None
    buyingPower: float | None = None
    totalCashValue: float | None = None
    grossPositionValue: float | None = None


class Position(BaseModel):
    account: str
    conId: int
    symbol: str
    secType: str
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    position: float
    avgCost: float
    marketPrice: float | None = None
    marketValue: float | None = None
    unrealizedPnL: float | None = None


class PnLSnapshot(BaseModel):
    account: str
    dailyPnL: float | None = None
    unrealizedPnL: float | None = None
    realizedPnL: float | None = None


class ChainRow(BaseModel):
    strike: float
    right: str
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    volume: int | None = None
    impliedVolatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


class ChainResponse(BaseModel):
    symbol: str
    expiry: str
    spot: float | None = None
    calls: list[ChainRow]
    puts: list[ChainRow]
