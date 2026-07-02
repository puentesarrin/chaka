"""The Chaka application: configuration, the ASGI app wrapper, and the WebSocket
runtime handler.

- :class:`Settings` — immutable configuration (loads itself from the environment).
- :class:`ChakaApp` — a thin composition wrapper around a FastAPI instance; it is
  itself a valid ASGI app and adds a convenience :meth:`ChakaApp.run`.
- :class:`WebSocketHandler` — the runtime behaviour for a single ``/ws`` connection.
  It reads its collaborators (``manager``, ``sessionmaker``) from ``app.state``.

Construction/wiring lives in :mod:`chaka.factory`; this module is just the pieces.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from chaka import frames, inbound, interfaces, repositories, types

# Bundled asset directories, resolved relative to this package so they work
# whether Chaka is run from a clone or pip-installed anywhere on disk.
PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_STATIC_DIR = str(PACKAGE_DIR / 'static')
DEFAULT_TEMPLATES_DIR = str(PACKAGE_DIR / 'templates')


@dataclass(frozen=True)
class Settings:
    title: str = 'Chaka'
    static_dir: str = DEFAULT_STATIC_DIR
    templates_dir: str = DEFAULT_TEMPLATES_DIR
    websocket_path: str = '/ws'
    database_url: str = 'mysql+aiomysql://user:pass@localhost:3306/chaka'
    admin_user: str = 'admin'
    admin_password: str = 'changeme'
    log_file: str = './chaka.log'
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5
    heartbeat_log_file: str = './heartbeat.log'
    heartbeat_url: Optional[str] = None
    heartbeat_interval: int = 60
    sentry_dsn: Optional[str] = None
    sentry_traces_sample_rate: float = 0.2

    @classmethod
    def from_env(cls) -> 'Settings':
        return cls(
            title=os.getenv('TITLE', cls.title),
            static_dir=os.getenv('STATIC_DIR', cls.static_dir),
            templates_dir=os.getenv('TEMPLATES_DIR', cls.templates_dir),
            websocket_path=os.getenv('WEBSOCKET_PATH', cls.websocket_path),
            database_url=os.getenv('DATABASE_URL', cls.database_url),
            admin_user=os.getenv('ADMIN_USER', cls.admin_user),
            admin_password=os.getenv('ADMIN_PASSWORD', cls.admin_password),
            log_file=os.getenv('LOG_FILE', cls.log_file),
            log_max_bytes=int(os.getenv('LOG_MAX_BYTES', cls.log_max_bytes)),
            log_backup_count=int(os.getenv('LOG_BACKUP_COUNT', cls.log_backup_count)),
            heartbeat_log_file=os.getenv('HEARTBEAT_LOG_FILE', cls.heartbeat_log_file),
            heartbeat_url=os.getenv('HEARTBEAT_URL', cls.heartbeat_url),
            heartbeat_interval=int(os.getenv('HEARTBEAT_INTERVAL', cls.heartbeat_interval)),
            sentry_dsn=os.getenv('SENTRY_DSN', cls.sentry_dsn),
            sentry_traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', cls.sentry_traces_sample_rate)),
        )


class ChakaApp:
    """The application: owns a FastAPI instance and its lifecycle.

    A composition wrapper (not a FastAPI subclass): it builds its own FastAPI
    with its lifespan (:meth:`_lifespan`), is itself a valid ASGI app
    (``__call__`` delegates, so ``uvicorn main:app`` works), and adds a
    convenience :meth:`run`. The factory populates ``self.fastapi.state`` with
    the collaborators the app needs (manager, engine, sessionmaker, …).
    """

    def __init__(self, settings: Settings, logger: logging.Logger, heartbeat_logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.heartbeat_logger = heartbeat_logger
        self.fastapi = FastAPI(title=settings.title, lifespan=self._lifespan)

    async def __call__(self, scope, receive, send) -> None:
        await self.fastapi(scope, receive, send)

    def run(self, host: str = '127.0.0.1', port: int = 8000, **kwargs: Any) -> None:
        """Run with uvicorn. For production prefer invoking an ASGI server
        directly (``uvicorn main:app``) so options like ``--workers`` apply."""
        import uvicorn  # optional convenience; not needed on the `uvicorn main:app` path

        uvicorn.run(self.fastapi, host=host, port=port, **kwargs)

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        self.logger.info('Chaka started')
        heartbeat_task = None
        if self.settings.heartbeat_url:
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(app.state.manager))
            self.heartbeat_logger.info('Heartbeat task started (interval=%ds)', self.settings.heartbeat_interval)
        yield
        self.logger.info('Chaka stopping')
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                ...
        await app.state.engine.dispose()

    async def _heartbeat_loop(self, manager: interfaces.IConnectionManager) -> None:
        url = self.settings.heartbeat_url
        interval = self.settings.heartbeat_interval
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                await asyncio.sleep(interval)
                stats = await manager.get_stats()
                msg = (
                    f'Connected clients: {stats.total} '
                    f'(can_send: {stats.can_send}, can_receive: {stats.can_receive}, '
                    f'can_talk: {stats.can_talk}, can_hear: {stats.can_hear})'
                )
                try:
                    await client.get(url, params={'status': 'up', 'msg': msg})
                    self.heartbeat_logger.info('Heartbeat sent: %s', msg)
                except Exception as exc:
                    self.heartbeat_logger.warning('Heartbeat failed: %s', exc)


class WebSocketHandler(interfaces.IWebSocketHandler):
    """Handles the lifecycle of a single ``/ws`` connection.

    Collaborators (``manager``, ``sessionmaker``) are read from ``app.state`` on
    each connection, so a handler instance is stateless and shared. Swap it for a
    custom one by passing ``handler=`` to the factory's ``create_app``.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger('chaka')

    async def handle(self, websocket: WebSocket, token: str, client: str, version: str) -> None:
        state = websocket.app.state
        manager: interfaces.IConnectionManager = state.manager
        tokens: repositories.TokenRepository = state.token_repo
        notifications: repositories.NotificationRepository = state.notification_repo
        channels: repositories.VoiceChannelRepository = state.channel_repo

        db_token = await tokens.get_active(token)
        if db_token is None:
            await websocket.close(code=4401)
            return

        ip = websocket.client.host if websocket.client else 'unknown'
        await websocket.accept()
        conn = types.ClientConnection(
            token_id=db_token.id,
            token_name=db_token.name,
            ip=ip,
            can_send=db_token.can_send,
            can_receive=db_token.can_receive,
            can_talk=db_token.can_talk,
            can_hear=db_token.can_hear,
            client=client,
            version=version,
        )
        ws_id = await manager.connect(websocket, conn)
        if ws_id is None:
            self.logger.warning('WS rejected: token=%s ip=%s — already connected', conn.token_name, ip)
            await websocket.close(code=4409)
            return
        self.logger.info(
            'WS connect: ws_id=%s token=%s client=%s version=%s ip=%s',
            ws_id,
            conn.token_name,
            client or '-',
            version or '-',
            ip,
        )

        await self._send_hello(websocket, channels, conn)
        await self._record_event(tokens, conn, 'connected', self._connect_detail(conn))

        if conn.can_receive and db_token.last_delivered_at is not None:
            await self._replay_missed(websocket, notifications, tokens, ws_id, db_token.last_delivered_at, conn)

        try:
            while True:
                message = await websocket.receive()
                if message['type'] == 'websocket.disconnect':
                    break
                raw_bytes = message.get('bytes')
                raw_text = message.get('text')
                if raw_bytes is not None:
                    await self._handle_binary(manager, ws_id, conn, raw_bytes)
                elif raw_text:
                    await self._handle_text(manager, channels, notifications, tokens, ws_id, conn, raw_text)
        except WebSocketDisconnect:
            ...
        finally:
            await manager.end_voice_transmission(ws_id)
            await manager.leave_voice_channel(ws_id)
            await manager.disconnect(ws_id)
            try:
                await self._record_event(tokens, conn, 'disconnected', {'ip': ip})
            except Exception:
                ...
            self.logger.info('WS disconnect: ws_id=%s', ws_id)

    async def _handle_binary(
        self, manager: interfaces.IConnectionManager, ws_id: str, conn: types.ClientConnection, raw: bytes
    ) -> None:
        if not conn.can_talk:
            return
        if raw == b'\x00':
            await manager.end_voice_transmission(ws_id)
        else:
            await manager.relay_voice(ws_id, conn.token_id, conn.token_name, raw)

    async def _handle_text(
        self,
        manager: interfaces.IConnectionManager,
        channels: repositories.VoiceChannelRepository,
        notifications: repositories.NotificationRepository,
        tokens: repositories.TokenRepository,
        ws_id: str,
        conn: types.ClientConnection,
        raw_text: str,
    ) -> None:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return

        msg_type = payload.get('type')

        if msg_type == inbound.InboundType.VOICE_JOIN:
            if not (conn.can_talk or conn.can_hear):
                return
            channel_id = payload.get('channel_id')
            if not isinstance(channel_id, int):
                return
            if await channels.get_enabled(channel_id) is None:
                return
            await manager.end_voice_transmission(ws_id)
            await manager.join_voice_channel(ws_id, channel_id)
            self.logger.info('Voice join: ws_id=%s token=%s channel_id=%d', ws_id, conn.token_name, channel_id)
        elif msg_type == inbound.InboundType.VOICE_LEAVE:
            if not (conn.can_talk or conn.can_hear):
                return
            await manager.end_voice_transmission(ws_id)
            await manager.leave_voice_channel(ws_id)
            self.logger.info('Voice leave: ws_id=%s token=%s', ws_id, conn.token_name)
        elif msg_type in (inbound.InboundType.VOICE_MUTE, inbound.InboundType.VOICE_UNMUTE):
            if not conn.can_talk:
                return
            await manager.set_voice_muted(ws_id, muted=msg_type == inbound.InboundType.VOICE_MUTE)
            self.logger.info('Voice %s: ws_id=%s token=%s', msg_type, ws_id, conn.token_name)
        else:
            if not conn.can_send:
                return
            await self._handle_notification(manager, notifications, tokens, conn, payload)

    async def _handle_notification(
        self,
        manager: interfaces.IConnectionManager,
        notifications: repositories.NotificationRepository,
        tokens: repositories.TokenRepository,
        conn: types.ClientConnection,
        payload: dict,
    ) -> None:
        msg_id = str(uuid.uuid4())
        ts = payload.get('timestamp')
        received_at = datetime.fromtimestamp(ts / 1000, UTC) if isinstance(ts, (int, float)) else datetime.now(UTC)
        log_id = await notifications.create(
            token_id=conn.token_id,
            msg_id=msg_id,
            source='device',
            received_at=received_at,
            client_ip=conn.ip,
            payload=payload,
            forwarded_at=datetime.now(UTC),
        )
        delivered = await manager.broadcast(
            frames.single(msg_id=msg_id, received_at=received_at.isoformat(), message=payload)
        )
        self.logger.info(
            'Broadcast: token=%s scope=%s delivered=%d', conn.token_name, payload.get('scope', ''), len(delivered)
        )
        if delivered:
            now = datetime.now(UTC)
            await tokens.mark_delivered([d.token_id for d in delivered], now)
            await notifications.record_deliveries(log_id, delivered, now)

    async def _send_hello(
        self, websocket: WebSocket, channels: repositories.VoiceChannelRepository, conn: types.ClientConnection
    ) -> None:
        channel_list = None
        if conn.can_talk or conn.can_hear:
            enabled = await channels.list_enabled()
            channel_list = [{'id': ch.id, 'number': ch.number, 'name': ch.name} for ch in enabled]
        await websocket.send_text(
            frames.hello(
                can_send=conn.can_send,
                can_receive=conn.can_receive,
                can_talk=conn.can_talk,
                can_hear=conn.can_hear,
                channels=channel_list,
            )
        )

    async def _replay_missed(
        self,
        websocket: WebSocket,
        notifications: repositories.NotificationRepository,
        tokens: repositories.TokenRepository,
        ws_id: str,
        since: datetime,
        conn: types.ClientConnection,
    ) -> None:
        fetched = await notifications.missed_since(since, limit=101)
        has_more = len(fetched) == 101
        pending = fetched[:100]
        if not pending:
            return
        await websocket.send_text(
            frames.replay(
                count=len(pending),
                has_more=has_more,
                messages=[{'msg_id': p.msg_id, 'message': p.payload} for p in pending],
            )
        )
        self.logger.info('WS replay: ws_id=%s token=%s count=%d', ws_id, conn.token_name, len(pending))
        now = datetime.now(UTC)
        await notifications.record_replay(
            token_id=conn.token_id, token_name=conn.token_name, notification_ids=[p.id for p in pending], when=now
        )
        await tokens.mark_delivered([conn.token_id], now)

    @staticmethod
    def _connect_detail(conn: types.ClientConnection) -> dict:
        detail: dict = {'ip': conn.ip}
        if conn.client:
            detail['client'] = conn.client
        if conn.version:
            detail['version'] = conn.version
        return detail

    async def _record_event(
        self, tokens: repositories.TokenRepository, conn: types.ClientConnection, event: str, detail: dict
    ) -> None:
        await tokens.record_event(token_id=conn.token_id, token_name=conn.token_name, event=event, detail=detail)
