"""In-memory, short-lived store for order previews. A preview is generated
by POST /api/orders/preview (with contracts already qualified and current
bid/ask fetched), then consumed exactly once by POST /api/orders/submit --
this is what makes the confirmation modal trustworthy: the frontend only
ever renders what the backend already validated, and resubmitting requires
a fresh preview (no stale price, no accidental double-submit)."""

import time
import uuid

_TTL_SECONDS = 120


class PreviewStore:
    def __init__(self):
        self._store: dict[str, tuple[float, dict]] = {}

    def put(self, spec: dict) -> str:
        self._sweep()
        preview_id = str(uuid.uuid4())
        self._store[preview_id] = (time.time() + _TTL_SECONDS, spec)
        return preview_id

    def pop(self, preview_id: str) -> dict | None:
        self._sweep()
        entry = self._store.pop(preview_id, None)
        return entry[1] if entry else None

    def peek(self, preview_id: str) -> dict | None:
        self._sweep()
        entry = self._store.get(preview_id)
        return entry[1] if entry else None

    def _sweep(self):
        now = time.time()
        expired = [k for k, (exp, _) in self._store.items() if exp < now]
        for k in expired:
            self._store.pop(k, None)


preview_store = PreviewStore()
TTL_SECONDS = _TTL_SECONDS
