from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chaka import auth, database, frames, interfaces, models, schemas, types

logger = logging.getLogger(__name__)
router = APIRouter(tags=['channels'])


async def _push_channels_updated(manager, db: AsyncSession) -> None:
    enabled = (
        (
            await db.execute(
                select(models.VoiceChannel)
                .where(models.VoiceChannel.is_enabled.is_(True))
                .order_by(models.VoiceChannel.number)
            )
        )
        .scalars()
        .all()
    )
    frame = frames.channels_updated(channels=[{'id': ch.id, 'number': ch.number, 'name': ch.name} for ch in enabled])
    await manager.broadcast_to_voice_clients(frame)


def _build_response(
    channel: models.VoiceChannel, stats: Dict[int, types.VoiceChannelStats]
) -> schemas.VoiceChannelResponse:
    ch_stats = stats.get(channel.id)
    return schemas.VoiceChannelResponse(
        id=channel.id,
        number=channel.number,
        name=channel.name,
        is_enabled=channel.is_enabled,
        created_at=channel.created_at,
        client_count=ch_stats.client_count if ch_stats else 0,
        clients=[schemas.VoiceChannelClientInfo(**asdict(m)) for m in (ch_stats.clients if ch_stats else [])],
    )


@router.get('/channels', response_model=List[schemas.VoiceChannelResponse])
async def list_channels(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    channels = (await db.execute(select(models.VoiceChannel).order_by(models.VoiceChannel.number))).scalars().all()
    stats = await request.app.state.manager.get_voice_channel_stats()
    return [_build_response(ch, stats) for ch in channels]


@router.post('/channels', response_model=schemas.VoiceChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: schemas.VoiceChannelCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    existing = (
        await db.execute(select(models.VoiceChannel).where(models.VoiceChannel.number == body.number))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Channel number already exists')
    channel = models.VoiceChannel(number=body.number, name=body.name, is_enabled=True, created_at=datetime.now(UTC))
    db.add(channel)
    await db.commit()
    logger.info('Channel created: number=%d name=%s', channel.number, channel.name)
    await _push_channels_updated(request.app.state.manager, db)
    return _build_response(channel, {})


@router.patch('/channels/{channel_id}', response_model=schemas.VoiceChannelResponse)
async def update_channel(
    channel_id: int,
    body: schemas.VoiceChannelUpdate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    manager: interfaces.IConnectionManager = request.app.state.manager
    channel = (
        await db.execute(select(models.VoiceChannel).where(models.VoiceChannel.id == channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Channel not found')
    if body.name is not None:
        channel.name = body.name
    if body.is_enabled is not None:
        channel.is_enabled = body.is_enabled
    await db.commit()
    if body.is_enabled is False:
        await manager.eject_all_from_voice_channel(channel.id)
    await _push_channels_updated(manager, db)
    stats = await manager.get_voice_channel_stats()
    return _build_response(channel, stats)


@router.delete('/channels/{channel_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: int,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    manager: interfaces.IConnectionManager = request.app.state.manager
    channel = (
        await db.execute(select(models.VoiceChannel).where(models.VoiceChannel.id == channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Channel not found')
    stats = await manager.get_voice_channel_stats()
    ch_stats = stats.get(channel_id)
    if ch_stats is not None and ch_stats.client_count > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Channel has connected clients')
    await db.delete(channel)
    await db.commit()
    logger.info('Channel deleted: id=%d number=%d', channel.id, channel.number)
    await _push_channels_updated(manager, db)
