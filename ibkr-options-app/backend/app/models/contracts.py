from typing import Literal

from pydantic import BaseModel

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
Right = Literal["C", "P"]


class OrderPreviewRequest(BaseModel):
    symbol: str
    expiry: str  # YYYYMMDD
    strike: float
    right: Right
    side: Side
    quantity: int
    orderType: OrderType
    limitPrice: float | None = None
    stopPrice: float | None = None


class OrderLegPreview(BaseModel):
    symbol: str
    expiry: str
    strike: float
    right: Right
    side: Side
    quantity: int
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None


class OrderPreviewResponse(BaseModel):
    previewId: str
    legs: list[OrderLegPreview]
    orderType: OrderType
    limitPrice: float | None = None
    stopPrice: float | None = None
    estCost: float | None = None
    dryRun: bool
    expiresAt: str


class OrderSubmitRequest(BaseModel):
    previewId: str


class OrderSubmitResponse(BaseModel):
    orderId: int | None = None
    status: str
    dryRun: bool


ComboAction = Literal["BUY", "SELL"]
PresetName = Literal["vertical", "straddle", "strangle", "iron_condor", "butterfly", "calendar_spread"]
PresetSide = Literal["long", "short"]


class ComboLegSpec(BaseModel):
    expiry: str
    strike: float
    right: Right
    action: ComboAction
    ratio: int = 1


class ComboPresetRequest(BaseModel):
    name: PresetName
    expiry: str
    strikes: list[float]
    right: Right | None = None  # required for "vertical"/"butterfly"/"calendar_spread"
    side: PresetSide | None = None  # required for "straddle"/"strangle"/"butterfly"/"calendar_spread"
    expiry2: str | None = None  # required for "calendar_spread" -- the far-dated expiry


class ComboPresetResponse(BaseModel):
    legs: list[ComboLegSpec]


class ComboPreviewRequest(BaseModel):
    symbol: str
    legs: list[ComboLegSpec]
    quantity: int
    orderType: OrderType
    limitPrice: float | None = None


class ComboLegPreview(ComboLegSpec):
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    # Exposed so the frontend can key into the WebSocket's per-conId quote
    # stream (see ib_service._on_tickers) for push-based price updates
    # instead of re-polling this endpoint.
    conId: int | None = None


class ComboPreviewResponse(BaseModel):
    previewId: str
    symbol: str
    legs: list[ComboLegPreview]
    quantity: int
    orderType: OrderType
    limitPrice: float | None = None
    netMid: float | None = None
    estCost: float | None = None
    dryRun: bool
    expiresAt: str


class ComboQuoteRequest(BaseModel):
    symbol: str
    legs: list[ComboLegSpec]


class ComboQuoteResponse(BaseModel):
    legs: list[ComboLegPreview]
    netMid: float | None = None


class BracketOrderRequest(BaseModel):
    symbol: str
    expiry: str  # YYYYMMDD
    strike: float
    right: Right
    side: Side  # entry direction -- "buy" opens long, "sell" opens short
    quantity: int
    entryLimitPrice: float
    targetLimitPrice: float
    stopPrice: float


class BracketLegPreview(BaseModel):
    role: Literal["entry", "target", "stop"]
    action: str
    orderType: str
    price: float


class BracketPreviewResponse(BaseModel):
    previewId: str
    symbol: str
    expiry: str
    strike: float
    right: Right
    quantity: int
    legs: list[BracketLegPreview]
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    estCost: float | None = None
    dryRun: bool
    expiresAt: str


class BracketSubmitRequest(BaseModel):
    previewId: str


class BracketSubmitResponse(BaseModel):
    orderIds: list[int] | None = None
    status: str
    dryRun: bool


class BracketRecommendationRequest(BaseModel):
    """Inbox payload for an external options-analyzer process/session to
    queue a bracket trade idea into this app -- see routers/recommendations.py.
    Deliberately the same shape as BracketOrderRequest so it maps directly
    onto the Bracket Order form; source/note are just provenance, shown to
    the human reviewing it, never used to decide anything automatically."""
    symbol: str
    expiry: str
    strike: float
    right: Right
    side: Side
    quantity: int
    entryLimitPrice: float
    targetLimitPrice: float
    stopPrice: float
    source: str | None = None
    note: str | None = None


class BracketRecommendation(BracketRecommendationRequest):
    id: str
    receivedAt: str


class SingleLegRecommendationRequest(BaseModel):
    """Same idea as BracketRecommendationRequest but for a single buy/sell
    call or put -- maps directly onto the Order Ticket form."""
    symbol: str
    expiry: str
    strike: float
    right: Right
    side: Side
    quantity: int
    orderType: OrderType
    limitPrice: float | None = None
    stopPrice: float | None = None
    source: str | None = None
    note: str | None = None


class SingleLegRecommendation(SingleLegRecommendationRequest):
    id: str
    receivedAt: str


class OrderRow(BaseModel):
    orderId: int
    permId: int
    symbol: str
    action: str
    orderType: str
    totalQuantity: float
    lmtPrice: float | None = None
    status: str
    filled: float
    remaining: float
    avgFillPrice: float | None = None
