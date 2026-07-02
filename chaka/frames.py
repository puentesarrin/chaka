"""The WebSocket wire protocol: one place that knows the shape of every JSON
frame Chaka sends.

:class:`FrameType` enumerates the ``type`` tag; the builders return the encoded
``str`` ready to hand to a socket or an :class:`~chaka.interfaces.IConnectionManager`
delivery method. See PROTOCOL.md for the full spec.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Dict, List, Optional


class FrameType(StrEnum):
    HELLO = 'hello'
    REPLAY = 'replay'
    SINGLE = 'single'
    CHANNELS_UPDATED = 'channels_updated'
    VOICE_JOINED = 'voice_joined'
    VOICE_PEER_JOINED = 'voice_peer_joined'
    VOICE_PEER_LEFT = 'voice_peer_left'
    VOICE_PEER_MUTED = 'voice_peer_muted'
    VOICE_PEER_UNMUTED = 'voice_peer_unmuted'
    BUSY = 'busy'
    TALKING = 'talking'
    SILENT = 'silent'
    VOICE_EJECTED = 'voice_ejected'


def hello(
    *,
    can_send: bool,
    can_receive: bool,
    can_talk: bool,
    can_hear: bool,
    channels: Optional[List[Dict[str, Any]]] = None,
) -> str:
    frame: Dict[str, Any] = {
        'type': FrameType.HELLO,
        'can_send': can_send,
        'can_receive': can_receive,
        'can_talk': can_talk,
        'can_hear': can_hear,
    }
    if channels is not None:
        frame['channels'] = channels
    return json.dumps(frame)


def replay(*, count: int, has_more: bool, messages: List[Dict[str, Any]]) -> str:
    return json.dumps({'type': FrameType.REPLAY, 'count': count, 'has_more': has_more, 'messages': messages})


def single(*, msg_id: str, message: Dict[str, Any], received_at: Optional[str] = None) -> str:
    frame: Dict[str, Any] = {'type': FrameType.SINGLE, 'msg_id': msg_id}
    if received_at is not None:
        frame['received_at'] = received_at
    frame['message'] = message
    return json.dumps(frame)


def channels_updated(*, channels: List[Dict[str, Any]]) -> str:
    return json.dumps({'type': FrameType.CHANNELS_UPDATED, 'channels': channels})


def voice_joined(*, channel_id: int, clients: List[Dict[str, Any]]) -> str:
    return json.dumps({'type': FrameType.VOICE_JOINED, 'channel_id': channel_id, 'clients': clients})


def voice_peer_joined(*, channel_id: int, token_name: str) -> str:
    return json.dumps({'type': FrameType.VOICE_PEER_JOINED, 'channel_id': channel_id, 'token_name': token_name})


def voice_peer_left(*, channel_id: int, token_name: str) -> str:
    return json.dumps({'type': FrameType.VOICE_PEER_LEFT, 'channel_id': channel_id, 'token_name': token_name})


def voice_peer_mute(*, channel_id: int, token_name: str, muted: bool) -> str:
    frame_type = FrameType.VOICE_PEER_MUTED if muted else FrameType.VOICE_PEER_UNMUTED
    return json.dumps({'type': frame_type, 'channel_id': channel_id, 'token_name': token_name})


def busy(*, token_name: str) -> str:
    return json.dumps({'type': FrameType.BUSY, 'token_name': token_name})


def talking(*, channel_id: int, token_name: str) -> str:
    return json.dumps({'type': FrameType.TALKING, 'token_name': token_name, 'channel_id': channel_id})


def silent(*, channel_id: int, token_name: str) -> str:
    return json.dumps({'type': FrameType.SILENT, 'token_name': token_name, 'channel_id': channel_id})


def voice_ejected() -> str:
    return json.dumps({'type': FrameType.VOICE_EJECTED})
