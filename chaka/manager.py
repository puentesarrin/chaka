import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Dict, List, Optional

from fastapi import WebSocket

from chaka import frames, interfaces, types
from chaka.backend import InMemoryBackend


class NullVoiceLog(interfaces.IVoiceLog):
    """No-op voice-log port — the default when no persistence is wired (e.g. tests)."""

    async def start(self, *, token_id: int, token_name: str, channel_id: int) -> Optional[int]:
        return None

    async def update(self, log_id: int, *, bytes_relayed: int, listeners: int) -> None: ...

    async def end(self, log_id: int, *, bytes_relayed: int) -> None: ...


class ConnectionManager(interfaces.IConnectionManager):
    """Protocol orchestration over a pluggable :class:`IBackend` and :class:`IVoiceLog`.

    Builds the wire frames and gates on permissions; state and delivery are
    delegated to the backend (in-memory by default, e.g. Redis for scaling), and
    voice-transmission persistence to the voice-log port.
    """

    def __init__(
        self, backend: Optional[interfaces.IBackend] = None, voice_log: Optional[interfaces.IVoiceLog] = None
    ) -> None:
        self.backend = backend or InMemoryBackend()
        self.voice_log = voice_log or NullVoiceLog()

    async def connect(self, websocket: WebSocket, connection: types.ClientConnection) -> Optional[str]:
        ws_id = str(uuid.uuid4())
        session = types.ClientSession(
            ws_id=ws_id, connection=connection, websocket=websocket, connected_at=datetime.now(UTC)
        )
        return ws_id if await self.backend.register(session) else None

    async def disconnect(self, ws_id: str) -> None:
        await self.backend.unregister(ws_id)

    async def disconnect_by_token_id(self, token_id: int) -> None:
        ws_id = await self.backend.find_ws_id_by_token(token_id)
        if ws_id is None:
            return
        await self.backend.close(ws_id, 1008)
        await self.backend.unregister(ws_id)

    async def broadcast(self, message: str) -> List[types.Delivery]:
        return await self.backend.broadcast(message)

    async def send_to_tokens(self, token_ids: List[int], message: str) -> List[types.Delivery]:
        return await self.backend.send_to_tokens(token_ids, message)

    async def broadcast_to_voice_clients(self, message: str) -> None:
        await self.backend.broadcast_to_voice(message)

    async def set_voice_muted(self, ws_id: str, muted: bool) -> None:
        session = await self.backend.get(ws_id)
        if session is None or session.muted == muted:
            return
        await self.backend.set_muted(ws_id, muted)
        channel_id = session.voice_channel_id
        if channel_id is None:
            return
        frame = frames.voice_peer_mute(channel_id=channel_id, token_name=session.connection.token_name, muted=muted)
        for member in await self.backend.channel_members(channel_id):
            if member.ws_id != ws_id:
                await self.backend.send(member.ws_id, frame)

    async def join_voice_channel(self, ws_id: str, channel_id: int) -> None:
        session = await self.backend.get(ws_id)
        if session is None:
            return
        joining_token_name = session.connection.token_name

        old_channel_id = session.voice_channel_id
        if old_channel_id is not None:
            await self.backend.channel_discard(old_channel_id, ws_id)
            peer_left = frames.voice_peer_left(channel_id=old_channel_id, token_name=joining_token_name)
            for member in await self.backend.channel_members(old_channel_id):
                await self.backend.send(member.ws_id, peer_left)

        current = await self.backend.channel_members(channel_id)
        peers = [
            {'token_name': m.connection.token_name, 'transmitting': m.transmitting, 'muted': m.muted} for m in current
        ]
        await self.backend.channel_add(channel_id, ws_id)
        await self.backend.set_channel(ws_id, channel_id)

        await self.backend.send(ws_id, frames.voice_joined(channel_id=channel_id, clients=peers))
        peer_joined = frames.voice_peer_joined(channel_id=channel_id, token_name=joining_token_name)
        for member in current:
            await self.backend.send(member.ws_id, peer_joined)

    async def leave_voice_channel(self, ws_id: str) -> None:
        session = await self.backend.get(ws_id)
        if session is None or session.voice_channel_id is None:
            return
        channel_id = session.voice_channel_id
        leaving_token_name = session.connection.token_name
        await self.backend.channel_discard(channel_id, ws_id)
        await self.backend.set_channel(ws_id, None)
        frame = frames.voice_peer_left(channel_id=channel_id, token_name=leaving_token_name)
        for member in await self.backend.channel_members(channel_id):
            await self.backend.send(member.ws_id, frame)

    async def relay_voice(self, sender_ws_id: str, token_id: int, token_name: str, data: bytes) -> None:
        claim = await self.backend.begin_transmit(sender_ws_id)
        if claim.status == types.TransmitStatus.ABSENT:
            return
        if claim.status == types.TransmitStatus.BUSY:
            await self.backend.send(sender_ws_id, frames.busy(token_name=claim.busy_token_name))
            return

        channel_id = claim.channel_id
        if claim.status == types.TransmitStatus.STARTED:
            log_id = await self.voice_log.start(token_id=token_id, token_name=token_name, channel_id=channel_id)
            if log_id is not None:
                await self.backend.set_voice_log_id(sender_ws_id, log_id)
            talking = frames.talking(channel_id=channel_id, token_name=token_name)
            for member in await self.backend.channel_members(channel_id):
                if member.ws_id != sender_ws_id and not member.muted:
                    await self.backend.send(member.ws_id, talking)

        await self.backend.add_bytes(sender_ws_id, len(data))
        listener_count = 0
        for member in await self.backend.channel_members(channel_id):
            if member.ws_id != sender_ws_id and not member.muted:
                await self.backend.send(member.ws_id, data)
                listener_count += 1

        sender = await self.backend.get(sender_ws_id)
        if sender is not None and sender.voice_log_id is not None:
            await self.voice_log.update(
                sender.voice_log_id, bytes_relayed=sender.bytes_relayed, listeners=listener_count
            )

    async def end_voice_transmission(self, ws_id: str) -> None:
        result = await self.backend.end_transmit(ws_id)
        if result is None:
            return
        if result.channel_id is not None:
            silent = frames.silent(channel_id=result.channel_id, token_name=result.token_name)
            for member in await self.backend.channel_members(result.channel_id):
                if member.ws_id != ws_id:
                    await self.backend.send(member.ws_id, silent)
        if result.voice_log_id is not None:
            await self.voice_log.end(result.voice_log_id, bytes_relayed=result.bytes_relayed)

    async def eject_all_from_voice_channel(self, channel_id: int) -> None:
        for member in await self.backend.channel_members(channel_id):
            await self.end_voice_transmission(member.ws_id)
            await self.leave_voice_channel(member.ws_id)

    async def revoke_voice_permission_by_token_id(self, token_id: int) -> None:
        ws_id = await self.backend.find_ws_id_by_token(token_id)
        if ws_id is None:
            return
        session = await self.backend.get(ws_id)
        if session is None or not (session.connection.can_talk or session.connection.can_hear):
            return
        await self.backend.replace_connection(ws_id, replace(session.connection, can_talk=False, can_hear=False))
        await self.end_voice_transmission(ws_id)
        await self.leave_voice_channel(ws_id)
        await self.backend.send(ws_id, frames.voice_ejected())

    async def get_clients(self) -> List[types.ClientView]:
        return [
            types.ClientView(
                ws_id=s.ws_id,
                token_id=s.connection.token_id,
                token_name=s.connection.token_name,
                ip=s.connection.ip,
                connected_at=s.connected_at,
                client=s.connection.client,
                version=s.connection.version,
                can_receive=s.connection.can_receive,
                voice_channel_id=s.voice_channel_id,
                transmitting=s.transmitting,
            )
            for s in await self.backend.sessions()
        ]

    async def get_voice_channel_stats(self) -> Dict[int, types.VoiceChannelStats]:
        result: Dict[int, types.VoiceChannelStats] = {}
        for channel_id in await self.backend.channel_ids():
            members = await self.backend.channel_members(channel_id)
            transmitter = await self.backend.get_transmitter(channel_id)
            clients = [
                types.VoiceMember(
                    ws_id=m.ws_id,
                    token_id=m.connection.token_id,
                    token_name=m.connection.token_name,
                    transmitting=m.transmitting,
                    muted=m.muted,
                )
                for m in members
            ]
            result[channel_id] = types.VoiceChannelStats(
                current_transmitter=transmitter, client_count=len(clients), clients=clients
            )
        return result

    async def get_stats(self) -> types.ConnectionStats:
        sessions = await self.backend.sessions()
        return types.ConnectionStats(
            total=len(sessions),
            can_send=sum(1 for s in sessions if s.connection.can_send),
            can_receive=sum(1 for s in sessions if s.connection.can_receive),
            can_talk=sum(1 for s in sessions if s.connection.can_talk),
            can_hear=sum(1 for s in sessions if s.connection.can_hear),
            transmitting=sum(1 for s in sessions if s.transmitting),
        )
