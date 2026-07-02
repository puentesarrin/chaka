"""Chaka's shared data vocabulary: the value objects, runtime state, and
read-model snapshots passed between the manager, its backend, and the API.

These are plain dataclasses (plus one enum) with no behaviour — the contracts in
:mod:`chaka.interfaces` are defined in terms of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional

from fastapi import WebSocket


@dataclass(frozen=True)
class ClientConnection:
    """Identity, origin, and permissions of a client at connect time."""

    token_id: int
    token_name: str
    ip: str
    can_send: bool
    can_receive: bool
    can_talk: bool
    can_hear: bool
    client: str
    version: str


@dataclass
class ClientSession:
    """A live connection: its immutable :class:`ClientConnection` plus runtime state.

    ``websocket`` is process-local — for a distributed backend it is ``None`` on
    instances that don't hold the socket (delivery goes via the backend instead).
    """

    ws_id: str
    connection: ClientConnection
    websocket: Optional[WebSocket]
    connected_at: datetime
    voice_channel_id: Optional[int] = None
    transmitting: bool = False
    muted: bool = False
    voice_log_id: Optional[int] = None
    bytes_relayed: int = 0
    tx_started_at: Optional[datetime] = None


@dataclass(frozen=True)
class ConnectionStats:
    total: int
    can_send: int
    can_receive: int
    can_talk: int
    can_hear: int
    transmitting: int


@dataclass(frozen=True)
class VoiceMember:
    ws_id: str
    token_id: int
    token_name: str
    transmitting: bool
    muted: bool


@dataclass(frozen=True)
class VoiceChannelStats:
    current_transmitter: Optional[str]
    client_count: int
    clients: List[VoiceMember]


@dataclass(frozen=True)
class ClientView:
    ws_id: str
    token_id: int
    token_name: str
    ip: str
    connected_at: datetime
    client: str
    version: str
    can_receive: bool
    voice_channel_id: Optional[int]
    transmitting: bool


class TransmitStatus(Enum):
    ABSENT = 'absent'
    BUSY = 'busy'
    STARTED = 'started'
    CONTINUING = 'continuing'


@dataclass(frozen=True)
class Delivery:
    """One recipient a message was successfully delivered to."""

    token_id: int
    token_name: str


@dataclass(frozen=True)
class TransmitClaim:
    """Outcome of a transmitter claim. ``channel_id``/``busy_token_name`` are set
    per :class:`TransmitStatus` (busy_token_name only when ``BUSY``)."""

    status: TransmitStatus
    channel_id: Optional[int] = None
    busy_token_name: str = ''


@dataclass(frozen=True)
class TransmitEnd:
    """State captured when a transmission ends, for the silent frame + voice-log close."""

    channel_id: Optional[int]
    token_name: str
    voice_log_id: Optional[int]
    bytes_relayed: int
