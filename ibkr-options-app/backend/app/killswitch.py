from datetime import datetime, timezone


class KillSwitch:
    """In-memory trading kill switch. Engaged blocks new order submission
    everywhere it's checked (router level and again at the actual IB
    place_order call site). Resets to disengaged on process restart."""

    def __init__(self):
        self.engaged = False
        self.engaged_at: datetime | None = None
        self.reason: str | None = None

    def engage(self, reason: str = "manual"):
        self.engaged = True
        self.engaged_at = datetime.now(timezone.utc)
        self.reason = reason

    def disengage(self):
        self.engaged = False
        self.engaged_at = None
        self.reason = None

    def as_dict(self) -> dict:
        return {
            "engaged": self.engaged,
            "engagedAt": self.engaged_at.isoformat() if self.engaged_at else None,
            "reason": self.reason,
        }


kill_switch = KillSwitch()
