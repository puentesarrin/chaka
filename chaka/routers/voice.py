from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chaka import auth, database, models, schemas

logger = logging.getLogger(__name__)
router = APIRouter(tags=['voice'])


@router.get('/voice-log', response_model=schemas.PaginatedVoiceLogs)
async def list_voice_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    total = (await db.execute(select(func.count(models.VoiceLog.id)))).scalar_one()

    items = (
        (
            await db.execute(
                select(models.VoiceLog)
                .order_by(models.VoiceLog.started_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )

    return schemas.PaginatedVoiceLogs(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=max(1, math.ceil(total / per_page)),
    )
