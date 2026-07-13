"""In-memory inboxes for trade recommendations pushed in from an external
process (e.g. a separate options-analyzer session hitting this app's
API). Unlike preview_store, entries here have no TTL -- they sit until a
human loads one into the matching form (which consumes it) or explicitly
dismisses it. This store never touches IB or places anything; it only
holds data for a human to review. Bracket and single-leg recommendations
get their own independent instance below so the two inboxes (and their
poll loops on the Bracket Order / Order Ticket pages) never cross over."""

import uuid
from datetime import datetime, timezone


class RecommendationStore:
    def __init__(self):
        self._items: dict[str, dict] = {}

    def add(self, rec: dict) -> dict:
        rec_id = str(uuid.uuid4())
        stored = {**rec, "id": rec_id, "receivedAt": datetime.now(timezone.utc).isoformat()}
        self._items[rec_id] = stored
        return stored

    def list_pending(self) -> list[dict]:
        return list(self._items.values())

    def consume(self, rec_id: str) -> bool:
        return self._items.pop(rec_id, None) is not None


bracket_recommendation_store = RecommendationStore()
single_leg_recommendation_store = RecommendationStore()
