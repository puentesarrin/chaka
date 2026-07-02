from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()

from chaka.models import Base

config = context.config
target_metadata = Base.metadata

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+aiomysql://user:pass@localhost:3306/chaka")


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(DATABASE_URL)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
