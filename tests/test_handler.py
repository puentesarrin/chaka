import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from chaka import application, interfaces, repositories


def _wire(ws, **overrides):
    ws.app.state.manager = overrides.get('manager') or AsyncMock(spec=interfaces.IConnectionManager)
    ws.app.state.token_repo = overrides.get('token_repo') or AsyncMock(spec=repositories.TokenRepository)
    ws.app.state.notification_repo = overrides.get('notification_repo') or AsyncMock(
        spec=repositories.NotificationRepository
    )
    ws.app.state.channel_repo = overrides.get('channel_repo') or AsyncMock(spec=repositories.VoiceChannelRepository)
    return ws


def _text(payload):
    return {'type': 'websocket.receive', 'text': json.dumps(payload)}


async def test_unknown_token_closes_4401(make_ws):
    ws = _wire(make_ws())
    ws.app.state.token_repo.get_active.return_value = None
    await application.WebSocketHandler().handle(ws, token='bad', client='c', version='1')
    assert ws.closed_code == 4401
    assert not ws.accepted


async def test_duplicate_connection_closes_4409(make_ws, make_token):
    ws = _wire(make_ws())
    ws.app.state.token_repo.get_active.return_value = make_token()
    ws.app.state.manager.connect.return_value = None
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    assert ws.accepted and ws.closed_code == 4409


async def test_hello_and_events_on_connect(make_ws, make_token):
    ws = _wire(make_ws())
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=True, can_hear=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.channel_repo.list_enabled.return_value = []
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    assert 'hello' in ws.sent_types()
    # connected + disconnected events recorded
    events = [c.kwargs['event'] for c in ws.app.state.token_repo.record_event.await_args_list]
    assert events == ['connected', 'disconnected']


async def test_voice_join_dispatches_when_permitted(make_ws, make_token):
    ws = _wire(make_ws(incoming=[_text({'type': 'voice_join', 'channel_id': 3})]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=True, can_hear=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.channel_repo.list_enabled.return_value = []
    ws.app.state.channel_repo.get_enabled.return_value = object()  # channel exists + enabled
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.manager.join_voice_channel.assert_awaited_once_with('wsid', 3)


async def test_voice_join_denied_without_voice_permission(make_ws, make_token):
    ws = _wire(make_ws(incoming=[_text({'type': 'voice_join', 'channel_id': 3})]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=False, can_hear=False, can_send=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.manager.join_voice_channel.assert_not_awaited()


async def test_voice_join_ignored_for_unknown_channel(make_ws, make_token):
    ws = _wire(make_ws(incoming=[_text({'type': 'voice_join', 'channel_id': 999})]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=True, can_hear=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.channel_repo.list_enabled.return_value = []
    ws.app.state.channel_repo.get_enabled.return_value = None  # not found / disabled
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.manager.join_voice_channel.assert_not_awaited()


async def test_notification_without_timestamp_does_not_crash(make_ws, make_token):
    # regression: payload['timestamp'] used to KeyError and tear down the loop
    ws = _wire(make_ws(incoming=[_text({'title': 'hi'})]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_send=True, can_talk=False, can_hear=False)
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.manager.broadcast.return_value = []
    ws.app.state.notification_repo.create.return_value = 1
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.notification_repo.create.assert_awaited_once()
    ws.app.state.manager.broadcast.assert_awaited_once()


async def test_notification_denied_without_send_permission(make_ws, make_token):
    ws = _wire(make_ws(incoming=[_text({'title': 'hi', 'timestamp': 1000})]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_send=False)
    ws.app.state.manager.connect.return_value = 'wsid'
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.notification_repo.create.assert_not_awaited()
    ws.app.state.manager.broadcast.assert_not_awaited()


async def test_replay_runs_when_receiver_has_prior_delivery(make_ws, make_token):
    ws = _wire(make_ws())
    ws.app.state.token_repo.get_active.return_value = make_token(can_receive=True, last_delivered_at=object())
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.notification_repo.missed_since.return_value = []  # nothing pending -> no replay frame
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.notification_repo.missed_since.assert_awaited_once()


async def test_replay_sends_pending_and_records(make_ws, make_token):
    ws = _wire(make_ws())
    ws.app.state.token_repo.get_active.return_value = make_token(can_receive=True, last_delivered_at=object())
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.notification_repo.missed_since.return_value = [
        SimpleNamespace(id=10, msg_id='m1', payload={'title': 'a'})
    ]
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    assert 'replay' in ws.sent_types()
    ws.app.state.notification_repo.record_replay.assert_awaited_once()
    ws.app.state.token_repo.mark_delivered.assert_awaited_once()


async def test_voice_leave_dispatches(make_ws, make_token):
    ws = _wire(make_ws(incoming=[_text({'type': 'voice_leave'})]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=True, can_hear=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.channel_repo.list_enabled.return_value = []
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.manager.leave_voice_channel.assert_awaited_with('wsid')


async def test_voice_mute_and_unmute_dispatch(make_ws, make_token):
    for msg_type, expected in (('voice_mute', True), ('voice_unmute', False)):
        ws = _wire(make_ws(incoming=[_text({'type': msg_type})]))
        ws.app.state.token_repo.get_active.return_value = make_token(can_talk=True, can_hear=True)
        ws.app.state.manager.connect.return_value = 'wsid'
        ws.app.state.channel_repo.list_enabled.return_value = []
        await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
        ws.app.state.manager.set_voice_muted.assert_awaited_once_with('wsid', muted=expected)


async def test_binary_audio_relayed_and_ptt_release_ends(make_ws, make_token):
    ws = _wire(
        make_ws(
            incoming=[
                {'type': 'websocket.receive', 'bytes': b'audio'},
                {'type': 'websocket.receive', 'bytes': b'\x00'},  # PTT release sentinel
            ]
        )
    )
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=True, can_hear=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    ws.app.state.channel_repo.list_enabled.return_value = []
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.manager.relay_voice.assert_awaited_once_with('wsid', 1, 't', b'audio')
    # end_voice_transmission fires for the sentinel and again in the finally block
    assert ws.app.state.manager.end_voice_transmission.await_count >= 1


async def test_binary_ignored_without_talk_permission(make_ws, make_token):
    ws = _wire(make_ws(incoming=[{'type': 'websocket.receive', 'bytes': b'audio'}]))
    ws.app.state.token_repo.get_active.return_value = make_token(can_talk=False, can_send=True)
    ws.app.state.manager.connect.return_value = 'wsid'
    await application.WebSocketHandler().handle(ws, token='t', client='c', version='1')
    ws.app.state.manager.relay_voice.assert_not_awaited()
