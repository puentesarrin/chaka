"""In-memory implementation of :class:`chaka.interfaces.IBackend`.

Everything lives in this process: a dict of sessions, a dict of voice channels,
and one asyncio lock guarding compound mutations. Delivery goes straight to the
local sockets. A distributed backend (e.g. Redis) implements the same interface
with a shared registry + pub/sub while keeping sockets per-instance.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union

from chaka import interfaces, types


@dataclass
class VoiceChannelState:
    """Live membership and transmitter slot for one voice channel."""

    current_transmitter: Optional[str] = None
    clients: Set[str] = field(default_factory=set)


class InMemoryBackend(interfaces.IBackend):
    def __init__(self) -> None:
        self._sessions: Dict[str, types.ClientSession] = {}
        self._channels: Dict[int, VoiceChannelState] = {}
        self._lock = asyncio.Lock()

    async def register(self, session: types.ClientSession) -> bool:
        async with self._lock:
            for existing in self._sessions.values():
                if existing.connection.token_id == session.connection.token_id:
                    return False
            self._sessions[session.ws_id] = session
            return True

    async def unregister(self, ws_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(ws_id, None)
            if session is not None and session.voice_channel_id is not None:
                self._discard_from_channel(session.voice_channel_id, ws_id)

    async def get(self, ws_id: str) -> Optional[types.ClientSession]:
        async with self._lock:
            return self._sessions.get(ws_id)

    async def find_ws_id_by_token(self, token_id: int) -> Optional[str]:
        async with self._lock:
            return next((s.ws_id for s in self._sessions.values() if s.connection.token_id == token_id), None)

    async def sessions(self) -> List[types.ClientSession]:
        async with self._lock:
            return list(self._sessions.values())

    async def replace_connection(self, ws_id: str, connection: types.ClientConnection) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is not None:
                session.connection = connection

    async def set_muted(self, ws_id: str, muted: bool) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is not None:
                session.muted = muted

    async def set_channel(self, ws_id: str, channel_id: Optional[int]) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is not None:
                session.voice_channel_id = channel_id

    async def channel_add(self, channel_id: int, ws_id: str) -> None:
        async with self._lock:
            self._channels.setdefault(channel_id, VoiceChannelState()).clients.add(ws_id)

    async def channel_discard(self, channel_id: int, ws_id: str) -> None:
        async with self._lock:
            self._discard_from_channel(channel_id, ws_id)

    async def channel_members(self, channel_id: int) -> List[types.ClientSession]:
        async with self._lock:
            ch = self._channels.get(channel_id)
            if ch is None:
                return []
            return [self._sessions[w] for w in ch.clients if w in self._sessions]

    async def channel_ids(self) -> List[int]:
        async with self._lock:
            return list(self._channels.keys())

    async def get_transmitter(self, channel_id: int) -> Optional[str]:
        async with self._lock:
            ch = self._channels.get(channel_id)
            return ch.current_transmitter if ch else None

    async def begin_transmit(self, ws_id: str) -> types.TransmitClaim:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is None or session.voice_channel_id is None:
                return types.TransmitClaim(types.TransmitStatus.ABSENT)
            channel_id = session.voice_channel_id
            ch = self._channels.get(channel_id)
            if ch is None:
                return types.TransmitClaim(types.TransmitStatus.ABSENT)
            if ch.current_transmitter is not None and ch.current_transmitter != ws_id:
                ct = self._sessions.get(ch.current_transmitter)
                return types.TransmitClaim(
                    types.TransmitStatus.BUSY, channel_id, ct.connection.token_name if ct else ''
                )
            if not session.transmitting:
                session.transmitting = True
                ch.current_transmitter = ws_id
                session.bytes_relayed = 0
                return types.TransmitClaim(types.TransmitStatus.STARTED, channel_id)
            return types.TransmitClaim(types.TransmitStatus.CONTINUING, channel_id)

    async def end_transmit(self, ws_id: str) -> Optional[types.TransmitEnd]:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is None or not session.transmitting:
                return None
            session.transmitting = False
            channel_id = session.voice_channel_id
            if channel_id is not None and channel_id in self._channels:
                ch = self._channels[channel_id]
                if ch.current_transmitter == ws_id:
                    ch.current_transmitter = None
            result = types.TransmitEnd(
                channel_id, session.connection.token_name, session.voice_log_id, session.bytes_relayed
            )
            session.voice_log_id = None
            session.bytes_relayed = 0
            session.tx_started_at = None
            return result

    async def add_bytes(self, ws_id: str, n: int) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is not None:
                session.bytes_relayed += n

    async def set_voice_log_id(self, ws_id: str, log_id: int) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            if session is not None:
                session.voice_log_id = log_id

    async def send(self, ws_id: str, data: Union[str, bytes]) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            websocket = session.websocket if session else None
        if websocket is None:
            return
        try:
            if isinstance(data, bytes):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)
        except Exception:
            await self.unregister(ws_id)

    async def close(self, ws_id: str, code: int) -> None:
        async with self._lock:
            session = self._sessions.get(ws_id)
            websocket = session.websocket if session else None
        if websocket is None:
            return
        try:
            await websocket.close(code=code)
        except Exception:
            ...

    async def broadcast(self, message: str) -> List[types.Delivery]:
        async with self._lock:
            targets = [s for s in self._sessions.values() if s.connection.can_receive]
        return await self._deliver_text(targets, message)

    async def send_to_tokens(self, token_ids: List[int], message: str) -> List[types.Delivery]:
        async with self._lock:
            targets = [
                s for s in self._sessions.values() if s.connection.token_id in token_ids and s.connection.can_receive
            ]
        return await self._deliver_text(targets, message)

    async def broadcast_to_voice(self, message: str) -> None:
        async with self._lock:
            targets = [s for s in self._sessions.values() if s.connection.can_hear]
        for session in targets:
            try:
                await session.websocket.send_text(message)
            except Exception:
                ...

    def _discard_from_channel(self, channel_id: int, ws_id: str) -> None:
        ch = self._channels.get(channel_id)
        if ch is not None:
            ch.clients.discard(ws_id)
            if ch.current_transmitter == ws_id:
                ch.current_transmitter = None

    async def _deliver_text(self, targets: List[types.ClientSession], message: str) -> List[types.Delivery]:
        delivered: List[types.Delivery] = []
        for session in targets:
            try:
                await session.websocket.send_text(message)
                delivered.append(types.Delivery(session.connection.token_id, session.connection.token_name))
            except Exception:
                await self.unregister(session.ws_id)
        return delivered
