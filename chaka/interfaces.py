"""Contracts for Chaka's pluggable collaborators.

Depend on these, not the concrete classes, so alternative implementations can be
injected via ``create_app(manager=..., handler=...)`` or the factory's
``get_manager`` / ``get_handler`` overrides.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

from fastapi import WebSocket

from chaka import types


class IBackend(ABC):
    """State registry + delivery substrate for :class:`IConnectionManager`.

    Owns *where* sessions and voice-channel state live and *how* frames reach
    clients. The in-memory implementation keeps everything local; a distributed
    (e.g. Redis) implementation keeps a shared registry + pub/sub fan-out while
    the WebSocket sockets stay per-instance.
    """

    @abstractmethod
    async def register(self, session: types.ClientSession) -> bool: ...

    @abstractmethod
    async def unregister(self, ws_id: str) -> None: ...

    @abstractmethod
    async def get(self, ws_id: str) -> Optional[types.ClientSession]: ...

    @abstractmethod
    async def find_ws_id_by_token(self, token_id: int) -> Optional[str]: ...

    @abstractmethod
    async def sessions(self) -> List[types.ClientSession]: ...

    @abstractmethod
    async def replace_connection(self, ws_id: str, connection: types.ClientConnection) -> None: ...

    @abstractmethod
    async def set_muted(self, ws_id: str, muted: bool) -> None: ...

    @abstractmethod
    async def set_channel(self, ws_id: str, channel_id: Optional[int]) -> None: ...

    @abstractmethod
    async def channel_add(self, channel_id: int, ws_id: str) -> None: ...

    @abstractmethod
    async def channel_discard(self, channel_id: int, ws_id: str) -> None: ...

    @abstractmethod
    async def channel_members(self, channel_id: int) -> List[types.ClientSession]: ...

    @abstractmethod
    async def channel_ids(self) -> List[int]: ...

    @abstractmethod
    async def get_transmitter(self, channel_id: int) -> Optional[str]: ...

    @abstractmethod
    async def begin_transmit(self, ws_id: str) -> types.TransmitClaim:
        """Atomically claim the channel transmitter."""

    @abstractmethod
    async def end_transmit(self, ws_id: str) -> Optional[types.TransmitEnd]:
        """End transmission; returns the captured state, or None if not transmitting."""

    @abstractmethod
    async def add_bytes(self, ws_id: str, n: int) -> None: ...

    @abstractmethod
    async def set_voice_log_id(self, ws_id: str, log_id: int) -> None: ...

    @abstractmethod
    async def send(self, ws_id: str, data: Union[str, bytes]) -> None: ...

    @abstractmethod
    async def close(self, ws_id: str, code: int) -> None: ...

    @abstractmethod
    async def broadcast(self, message: str) -> List[types.Delivery]: ...

    @abstractmethod
    async def send_to_tokens(self, token_ids: List[int], message: str) -> List[types.Delivery]: ...

    @abstractmethod
    async def broadcast_to_voice(self, message: str) -> None: ...


class IConnectionManager(ABC):
    """Owns live connections, broadcast fan-out, and voice-channel state."""

    @abstractmethod
    async def connect(self, websocket: WebSocket, connection: types.ClientConnection) -> Optional[str]: ...

    @abstractmethod
    async def disconnect(self, ws_id: str) -> None: ...

    @abstractmethod
    async def disconnect_by_token_id(self, token_id: int) -> None: ...

    @abstractmethod
    async def broadcast(self, message: str) -> List[types.Delivery]: ...

    @abstractmethod
    async def send_to_tokens(self, token_ids: List[int], message: str) -> List[types.Delivery]: ...

    @abstractmethod
    async def join_voice_channel(self, ws_id: str, channel_id: int) -> None: ...

    @abstractmethod
    async def leave_voice_channel(self, ws_id: str) -> None: ...

    @abstractmethod
    async def set_voice_muted(self, ws_id: str, muted: bool) -> None: ...

    @abstractmethod
    async def relay_voice(self, sender_ws_id: str, token_id: int, token_name: str, data: bytes) -> None: ...

    @abstractmethod
    async def end_voice_transmission(self, ws_id: str) -> None: ...

    @abstractmethod
    async def eject_all_from_voice_channel(self, channel_id: int) -> None: ...

    @abstractmethod
    async def revoke_voice_permission_by_token_id(self, token_id: int) -> None: ...

    @abstractmethod
    async def broadcast_to_voice_clients(self, message: str) -> None: ...

    @abstractmethod
    async def get_clients(self) -> List[types.ClientView]: ...

    @abstractmethod
    async def get_voice_channel_stats(self) -> Dict[int, types.VoiceChannelStats]: ...

    @abstractmethod
    async def get_stats(self) -> types.ConnectionStats: ...


class IVoiceLog(ABC):
    """Persistence port for voice-transmission logging.

    Decouples :class:`IConnectionManager` from the ORM: the manager records
    transmissions through this port instead of holding a DB session.
    """

    @abstractmethod
    async def start(self, *, token_id: int, token_name: str, channel_id: int) -> Optional[int]:
        """Record a transmission start; returns the log id (or None if not persisted)."""

    @abstractmethod
    async def update(self, log_id: int, *, bytes_relayed: int, listeners: int) -> None: ...

    @abstractmethod
    async def end(self, log_id: int, *, bytes_relayed: int) -> None: ...


class IWebSocketHandler(ABC):
    """Handles a single ``/ws`` connection from accept through disconnect."""

    @abstractmethod
    async def handle(self, websocket: WebSocket, token: str, client: str, version: str) -> None: ...
