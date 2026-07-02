"""Inbound control-message vocabulary — the mirror of :mod:`chaka.frames`.

These are the typed control messages a client sends over the WebSocket. Anything
that is not one of these is treated as a free-form notification payload.
"""

from __future__ import annotations

from enum import StrEnum


class InboundType(StrEnum):
    VOICE_JOIN = 'voice_join'
    VOICE_LEAVE = 'voice_leave'
    VOICE_MUTE = 'voice_mute'
    VOICE_UNMUTE = 'voice_unmute'
