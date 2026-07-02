from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from chaka import frames, interfaces, repositories

logger = logging.getLogger(__name__)
router = APIRouter(tags=['notify'])
_bearer = HTTPBearer()


@router.post('/notify', status_code=status.HTTP_202_ACCEPTED)
async def notify(
    payload: Dict[str, Any],
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    x_source: str = Header(default='device'),
):
    manager: interfaces.IConnectionManager = request.app.state.manager
    tokens: repositories.TokenRepository = request.app.state.token_repo
    notifications: repositories.NotificationRepository = request.app.state.notification_repo

    db_token = await tokens.get_active(credentials.credentials)
    if db_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token')
    if not db_token.can_send:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Token does not have send permission')

    ip = request.client.host if request.client else 'unknown'
    msg_id = str(uuid.uuid4())
    log_id = await notifications.create(
        token_id=db_token.id,
        msg_id=msg_id,
        source=x_source,
        received_at=datetime.now(UTC),
        client_ip=ip,
        payload=payload,
    )

    delivered = await manager.broadcast(frames.single(msg_id=msg_id, message=payload))
    logger.info(
        'HTTP notify: token=%s source=%s scope=%s delivered=%d',
        db_token.name,
        x_source,
        payload.get('scope', ''),
        len(delivered),
    )
    if delivered:
        now = datetime.now(UTC)
        await tokens.mark_delivered([d.token_id for d in delivered], now)
        await notifications.record_deliveries(log_id, delivered, now)

    return {'sent': len(delivered), 'msg_id': msg_id}
