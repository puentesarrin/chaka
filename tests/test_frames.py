import json

from chaka import frames


def test_all_frame_types_enumerated():
    assert len(list(frames.FrameType)) == 13


def test_hello_includes_channels_when_given():
    f = json.loads(frames.hello(can_send=True, can_receive=False, can_talk=True, can_hear=True, channels=[{'id': 1}]))
    assert f == {
        'type': 'hello',
        'can_send': True,
        'can_receive': False,
        'can_talk': True,
        'can_hear': True,
        'channels': [{'id': 1}],
    }


def test_hello_omits_channels_when_none():
    f = json.loads(frames.hello(can_send=False, can_receive=True, can_talk=False, can_hear=False))
    assert 'channels' not in f


def test_single_omits_received_at_when_absent():
    assert json.loads(frames.single(msg_id='m', message={'a': 1})) == {
        'type': 'single',
        'msg_id': 'm',
        'message': {'a': 1},
    }


def test_single_includes_received_at():
    assert json.loads(frames.single(msg_id='m', message={}, received_at='2026-01-01T00:00:00'))['received_at'] == (
        '2026-01-01T00:00:00'
    )


def test_voice_peer_mute_toggles_type():
    assert json.loads(frames.voice_peer_mute(channel_id=1, token_name='t', muted=True))['type'] == 'voice_peer_muted'
    assert json.loads(frames.voice_peer_mute(channel_id=1, token_name='t', muted=False))['type'] == 'voice_peer_unmuted'


def test_talking_and_silent_shape():
    assert json.loads(frames.talking(channel_id=3, token_name='x')) == {
        'type': 'talking',
        'token_name': 'x',
        'channel_id': 3,
    }
    assert json.loads(frames.silent(channel_id=3, token_name='x')) == {
        'type': 'silent',
        'token_name': 'x',
        'channel_id': 3,
    }


def test_voice_ejected():
    assert json.loads(frames.voice_ejected()) == {'type': 'voice_ejected'}


def test_frametype_serializes_as_plain_string():
    # StrEnum members must JSON-encode to their value, not "FrameType.HELLO"
    assert json.loads(frames.busy(token_name='t'))['type'] == 'busy'
