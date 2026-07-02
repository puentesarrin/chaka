"""Shared test helpers: a fake WebSocket, connection/token builders, and a mock
sessionmaker for repository tests. No real DB or sockets are used anywhere.
"""

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from chaka import types


@pytest.fixture(autouse=True)
def _reset_logging():
    """create_app() attaches rotating file handlers to shared loggers; drop them
    after each test so they don't accumulate and write to deleted tmp paths."""
    yield
    for name in ('chaka', 'heartbeat', 'httpx'):
        lg = logging.getLogger(name)
        for handler in lg.handlers[:]:
            lg.removeHandler(handler)


class FakeWebSocket:
    """Records outbound frames and replays a scripted inbound queue."""

    def __init__(self, incoming=None, host='1.2.3.4', raise_on_send=False):
        self.text_frames = []
        self.binary_frames = []
        self.closed_code = None
        self.accepted = False
        self.raise_on_send = raise_on_send
        self._incoming = list(incoming or [])
        self.client = SimpleNamespace(host=host)
        self.app = SimpleNamespace(state=SimpleNamespace())

    async def accept(self):
        self.accepted = True

    async def send_text(self, data):
        if self.raise_on_send:
            raise RuntimeError('send failed')
        self.text_frames.append(data)

    async def send_bytes(self, data):
        if self.raise_on_send:
            raise RuntimeError('send failed')
        self.binary_frames.append(data)

    async def close(self, code=1000):
        self.closed_code = code

    async def receive(self):
        if self._incoming:
            return self._incoming.pop(0)
        return {'type': 'websocket.disconnect'}

    def sent_types(self):
        return [json.loads(t).get('type') for t in self.text_frames]


@pytest.fixture
def make_ws():
    return FakeWebSocket


@pytest.fixture
def make_conn():
    def _make(token_id=1, name='t', can_send=True, can_receive=True, can_talk=True, can_hear=True):
        return types.ClientConnection(
            token_id, name, '1.2.3.4', can_send, can_receive, can_talk, can_hear, 'app', '1.0'
        )

    return _make


@pytest.fixture
def make_session():
    def _make(ws_id, conn, ws):
        return types.ClientSession(ws_id=ws_id, connection=conn, websocket=ws, connected_at=datetime.now(UTC))

    return _make


@pytest.fixture
def make_token():
    def _make(id=1, name='t', can_send=True, can_receive=True, can_talk=True, can_hear=True, last_delivered_at=None):
        return SimpleNamespace(
            id=id,
            name=name,
            can_send=can_send,
            can_receive=can_receive,
            can_talk=can_talk,
            can_hear=can_hear,
            last_delivered_at=last_delivered_at,
        )

    return _make


@pytest.fixture
def fake_session():
    """Return ``(sessionmaker, db)`` where ``sessionmaker()`` is an async CM yielding ``db``."""

    def _make():
        db = AsyncMock()
        db.add = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        return MagicMock(return_value=cm), db

    return _make
