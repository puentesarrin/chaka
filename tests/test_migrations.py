"""Migrations against a real database: schema, autoincrementing keys, and the
foreign-key rules the schema depends on.

Every other test module mocks the session; this one is the only place the real
DDL runs. It targets ``TEST_DATABASE_URL`` when set (that is how CI points it at
MySQL and PostgreSQL) and otherwise a throwaway SQLite file, so a plain
``pytest`` needs no database server.
"""

import os
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text

from chaka import clock, database, models, repositories

TEST_DATABASE_URL = os.getenv('TEST_DATABASE_URL', '')
SQLITE_ONLY = pytest.mark.skipif(
    not (TEST_DATABASE_URL or 'sqlite').startswith('sqlite'), reason='SQLite-specific behaviour'
)


def _reset(url: str) -> None:
    """Drop whatever a previous test left behind, then migrate to head."""
    from chaka.cli import db_downgrade, db_upgrade

    with patch.dict(os.environ, {'DATABASE_URL': url}):
        try:
            db_downgrade('base')
        except Exception:
            pass  # nothing applied yet
        db_upgrade('head')


@pytest.fixture
def db_url(tmp_path):
    url = TEST_DATABASE_URL or f'sqlite+aiosqlite:///{tmp_path}/chaka.db'
    _reset(url)
    return url


@pytest.fixture
async def engine(db_url):
    engine = database.make_engine(db_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine):
    return database.make_sessionmaker(engine)


async def test_upgrade_creates_every_table(engine):
    async with engine.connect() as conn:
        names = set(await conn.run_sync(lambda sync: sa.inspect(sync).get_table_names()))
    assert {
        'users',
        'tokens',
        'notification_log',
        'notification_deliveries',
        'token_events',
        'voice_channels',
        'voice_log',
    } <= names


async def test_upgrade_stamps_head(sessionmaker):
    async with sessionmaker() as db:
        assert (await db.execute(text('select version_num from alembic_version'))).scalar() == '0003'


async def test_bigint_primary_keys_autoincrement(sessionmaker):
    """SQLite only auto-assigns a key declared exactly INTEGER, so a BIGINT one
    inserts NULL there. Covers notification_log and voice_log on every engine."""
    notifications = repositories.NotificationRepository(sessionmaker)
    ids = [
        await notifications.create(
            token_id=None,
            msg_id=f'm{i}',
            source='device',
            received_at=clock.utcnow(),
            client_ip='1.2.3.4',
            payload={'i': i},
            forwarded_at=clock.utcnow(),
        )
        for i in range(3)
    ]
    assert ids == [1, 2, 3]

    voice = repositories.VoiceLogRepository(sessionmaker)
    assert [await voice.start(token_id=None, token_name='t', channel_id=1) for _ in range(2)] == [1, 2]


@SQLITE_ONLY
async def test_sqlite_pragmas_are_applied(sessionmaker):
    async with sessionmaker() as db:
        assert (await db.execute(text('PRAGMA foreign_keys'))).scalar() == 1
        assert (await db.execute(text('PRAGMA journal_mode'))).scalar() == 'wal'


async def test_foreign_keys_are_enforced(sessionmaker):
    async with sessionmaker() as db:
        with pytest.raises(sa.exc.IntegrityError):
            await db.execute(
                text(
                    'insert into notification_deliveries (notification_id, token_name, sent_at) '
                    "values (9999, 't', '2026-01-01 00:00:00')"
                )
            )
            await db.commit()


async def test_deleting_a_channel_nulls_its_voice_logs(sessionmaker):
    voice = repositories.VoiceLogRepository(sessionmaker)
    await voice.start(token_id=None, token_name='t', channel_id=1)
    async with sessionmaker() as db:
        channel = (await db.execute(select(models.VoiceChannel).where(models.VoiceChannel.number == 1))).scalar_one()
        await db.delete(channel)
        await db.commit()
        logs = (await db.execute(select(models.VoiceLog))).scalars().all()
    assert logs and all(log.channel_id is None for log in logs)


async def test_default_channel_is_seeded(sessionmaker):
    channels = repositories.VoiceChannelRepository(sessionmaker)
    assert [(c.number, c.name) for c in await channels.list_enabled()] == [(1, 'Channel 1')]
