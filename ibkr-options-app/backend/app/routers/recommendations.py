from fastapi import APIRouter, HTTPException

from ..models.contracts import (
    BracketRecommendation,
    BracketRecommendationRequest,
    SingleLegRecommendation,
    SingleLegRecommendationRequest,
)
from ..services import bracket_service, order_builder
from ..services.recommendation_store import bracket_recommendation_store, single_leg_recommendation_store

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.post("", response_model=BracketRecommendation)
async def create_bracket_recommendation(body: BracketRecommendationRequest):
    """Inbox endpoint for an external options-analyzer process/session to
    push a bracket trade idea into this app -- e.g. `curl -X POST
    http://localhost:8010/api/recommendations -d '{...}'` from another
    Claude session. Deliberately does NOT touch IB, the preview store, or
    the kill switch: it only queues a suggestion for a human to review on
    the Bracket Order page, which auto-fills the form but still requires
    the normal manual Preview -> Confirm & Submit before anything reaches
    the account. Still validates the price ordering up front so a
    malformed recommendation fails loudly here instead of silently later."""
    try:
        bracket_service.validate_bracket_prices(body.side, body.entryLimitPrice, body.targetLimitPrice, body.stopPrice)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    stored = bracket_recommendation_store.add(body.model_dump())
    return BracketRecommendation(**stored)


@router.get("", response_model=list[BracketRecommendation])
async def list_bracket_recommendations():
    """Polled by the Bracket Order page. Returns every recommendation not
    yet consumed, oldest first."""
    return [BracketRecommendation(**r) for r in bracket_recommendation_store.list_pending()]


@router.post("/{rec_id}/consume")
async def consume_bracket_recommendation(rec_id: str):
    """Called once the frontend has loaded a recommendation into the form
    (or the user dismisses it) so it doesn't keep reappearing."""
    if not bracket_recommendation_store.consume(rec_id):
        raise HTTPException(status_code=404, detail="recommendation not found or already consumed")
    return {"id": rec_id, "status": "consumed"}


@router.post("/single-leg", response_model=SingleLegRecommendation)
async def create_single_leg_recommendation(body: SingleLegRecommendationRequest):
    """Same idea as the bracket inbox above, for a plain single buy/sell
    call or put that maps onto the Order Ticket page instead. Validates
    via order_builder.build_single_leg_order -- the same construction the
    real submit path uses -- so a recommendation missing a required price
    for its orderType (e.g. a "limit" with no limitPrice) fails loudly
    here rather than silently sitting unusable in the form."""
    try:
        order_builder.build_single_leg_order(body.side, body.quantity, body.orderType, body.limitPrice, body.stopPrice)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    stored = single_leg_recommendation_store.add(body.model_dump())
    return SingleLegRecommendation(**stored)


@router.get("/single-leg", response_model=list[SingleLegRecommendation])
async def list_single_leg_recommendations():
    """Polled by the Order Ticket page."""
    return [SingleLegRecommendation(**r) for r in single_leg_recommendation_store.list_pending()]


@router.post("/single-leg/{rec_id}/consume")
async def consume_single_leg_recommendation(rec_id: str):
    if not single_leg_recommendation_store.consume(rec_id):
        raise HTTPException(status_code=404, detail="recommendation not found or already consumed")
    return {"id": rec_id, "status": "consumed"}
