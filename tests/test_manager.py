from unittest.mock import AsyncMock

from chaka import interfaces, manager, types


async def test_a_second_connection_displaces_the_first(make_ws, make_conn):
    m = manager.ConnectionManager()
    first_ws = make_ws()
    first, displaced = await m.connect(first_ws, make_conn(token_id=1))
    assert first is not None and displaced is None

    second, displaced = await m.connect(make_ws(), make_conn(token_id=1))

    assert second is not None and second != first
    assert displaced is not None and displaced.ws_id == first
    assert displaced.websocket is first_ws
    # And exactly one session survives: the rule is unchanged.
    assert [s.ws_id for s in await m.backend.sessions()] == [second]


async def test_displacing_leaves_other_tokens_alone(make_ws, make_conn):
    m = manager.ConnectionManager()
    other, _ = await m.connect(make_ws(), make_conn(token_id=2))

    _, displaced = await m.connect(make_ws(), make_conn(token_id=1))

    assert displaced is None
    assert other in [s.ws_id for s in await m.backend.sessions()]


async def test_default_voice_log_is_null():
    assert isinstance(manager.ConnectionManager().voice_log, manager.NullVoiceLog)


async def test_get_stats_and_clients(make_ws, make_conn):
    m = manager.ConnectionManager()
    await m.connect(make_ws(), make_conn(token_id=1, can_talk=False, can_hear=False))
    stats = await m.get_stats()
    assert isinstance(stats, types.ConnectionStats)
    assert (stats.total, stats.can_talk, stats.can_hear) == (1, 0, 0)
    clients = await m.get_clients()
    assert clients[0].token_id == 1


async def test_broadcast_delivers_and_returns_recipients(make_ws, make_conn):
    m = manager.ConnectionManager()
    ws = make_ws()
    await m.connect(ws, make_conn(token_id=1, name='rx'))
    assert await m.broadcast('{"x":1}') == [types.Delivery(1, 'rx')]
    assert ws.text_frames == ['{"x":1}']


async def test_join_emits_presence_frames(make_ws, make_conn):
    m = manager.ConnectionManager()
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    a.text_frames.clear()
    await m.join_voice_channel(wb, 5)
    assert 'voice_joined' in b.sent_types()  # joiner learns current members
    assert 'voice_peer_joined' in a.sent_types()  # existing member notified
    stats = await m.get_voice_channel_stats()
    assert stats[5].client_count == 2


async def test_relay_started_logs_and_streams(make_ws, make_conn):
    voice_log = AsyncMock(spec=interfaces.IVoiceLog)
    voice_log.start.return_value = 99
    m = manager.ConnectionManager(voice_log=voice_log)
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    await m.join_voice_channel(wb, 5)
    b.text_frames.clear()
    b.binary_frames.clear()

    await m.relay_voice(wa, 1, 'A', b'audio')
    voice_log.start.assert_awaited_once_with(token_id=1, token_name='A', channel_id=5)
    voice_log.update.assert_awaited_once_with(99, bytes_relayed=5, listeners=1)
    assert b.binary_frames == [b'audio']
    assert 'talking' in b.sent_types()

    await m.end_voice_transmission(wa)
    voice_log.end.assert_awaited_once_with(99, bytes_relayed=5)
    assert 'silent' in b.sent_types()


async def test_relay_busy_when_channel_taken(make_ws, make_conn):
    m = manager.ConnectionManager()
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    await m.join_voice_channel(wb, 5)
    await m.relay_voice(wa, 1, 'A', b'x')  # A owns the channel
    b.text_frames.clear()
    await m.relay_voice(wb, 2, 'B', b'y')  # B is blocked
    assert 'busy' in b.sent_types()


async def test_set_voice_muted_notifies_peers_and_updates_stats(make_ws, make_conn):
    m = manager.ConnectionManager()
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    await m.join_voice_channel(wb, 5)
    b.text_frames.clear()
    await m.set_voice_muted(wa, True)
    assert 'voice_peer_muted' in b.sent_types()
    stats = await m.get_voice_channel_stats()
    assert [c.muted for c in stats[5].clients if c.token_id == 1] == [True]


async def test_revoke_voice_permission(make_ws, make_conn):
    m = manager.ConnectionManager()
    ws = make_ws()
    wsid, _ = await m.connect(ws, make_conn(token_id=1, can_talk=True, can_hear=True))
    await m.join_voice_channel(wsid, 5)
    ws.text_frames.clear()
    await m.revoke_voice_permission_by_token_id(1)
    assert 'voice_ejected' in ws.sent_types()
    stats = await m.get_stats()
    assert (stats.can_talk, stats.can_hear) == (0, 0)


async def test_disconnect_by_token_closes_and_removes(make_ws, make_conn):
    m = manager.ConnectionManager()
    ws = make_ws()
    await m.connect(ws, make_conn(token_id=1))
    await m.disconnect_by_token_id(1)
    assert ws.closed_code == 1008
    assert (await m.get_stats()).total == 0


async def test_disconnect_by_unknown_token_is_noop(make_ws, make_conn):
    m = manager.ConnectionManager()
    await m.disconnect_by_token_id(999)  # must not raise


async def test_send_to_tokens_delegates(make_ws, make_conn):
    m = manager.ConnectionManager()
    ws = make_ws()
    await m.connect(ws, make_conn(token_id=1, name='a'))
    await m.connect(make_ws(), make_conn(token_id=2, name='b'))
    assert await m.send_to_tokens([1], 'hi') == [types.Delivery(1, 'a')]
    assert ws.text_frames == ['hi']


async def test_broadcast_to_voice_clients_reaches_can_hear(make_ws, make_conn):
    m = manager.ConnectionManager()
    hearer = make_ws()
    await m.connect(hearer, make_conn(token_id=1, can_hear=True))
    deaf = make_ws()
    await m.connect(deaf, make_conn(token_id=2, can_hear=False))
    await m.broadcast_to_voice_clients('ping')
    assert hearer.text_frames == ['ping'] and deaf.text_frames == []


async def test_leave_voice_channel_notifies_remaining_peer(make_ws, make_conn):
    m = manager.ConnectionManager()
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    await m.join_voice_channel(wb, 5)
    b.text_frames.clear()
    await m.leave_voice_channel(wa)
    assert 'voice_peer_left' in b.sent_types()
    assert (await m.get_voice_channel_stats())[5].client_count == 1


async def test_set_voice_muted_noop_when_unchanged(make_ws, make_conn):
    m = manager.ConnectionManager()
    ws = make_ws()
    wsid, _ = await m.connect(ws, make_conn(token_id=1))
    await m.join_voice_channel(wsid, 5)
    ws.text_frames.clear()
    await m.set_voice_muted(wsid, False)  # already unmuted -> no frame
    assert ws.text_frames == []


async def test_voice_ops_on_unknown_ws_are_noops(make_ws, make_conn):
    m = manager.ConnectionManager()
    # none of these should raise for an unknown ws_id
    await m.join_voice_channel('ghost', 5)
    await m.leave_voice_channel('ghost')
    await m.set_voice_muted('ghost', True)
    await m.relay_voice('ghost', 1, 't', b'x')
    await m.end_voice_transmission('ghost')


async def test_displacing_frees_the_voice_channel(make_ws, make_conn):
    # Otherwise the reconnecting client finds its own channel occupied by the ghost.
    m = manager.ConnectionManager()
    first, _ = await m.connect(make_ws(), make_conn(token_id=1, can_talk=True))
    await m.join_voice_channel(first, 1)

    second, displaced = await m.connect(make_ws(), make_conn(token_id=1, can_talk=True))

    assert displaced is not None
    sessions = await m.backend.sessions()
    assert [s.ws_id for s in sessions] == [second]
    assert sessions[0].voice_channel_id is None


async def test_displacing_tells_the_peers_the_ghost_left(make_ws, make_conn):
    # The displaced handler cannot do this itself: by the time it wakes up its
    # session is out of the registry and every teardown call is a no-op.
    m = manager.ConnectionManager()
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    await m.join_voice_channel(wb, 5)
    b.text_frames.clear()

    await m.connect(make_ws(), make_conn(token_id=1, name='A'))

    assert 'voice_peer_left' in b.sent_types()


async def test_displacing_closes_an_open_transmission(make_ws, make_conn):
    # Otherwise the voice_log row stays open forever and peers never hear silence.
    voice_log = AsyncMock()
    voice_log.start.return_value = 99
    m = manager.ConnectionManager(voice_log=voice_log)
    a, b = make_ws(), make_ws()
    wa, _ = await m.connect(a, make_conn(token_id=1, name='A'))
    wb, _ = await m.connect(b, make_conn(token_id=2, name='B'))
    await m.join_voice_channel(wa, 5)
    await m.join_voice_channel(wb, 5)
    await m.relay_voice(wa, 1, 'A', b'audio')
    b.text_frames.clear()

    await m.connect(make_ws(), make_conn(token_id=1, name='A'))

    assert 'silent' in b.sent_types()
    voice_log.end.assert_awaited_once_with(99, bytes_relayed=5)
