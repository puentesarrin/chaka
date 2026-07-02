from __future__ import annotations

from datetime import UTC, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from chaka import database, models

router = APIRouter(tags=['ack'])
_bearer = HTTPBearer()

_CORS_HEADERS = {
    'Access-Control-Allow-Methods': 'POST',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}


def _cors_headers(origin: str) -> dict:
    if origin.startswith('chrome-extension://'):
        return {'Access-Control-Allow-Origin': origin, **_CORS_HEADERS}
    return {}


@router.options('/ack')
async def ack_preflight(request: Request):
    origin = request.headers.get('origin', '')
    return Response(status_code=200, headers=_cors_headers(origin))


class AckRequest(BaseModel):
    msg_ids: List[str]


@router.post('/ack', status_code=status.HTTP_200_OK)
async def ack_messages(
    body: AckRequest,
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(database.get_db),
):
    origin = request.headers.get('origin', '')
    for k, v in _cors_headers(origin).items():
        response.headers[k] = v
    result = await db.execute(
        select(models.Token).where(models.Token.token == credentials.credentials, models.Token.is_active.is_(True))
    )
    db_token = result.scalar_one_or_none()
    if db_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token')
    if not db_token.can_receive:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Token does not have receive permission')

    if not body.msg_ids:
        return {'acked': 0}

    now = datetime.now(UTC)
    notification_ids_q = select(models.NotificationLog.id).where(models.NotificationLog.msg_id.in_(body.msg_ids))
    result = await db.execute(
        update(models.NotificationDelivery)
        .where(
            models.NotificationDelivery.notification_id.in_(notification_ids_q),
            models.NotificationDelivery.token_id == db_token.id,
            models.NotificationDelivery.acked_at.is_(None),
        )
        .values(acked_at=now)
    )
    await db.commit()
    return {'acked': result.rowcount}
