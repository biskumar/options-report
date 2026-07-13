from fastapi import APIRouter, HTTPException, Request

from ..deps import require_connected
from ..models.alerts import AlertCreateRequest, AlertRule

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRule])
async def list_alerts(request: Request):
    return request.app.state.alerts_service.list()


@router.post("", response_model=AlertRule)
async def create_alert(request: Request, body: AlertCreateRequest):
    ib_service = request.app.state.ib_service
    require_connected(ib_service)
    try:
        return await request.app.state.alerts_service.create(body)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/{alert_id}")
async def delete_alert(request: Request, alert_id: str):
    if not request.app.state.alerts_service.delete(alert_id):
        raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
    return {"id": alert_id, "deleted": True}
