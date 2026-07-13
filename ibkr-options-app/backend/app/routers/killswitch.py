from pydantic import BaseModel

from fastapi import APIRouter

from ..broadcaster import broadcaster
from ..killswitch import kill_switch
from ..models.domain import KillSwitchState

router = APIRouter(prefix="/api/killswitch", tags=["killswitch"])


class KillSwitchRequest(BaseModel):
    engaged: bool
    reason: str | None = None


@router.get("", response_model=KillSwitchState)
async def get_state():
    return kill_switch.as_dict()


@router.post("", response_model=KillSwitchState)
async def set_state(body: KillSwitchRequest):
    if body.engaged:
        kill_switch.engage(body.reason or "manual")
    else:
        kill_switch.disengage()
    state = kill_switch.as_dict()
    await broadcaster.publish("killswitch", state)
    return state
