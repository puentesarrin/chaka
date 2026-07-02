from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chaka import auth, database, models

router = APIRouter(tags=['admin'])


@router.get('/', response_class=HTMLResponse)
async def admin_index(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    _: str = Depends(auth.require_admin),
):
    result = await db.execute(select(models.Token).order_by(models.Token.created_at.desc()))
    tokens = result.scalars().all()
    return request.app.state.templates.TemplateResponse('index.html', {'request': request, 'tokens': tokens})
