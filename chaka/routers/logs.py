import math
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from chaka import auth, database, models, schemas

router = APIRouter(tags=['logs'])


@router.get('/logs', response_model=schemas.PaginatedLogs)
async def list_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    token_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    count_q = select(func.count(models.NotificationLog.id))
    if token_id is not None:
        count_q = count_q.where(models.NotificationLog.token_id == token_id)
    total = (await db.execute(count_q)).scalar_one()

    offset = (page - 1) * per_page
    rows_q = (
        select(models.NotificationLog, models.Token.name.label('token_name'))
        .options(selectinload(models.NotificationLog.deliveries))
        .outerjoin(models.Token, models.NotificationLog.token_id == models.Token.id)
        .order_by(models.NotificationLog.received_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    if token_id is not None:
        rows_q = rows_q.where(models.NotificationLog.token_id == token_id)

    rows = (await db.execute(rows_q)).all()
    items = [
        schemas.LogResponse(
            id=log.id,
            token_id=log.token_id,
            token_name=name,
            msg_id=log.msg_id,
            source=log.source,
            received_at=log.received_at,
            forwarded_at=log.forwarded_at,
            client_ip=log.client_ip,
            payload=log.payload,
            deliveries=log.deliveries,
        )
        for log, name in rows
    ]

    return schemas.PaginatedLogs(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, math.ceil(total / per_page)),
    )


@router.get('/connection-log', response_model=schemas.PaginatedEvents)
async def list_connection_events(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    events_filter = models.TokenEvent.event.in_(['connected', 'disconnected'])

    total = (await db.execute(select(func.count(models.TokenEvent.id)).where(events_filter))).scalar_one()

    items = (
        (
            await db.execute(
                select(models.TokenEvent)
                .where(events_filter)
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


@router.get('/server-log', response_class=PlainTextResponse)
async def server_log(request: Request, _: str = Depends(auth.require_admin)):
    log_file = request.app.state.settings.log_file
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
        return ''.join(lines[-200:])
    except FileNotFoundError:
        return '(log file not found)\n'


@router.get('/heartbeat-log', response_class=PlainTextResponse)
async def heartbeat_log(request: Request, _: str = Depends(auth.require_admin)):
    log_file = request.app.state.settings.heartbeat_log_file
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
        return ''.join(lines[-200:])
    except FileNotFoundError:
        return '(log file not found)\n'
