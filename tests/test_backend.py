from chaka import backend, types


async def test_register_dedupes_by_token(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    assert await be.register(make_session('a', make_conn(token_id=1), make_ws())) is True
    assert await be.register(make_session('b', make_conn(token_id=1), make_ws())) is False  # same token
    assert await be.register(make_session('c', make_conn(token_id=2), make_ws())) is True


async def test_find_and_get(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    await be.register(make_session('a', make_conn(token_id=7), make_ws()))
    assert await be.find_ws_id_by_token(7) == 'a'
    assert await be.find_ws_id_by_token(99) is None
    assert (await be.get('a')).connection.token_id == 7
    assert await be.get('missing') is None


async def test_unregister_cleans_up_channel(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    await be.register(make_session('a', make_conn(), make_ws()))
    await be.channel_add(5, 'a')
    await be.set_channel('a', 5)
    await be.begin_transmit('a')  # 'a' becomes the transmitter
    await be.unregister('a')
    assert await be.get('a') is None
    assert await be.get_transmitter(5) is None
    assert await be.channel_members(5) == []


async def test_begin_transmit_state_machine(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    assert (await be.begin_transmit('nope')).status is types.TransmitStatus.ABSENT

    await be.register(make_session('a', make_conn(token_id=1, name='t'), make_ws()))
    assert (await be.begin_transmit('a')).status is types.TransmitStatus.ABSENT  # not in a channel

    await be.channel_add(5, 'a')
    await be.set_channel('a', 5)
    started = await be.begin_transmit('a')
    assert started.status is types.TransmitStatus.STARTED and started.channel_id == 5
    assert (await be.begin_transmit('a')).status is types.TransmitStatus.CONTINUING

    await be.register(make_session('b', make_conn(token_id=2, name='other'), make_ws()))
    await be.channel_add(5, 'b')
    await be.set_channel('b', 5)
    busy = await be.begin_transmit('b')
    assert busy.status is types.TransmitStatus.BUSY and busy.busy_token_name == 't'


async def test_end_transmit_captures_state_and_clears(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    await be.register(make_session('a', make_conn(token_id=1, name='t'), make_ws()))
    await be.channel_add(5, 'a')
    await be.set_channel('a', 5)
    await be.begin_transmit('a')
    await be.set_voice_log_id('a', 42)
    await be.add_bytes('a', 100)

    end = await be.end_transmit('a')
    assert (end.channel_id, end.token_name, end.voice_log_id, end.bytes_relayed) == (5, 't', 42, 100)
    assert await be.get_transmitter(5) is None
    assert await be.end_transmit('a') is None  # no longer transmitting


async def test_broadcast_returns_deliveries_and_filters_can_receive(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    await be.register(make_session('a', make_conn(token_id=1, name='rx', can_receive=True), make_ws()))
    await be.register(make_session('b', make_conn(token_id=2, name='no', can_receive=False), make_ws()))
    assert await be.broadcast('hi') == [types.Delivery(1, 'rx')]


async def test_send_to_tokens_targets_subset(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    await be.register(make_session('a', make_conn(token_id=1, name='one'), make_ws()))
    await be.register(make_session('b', make_conn(token_id=2, name='two'), make_ws()))
    assert await be.send_to_tokens([2], 'hi') == [types.Delivery(2, 'two')]


async def test_broadcast_unregisters_on_send_failure(make_ws, make_conn, make_session):
    be = backend.InMemoryBackend()
    await be.register(make_session('a', make_conn(token_id=1), make_ws(raise_on_send=True)))
    assert await be.broadcast('hi') == []
    assert await be.get('a') is None  # failed delivery evicts the session
