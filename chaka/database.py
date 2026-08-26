from __future__ import annotations

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# An async session factory: call it to get an AsyncSession (async context manager).
SessionMaker = async_sessionmaker[AsyncSession]


def make_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True, pool_recycle=3600)
    if engine.dialect.name == 'sqlite':
        _apply_sqlite_pragmas(engine)
    return engine


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """SQLite ships with foreign keys disabled, so the schema's ``ondelete``
    rules would silently not fire; WAL keeps readers from blocking the writer."""

    @event.listens_for(engine.sync_engine, 'connect')
    def _set_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.close()


def make_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db(request: Request):
    """FastAPI dependency: yield a session from the app-owned sessionmaker."""
    async with request.app.state.sessionmaker() as session:
        yield session
