import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from chaka import auth, frames, interfaces, repositories

router = APIRouter(tags=['send'])


class SendPayload(BaseModel):
    scope: Optional[str] = None
    title: str
    body: Optional[str] = None
    package: Optional[str] = None
    timestamp: Optional[int] = None
    token_ids: Optional[List[int]] = None


@router.post('/send')
async def send_message(
    payload: SendPayload,
    request: Request,
    _: str = Depends(auth.require_admin),
):
    manager: interfaces.IConnectionManager = request.app.state.manager
    notifications: repositories.NotificationRepository = request.app.state.notification_repo

    data: Dict[str, Any] = {'title': payload.title}
    if payload.scope is not None:
        data['scope'] = payload.scope
    if payload.body is not None:
        data['body'] = payload.body
    if payload.package is not None:
        data['package'] = payload.package
    data['timestamp'] = payload.timestamp or int(datetime.now(UTC).timestamp() * 1000)

    msg_id = str(uuid.uuid4())
    log_id = await notifications.create(
        token_id=None, msg_id=msg_id, source='admin', received_at=datetime.now(UTC), client_ip='admin', payload=data
    )

    frame = frames.single(msg_id=msg_id, message=data)
    if payload.token_ids:
        delivered = await manager.send_to_tokens(payload.token_ids, frame)
    else:
        delivered = await manager.broadcast(frame)
    if delivered:
        await notifications.record_deliveries(log_id, delivered, datetime.now(UTC))

    return {'sent': len(delivered), 'msg_id': msg_id}
