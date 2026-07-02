from __future__ import annotations

import math
import secrets
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chaka import auth, database, models, schemas

router = APIRouter(tags=['tokens'])


def _event(token: models.Token, event: str, detail: Optional[dict] = None) -> models.TokenEvent:
    return models.TokenEvent(
        token_id=token.id,
        token_name=token.name,
        event=event,
        occurred_at=datetime.now(UTC),
        detail=detail,
    )


@router.post('/tokens', response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: schemas.TokenCreate,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    token_value = secrets.token_urlsafe(32)
    token = models.Token(name=body.name, token=token_value, created_at=datetime.now(UTC))
    db.add(token)
    await db.flush()
    db.add(_event(token, 'created'))
    await db.commit()
    await db.refresh(token)
    return token


@router.patch('/tokens/{token_id}', response_model=schemas.TokenResponse)
async def rename_token(
    token_id: int,
    body: schemas.TokenRename,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail='Token not found')
    old_name = token.name
    token.name = body.name
    db.add(_event(token, 'renamed', {'from': old_name, 'to': body.name}))
    await db.commit()
    await db.refresh(token)
    return token


@router.delete('/tokens/{token_id}', status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: int,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail='Token not found')
    if not token.is_active:
        raise HTTPException(status_code=409, detail='Token is already revoked')
    token.is_active = False
    token.revoked_at = datetime.now(UTC)
    db.add(_event(token, 'revoked'))
    await db.commit()
    await request.app.state.manager.disconnect_by_token_id(token.id)


@router.patch('/tokens/{token_id}/permissions', response_model=schemas.TokenResponse)
async def set_token_permissions(
    token_id: int,
    body: schemas.TokenPermissions,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail='Token not found')
    had_voice = token.can_talk or token.can_hear
    can_talk = body.can_talk
    can_hear = body.can_hear or body.can_talk  # can_talk implies can_hear
    token.can_send = body.can_send
    token.can_receive = body.can_receive
    token.can_talk = can_talk
    token.can_hear = can_hear
    db.add(
        _event(
            token,
            'permissions_changed',
            {
                'can_send': body.can_send,
                'can_receive': body.can_receive,
                'can_talk': can_talk,
                'can_hear': can_hear,
            },
        )
    )
    await db.commit()
    await db.refresh(token)
    if had_voice and not (can_talk or can_hear):
        await request.app.state.manager.revoke_voice_permission_by_token_id(token.id)
    return token


@router.post('/tokens/{token_id}/restore', response_model=schemas.TokenResponse)
async def restore_token(
    token_id: int,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail='Token not found')
    if token.is_active:
        raise HTTPException(status_code=409, detail='Token is not revoked')
    token.is_active = True
    token.revoked_at = None
    db.add(_event(token, 'restored'))
    await db.commit()
    await db.refresh(token)
    return token


@router.post('/tokens/{token_id}/regenerate', response_model=schemas.TokenResponse)
async def regenerate_token(
    token_id: int,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail='Token not found')
    token.token = secrets.token_urlsafe(32)
    db.add(_event(token, 'regenerated'))
    await db.commit()
    await db.refresh(token)
    await request.app.state.manager.disconnect_by_token_id(token.id)
    return token


@router.get('/tokens/{token_id}/events', response_model=schemas.PaginatedEvents)
async def get_token_events(
    token_id: int,
    page: int = 1,
    per_page: int = 20,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail='Token not found')

    total = (
        await db.execute(
            select(func.count()).select_from(models.TokenEvent).where(models.TokenEvent.token_id == token_id)
        )
    ).scalar()

    items = (
        (
            await db.execute(
                select(models.TokenEvent)
                .where(models.TokenEvent.token_id == token_id)
                .order_by(models.TokenEvent.occurred_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )

    return schemas.PaginatedEvents(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, math.ceil(total / per_page)),
    )


@router.get('/tokens/{token_id}/deliveries', response_model=schemas.PaginatedTokenDeliveries)
async def get_token_deliveries(
    token_id: int,
    page: int = 1,
    per_page: int = 20,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).where(models.Token.id == token_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail='Token not found')

    total = (
        await db.execute(
            select(func.count())
            .select_from(models.NotificationDelivery)
            .where(models.NotificationDelivery.token_id == token_id)
        )
    ).scalar()

    rows = (
        await db.execute(
            select(models.NotificationDelivery, models.NotificationLog)
            .join(models.NotificationLog, models.NotificationDelivery.notification_id == models.NotificationLog.id)
            .where(models.NotificationDelivery.token_id == token_id)
            .order_by(models.NotificationDelivery.sent_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    items = [
        schemas.TokenDeliveryResponse(
            notification_id=d.notification_id,
            msg_id=log.msg_id,
            sent_at=d.sent_at,
            acked_at=d.acked_at,
            source=log.source,
            received_at=log.received_at,
            payload=log.payload,
        )
        for d, log in rows
    ]

    return schemas.PaginatedTokenDeliveries(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, math.ceil(total / per_page)),
    )
