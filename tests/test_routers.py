"""Router tests via TestClient, mocking the DB session (``get_db`` override),
admin auth, the manager, and repositories — no real database.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from chaka import application, auth, database, factory, interfaces, types

BEARER = {'Authorization': 'Bearer sometoken'}


def _result(**kw):
    r = MagicMock()
    r.scalar_one_or_none.return_value = kw.get('scalar_one_or_none')
    r.scalar_one.return_value = kw.get('scalar_one', 0)
    r.scalar.return_value = kw.get('scalar', 0)
    r.scalars.return_value.all.return_value = kw.get('rows', [])
    r.all.return_value = kw.get('all', [])
    r.rowcount = kw.get('rowcount', 0)
    return r


def db_token(**kw):
    defaults = dict(
        id=1,
        name='t',
        token='secret',
        is_active=True,
        can_send=True,
        can_receive=True,
        can_talk=False,
        can_hear=False,
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def channel(**kw):
    defaults = dict(id=1, number=1, name='Channel 1', is_enabled=True, created_at=datetime.now(UTC))
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.fixture
def ctx(tmp_path):
    manager = AsyncMock(spec=interfaces.IConnectionManager)
    settings = application.Settings(
        admin_user='u',
        admin_password='p',
        log_file=str(tmp_path / 'c.log'),
        heartbeat_log_file=str(tmp_path / 'h.log'),
    )
    app = factory.create_app(settings, manager=manager)
    db = AsyncMock()
    db.add = MagicMock()

    async def _get_db():
        yield db

    app.fastapi.dependency_overrides[database.get_db] = _get_db
    app.fastapi.dependency_overrides[auth.require_admin] = lambda: 'admin'
    app.fastapi.state.token_repo = AsyncMock()
    app.fastapi.state.notification_repo = AsyncMock()
    return SimpleNamespace(client=TestClient(app), db=db, manager=manager, app=app)


# --- notify (bearer + repos) --------------------------------------------------
def test_notify_rejects_invalid_token(ctx):
    ctx.app.fastapi.state.token_repo.get_active.return_value = None
    r = ctx.client.post('/api/notify', json={'title': 'x'}, headers=BEARER)
    assert r.status_code == 401


def test_notify_forbids_without_send(ctx):
    ctx.app.fastapi.state.token_repo.get_active.return_value = db_token(can_send=False)
    r = ctx.client.post('/api/notify', json={'title': 'x'}, headers=BEARER)
    assert r.status_code == 403


def test_notify_accepts_and_broadcasts(ctx):
    ctx.app.fastapi.state.token_repo.get_active.return_value = db_token(can_send=True)
    ctx.app.fastapi.state.notification_repo.create.return_value = 1
    ctx.manager.broadcast.return_value = [types.Delivery(2, 'rx')]
    r = ctx.client.post('/api/notify', json={'title': 'hi'}, headers=BEARER)
    assert r.status_code == 202 and r.json()['sent'] == 1
    ctx.app.fastapi.state.notification_repo.record_deliveries.assert_awaited_once()


# --- send (admin + repos) -----------------------------------------------------
def test_send_broadcast(ctx):
    ctx.app.fastapi.state.notification_repo.create.return_value = 5
    ctx.manager.broadcast.return_value = [types.Delivery(1, 'a')]
    r = ctx.client.post('/api/send', json={'title': 'hi'})
    assert r.status_code == 200 and r.json()['sent'] == 1
    ctx.manager.broadcast.assert_awaited_once()


def test_send_to_specific_tokens(ctx):
    ctx.app.fastapi.state.notification_repo.create.return_value = 5
    ctx.manager.send_to_tokens.return_value = []
    r = ctx.client.post('/api/send', json={'title': 'hi', 'token_ids': [1, 2]})
    assert r.status_code == 200
    ctx.manager.send_to_tokens.assert_awaited_once()


# --- ack (bearer + get_db) ----------------------------------------------------
def test_ack_preflight_sets_cors_for_extension_origin(ctx):
    r = ctx.client.options('/api/ack', headers={'origin': 'chrome-extension://abc'})
    assert r.status_code == 200
    assert r.headers['access-control-allow-origin'] == 'chrome-extension://abc'


def test_ack_rejects_invalid_token(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    r = ctx.client.post('/api/ack', json={'msg_ids': ['a']}, headers=BEARER)
    assert r.status_code == 401


def test_ack_forbids_without_receive(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(can_receive=False))]
    r = ctx.client.post('/api/ack', json={'msg_ids': ['a']}, headers=BEARER)
    assert r.status_code == 403


def test_ack_empty_is_noop(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(can_receive=True))]
    r = ctx.client.post('/api/ack', json={'msg_ids': []}, headers=BEARER)
    assert r.status_code == 200 and r.json() == {'acked': 0}


def test_ack_marks_delivered(ctx):
    ctx.db.execute.side_effect = [
        _result(scalar_one_or_none=db_token(can_receive=True)),
        _result(rowcount=3),
    ]
    r = ctx.client.post('/api/ack', json={'msg_ids': ['a', 'b']}, headers=BEARER)
    assert r.status_code == 200 and r.json() == {'acked': 3}


# --- tokens (admin + get_db) --------------------------------------------------
def test_rename_missing_token_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    r = ctx.client.patch('/api/tokens/9', json={'name': 'new'})
    assert r.status_code == 404


def test_rename_token_ok(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(name='old'))]
    r = ctx.client.patch('/api/tokens/1', json={'name': 'new'})
    assert r.status_code == 200 and r.json()['name'] == 'new'


def test_revoke_already_revoked_409(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(is_active=False))]
    r = ctx.client.delete('/api/tokens/1')
    assert r.status_code == 409


def test_revoke_disconnects_client(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(is_active=True))]
    r = ctx.client.delete('/api/tokens/1')
    assert r.status_code == 204
    ctx.manager.disconnect_by_token_id.assert_awaited_once_with(1)


def test_restore_not_revoked_409(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(is_active=True))]
    r = ctx.client.post('/api/tokens/1/restore')
    assert r.status_code == 409


def test_permissions_downgrade_revokes_voice(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(can_talk=True, can_hear=True))]
    body = {'can_send': True, 'can_receive': True, 'can_talk': False, 'can_hear': False}
    r = ctx.client.patch('/api/tokens/1/permissions', json=body)
    assert r.status_code == 200
    ctx.manager.revoke_voice_permission_by_token_id.assert_awaited_once_with(1)


def test_regenerate_missing_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    r = ctx.client.post('/api/tokens/9/regenerate')
    assert r.status_code == 404


def test_regenerate_rotates_and_disconnects(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(token='old'))]
    r = ctx.client.post('/api/tokens/1/regenerate')
    assert r.status_code == 200
    ctx.manager.disconnect_by_token_id.assert_awaited_once_with(1)


def test_restore_revoked_token_ok(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(is_active=False))]
    r = ctx.client.post('/api/tokens/1/restore')
    assert r.status_code == 200 and r.json()['is_active'] is True


def test_permissions_grant_does_not_revoke_voice(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=db_token(can_talk=False, can_hear=False))]
    body = {'can_send': True, 'can_receive': True, 'can_talk': True, 'can_hear': True}
    r = ctx.client.patch('/api/tokens/1/permissions', json=body)
    assert r.status_code == 200
    ctx.manager.revoke_voice_permission_by_token_id.assert_not_awaited()


def test_token_events_empty(ctx):
    ctx.db.execute.side_effect = [
        _result(scalar_one_or_none=db_token()),  # token exists
        _result(scalar=0),  # count
        _result(rows=[]),  # items
    ]
    r = ctx.client.get('/api/tokens/1/events')
    assert r.status_code == 200 and r.json()['total'] == 0


def test_token_deliveries_missing_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    r = ctx.client.get('/api/tokens/9/deliveries')
    assert r.status_code == 404


# --- logs / voice (admin + get_db) --------------------------------------------
def test_logs_list_empty(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one=0), _result(all=[])]
    r = ctx.client.get('/api/logs')
    assert r.status_code == 200 and r.json()['items'] == []


def test_connection_log_empty(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one=0), _result(rows=[])]
    r = ctx.client.get('/api/connection-log')
    assert r.status_code == 200 and r.json()['total'] == 0


def test_server_log_missing_file(ctx, tmp_path):
    ctx.app.fastapi.state.settings = application.Settings(log_file=str(tmp_path / 'absent.log'))
    r = ctx.client.get('/api/server-log')
    assert r.status_code == 200 and 'not found' in r.text


def test_voice_log_empty(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one=0), _result(rows=[])]
    r = ctx.client.get('/api/voice-log')
    assert r.status_code == 200 and r.json()['items'] == []


# --- channels (admin + get_db + manager) --------------------------------------
def test_channels_list_empty(ctx):
    ctx.db.execute.side_effect = [_result(rows=[])]
    ctx.manager.get_voice_channel_stats.return_value = {}
    r = ctx.client.get('/api/channels')
    assert r.status_code == 200 and r.json() == []


def test_create_channel_conflict(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=channel())]  # number exists
    r = ctx.client.post('/api/channels', json={'number': 1, 'name': 'dup'})
    assert r.status_code == 409


def test_update_channel_missing_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    r = ctx.client.patch('/api/channels/9', json={'name': 'x'})
    assert r.status_code == 404


def test_update_channel_ok(ctx):
    ctx.db.execute.side_effect = [
        _result(scalar_one_or_none=channel(name='old')),  # lookup
        _result(rows=[]),  # _push_channels_updated: enabled channels
    ]
    ctx.manager.get_voice_channel_stats.return_value = {}
    r = ctx.client.patch('/api/channels/1', json={'name': 'new'})
    assert r.status_code == 200 and r.json()['name'] == 'new'
    ctx.manager.broadcast_to_voice_clients.assert_awaited_once()


def test_delete_channel_with_clients_409(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=channel())]
    ctx.manager.get_voice_channel_stats.return_value = {
        1: types.VoiceChannelStats(current_transmitter=None, client_count=2, clients=[])
    }
    r = ctx.client.delete('/api/channels/1')
    assert r.status_code == 409


def test_delete_channel_ok(ctx):
    ctx.db.execute.side_effect = [
        _result(scalar_one_or_none=channel()),  # lookup
        _result(rows=[]),  # _push_channels_updated: enabled channels
    ]
    ctx.manager.get_voice_channel_stats.return_value = {}
    r = ctx.client.delete('/api/channels/1')
    assert r.status_code == 204
    ctx.manager.broadcast_to_voice_clients.assert_awaited_once()
