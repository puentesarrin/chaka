from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# An async session factory: call it to get an AsyncSession (async context manager).
SessionMaker = async_sessionmaker[AsyncSession]


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, echo=False, pool_pre_ping=True, pool_recycle=3600)


def make_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db(request: Request):
    """FastAPI dependency: yield a session from the app-owned sessionmaker."""
    async with request.app.state.sessionmaker() as session:
        yield session
