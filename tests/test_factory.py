from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from chaka import application, factory, interfaces


@pytest.fixture
def settings(tmp_path):
    return application.Settings(
        admin_user='u',
        admin_password='p',
        log_file=str(tmp_path / 'chaka.log'),
        heartbeat_log_file=str(tmp_path / 'heartbeat.log'),
    )


def test_create_app_wires_state(settings):
    app = factory.create_app(settings)
    assert isinstance(app, application.ChakaApp)
    state = app.fastapi.state
    for attr in (
        'settings',
        'manager',
        'engine',
        'sessionmaker',
        'templates',
        'handler',
        'token_repo',
        'notification_repo',
        'channel_repo',
    ):
        assert hasattr(state, attr), attr
    assert isinstance(state.manager, interfaces.IConnectionManager)


def test_manager_can_be_injected(settings):
    fake = AsyncMock(spec=interfaces.IConnectionManager)
    app = factory.create_app(settings, manager=fake)
    assert app.fastapi.state.manager is fake


def test_admin_route_requires_valid_basic_auth(settings):
    fake = AsyncMock(spec=interfaces.IConnectionManager)
    fake.get_clients.return_value = []
    app = factory.create_app(settings, manager=fake)
    with TestClient(app) as client:
        assert client.get('/api/clients', auth=('u', 'p')).status_code == 200
        assert client.get('/api/clients', auth=('u', 'p')).json() == []
        assert client.get('/api/clients', auth=('u', 'wrong')).status_code == 401
        assert client.get('/api/clients').status_code == 401


def _override_settings(tmp_path):
    return application.Settings(
        templates_dir=str(tmp_path),
        static_dir=str(tmp_path),
        log_file=str(tmp_path / 'c.log'),
        heartbeat_log_file=str(tmp_path / 'h.log'),
    )


def test_templates_fall_back_to_bundled(tmp_path):
    (tmp_path / 'custom.html').write_text('hi')
    app = factory.create_app(_override_settings(tmp_path))
    env = app.fastapi.state.templates.env
    assert env.get_template('custom.html') is not None  # from the override dir
    assert env.get_template('index.html') is not None  # falls back to Chaka's bundle


def test_static_falls_back_to_bundled(tmp_path):
    (tmp_path / 'brand.txt').write_text('BRAND')
    app = factory.create_app(_override_settings(tmp_path))
    with TestClient(app) as client:
        assert client.get('/static/brand.txt').status_code == 200  # from the override dir
        assert client.get('/static/app.js').status_code == 200  # falls back to Chaka's bundle
        assert client.get('/static/nope.xyz').status_code == 404
