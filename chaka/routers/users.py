from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from chaka import auth, clock, database, models, passwords, schemas

logger = logging.getLogger(__name__)
router = APIRouter(tags=['users'])


async def _get_user(db: AsyncSession, user_id: int) -> models.User:
    user = (await db.execute(select(models.User).where(models.User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')
    return user


async def _active_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(models.User).where(models.User.is_active.is_(True)))
    return int(result.scalar() or 0)


async def _assert_not_last_admin(db: AsyncSession, user: models.User, current: models.User, action: str) -> None:
    if user.id == current.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'You cannot {action} your own account')
    if user.is_active and await _active_count(db) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'Cannot {action} the last active user')


async def _assert_available(
    db: AsyncSession, *, username: Optional[str] = None, email: Optional[str] = None, exclude: Optional[int] = None
) -> None:
    """409 if ``username`` or ``email`` already belongs to another user."""
    clauses = []
    if username is not None:
        clauses.append(models.User.username == username)
    if email is not None:
        clauses.append(models.User.email == email)
    if not clauses:
        return
    query = select(models.User).where(or_(*clauses))
    if exclude is not None:
        query = query.where(models.User.id != exclude)
    taken = (await db.execute(query)).scalars().first()
    if taken is None:
        return
    field = 'Username' if username is not None and taken.username == username else 'Email'
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'{field} is already taken')


@router.get('/users', response_model=List[schemas.UserResponse])
async def list_users(
    db: AsyncSession = Depends(database.get_db),
    _: models.User = Depends(auth.require_admin),
):
    result = await db.execute(select(models.User).order_by(models.User.username))
    return list(result.scalars().all())


@router.get('/users/me', response_model=schemas.UserResponse)
async def read_me(current: models.User = Depends(auth.require_admin)):
    return current


@router.post('/users', response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
    _: models.User = Depends(auth.require_admin),
):
    await _assert_available(db, username=body.username, email=body.email)
    user = models.User(
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        password_hash=passwords.hash_password(body.password),
        is_active=body.is_active,
        created_at=clock.utcnow(),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info('User created: username=%s', user.username)
    return user


@router.patch('/users/{user_id}', response_model=schemas.UserResponse)
async def update_user(
    user_id: int,
    body: schemas.UserUpdate,
    db: AsyncSession = Depends(database.get_db),
    current: models.User = Depends(auth.require_admin),
):
    user = await _get_user(db, user_id)
    fields = body.model_dump(exclude_unset=True)

    if 'is_active' in fields and fields['is_active'] is False:
        await _assert_not_last_admin(db, user, current, 'deactivate')
    if 'email' in fields and fields['email'] is not None:
        await _assert_available(db, email=fields['email'], exclude=user.id)

    for field, value in fields.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    logger.info('User updated: username=%s fields=%s', user.username, ','.join(sorted(fields)))
    return user


@router.post('/users/{user_id}/password', status_code=status.HTTP_204_NO_CONTENT)
async def set_password(
    user_id: int,
    body: schemas.UserPassword,
    db: AsyncSession = Depends(database.get_db),
    _: models.User = Depends(auth.require_admin),
):
    user = await _get_user(db, user_id)
    user.password_hash = passwords.hash_password(body.password)
    await db.commit()
    logger.info('User password changed: username=%s', user.username)


@router.delete('/users/{user_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current: models.User = Depends(auth.require_admin),
):
    user = await _get_user(db, user_id)
    await _assert_not_last_admin(db, user, current, 'delete')
    username = user.username
    await db.delete(user)
    await db.commit()
    logger.info('User deleted: username=%s', username)
