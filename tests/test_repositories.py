from datetime import UTC, datetime
from unittest.mock import MagicMock

from chaka import models, repositories, types


async def test_voicelog_start_returns_new_id(fake_session):
    sm, db = fake_session()
    db.add.side_effect = lambda entry: setattr(entry, 'id', 55)
    log_id = await repositories.VoiceLogRepository(sm).start(token_id=1, token_name='t', channel_id=3)
    assert log_id == 55
    added = db.add.call_args.args[0]
    assert isinstance(added, models.VoiceLog) and added.channel_id == 3
    db.commit.assert_awaited_once()


async def test_voicelog_update_and_end_execute(fake_session):
    sm, db = fake_session()
    repo = repositories.VoiceLogRepository(sm)
    await repo.update(9, bytes_relayed=10, listeners=2)
    await repo.end(9, bytes_relayed=20)
    assert db.execute.await_count == 2
    assert db.commit.await_count == 2


async def test_token_get_active(fake_session):
    sm, db = fake_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 'THE_TOKEN'
    db.execute.return_value = result
    assert await repositories.TokenRepository(sm).get_active('abc') == 'THE_TOKEN'
    db.execute.assert_awaited_once()


async def test_token_record_event_adds_row(fake_session):
    sm, db = fake_session()
    await repositories.TokenRepository(sm).record_event(
        token_id=1, token_name='t', event='connected', detail={'ip': 'x'}
    )
    added = db.add.call_args.args[0]
    assert isinstance(added, models.TokenEvent) and added.event == 'connected'
    db.commit.assert_awaited_once()


async def test_token_mark_delivered_noop_when_empty(fake_session):
    sm, db = fake_session()
    await repositories.TokenRepository(sm).mark_delivered([], datetime.now(UTC))
    sm.assert_not_called()
    db.execute.assert_not_awaited()


async def test_token_mark_delivered_executes(fake_session):
    sm, db = fake_session()
    await repositories.TokenRepository(sm).mark_delivered([1, 2], datetime.now(UTC))
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_notification_create_returns_id(fake_session):
    sm, db = fake_session()
    db.add.side_effect = lambda entry: setattr(entry, 'id', 7)
    log_id = await repositories.NotificationRepository(sm).create(
        token_id=1, msg_id='m', source='device', received_at=datetime.now(UTC), client_ip='ip', payload={'a': 1}
    )
    assert log_id == 7
    assert isinstance(db.add.call_args.args[0], models.NotificationLog)


async def test_notification_missed_since_returns_rows(fake_session):
    sm, db = fake_session()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ['n1', 'n2']
    db.execute.return_value = result
    out = await repositories.NotificationRepository(sm).missed_since(datetime.now(UTC), limit=10)
    assert out == ['n1', 'n2']


async def test_notification_record_deliveries_adds_each(fake_session):
    sm, db = fake_session()
    await repositories.NotificationRepository(sm).record_deliveries(
        1, [types.Delivery(1, 'a'), types.Delivery(2, 'b')], datetime.now(UTC)
    )
    assert db.add.call_count == 2
    db.commit.assert_awaited_once()


async def test_notification_record_deliveries_noop_when_empty(fake_session):
    sm, db = fake_session()
    await repositories.NotificationRepository(sm).record_deliveries(1, [], datetime.now(UTC))
    sm.assert_not_called()
    db.commit.assert_not_awaited()


async def test_notification_record_replay_adds_each(fake_session):
    sm, db = fake_session()
    await repositories.NotificationRepository(sm).record_replay(
        token_id=1, token_name='t', notification_ids=[10, 11, 12], when=datetime.now(UTC)
    )
    assert db.add.call_count == 3
    db.commit.assert_awaited_once()


async def test_notification_record_replay_noop_when_empty(fake_session):
    sm, db = fake_session()
    await repositories.NotificationRepository(sm).record_replay(
        token_id=1, token_name='t', notification_ids=[], when=datetime.now(UTC)
    )
    sm.assert_not_called()


async def test_channel_list_enabled(fake_session):
    sm, db = fake_session()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ['c1', 'c2']
    db.execute.return_value = result
    assert await repositories.VoiceChannelRepository(sm).list_enabled() == ['c1', 'c2']


async def test_channel_get_enabled(fake_session):
    sm, db = fake_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 'CHANNEL'
    db.execute.return_value = result
    assert await repositories.VoiceChannelRepository(sm).get_enabled(3) == 'CHANNEL'
