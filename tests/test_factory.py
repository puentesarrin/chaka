import dataclasses
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from chaka import application, factory, interfaces, models, passwords


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
        'user_repo',
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


def _app_with_user(settings, user):
    fake = AsyncMock(spec=interfaces.IConnectionManager)
    fake.get_clients.return_value = []
    app = factory.create_app(settings, manager=fake)
    repo = AsyncMock()
    repo.get.side_effect = lambda uid: user if uid == user.id else None
    repo.get_by_username.side_effect = lambda name: user if name == user.username else None
    repo.count.return_value = 1
    app.fastapi.state.user_repo = repo
    return app


@pytest.fixture
def user():
    return models.User(
        id=1,
        username='u',
        email='u@example.com',
        full_name=None,
        password_hash=passwords.hash_password('p' * 8, iterations=1),
        is_active=True,
        created_at=None,
    )


def test_admin_route_requires_a_session(settings, user):
    # follow_redirects=False: a successful login lands on '/', which would need a
    # real database. The redirect itself is what this asserts.
    with TestClient(_app_with_user(settings, user), follow_redirects=False) as client:
        assert client.get('/api/clients').status_code == 401

        assert client.post('/login', data={'username': 'u', 'password': 'nope'}).status_code == 401
        assert client.get('/api/clients').status_code == 401

        signed_in = client.post('/login', data={'username': 'u', 'password': 'p' * 8})
        assert signed_in.status_code == 303
        assert signed_in.headers['location'] == '/'
        assert client.get('/api/clients').status_code == 200
        assert client.get('/api/clients').json() == []

        signed_out = client.post('/logout')
        assert signed_out.status_code == 303
        assert signed_out.headers['location'] == '/login'
        assert client.get('/api/clients').status_code == 401


def test_browser_navigation_redirects_to_login(settings, user):
    with TestClient(_app_with_user(settings, user), follow_redirects=False) as client:
        response = client.get('/', headers={'accept': 'text/html'})
        assert response.status_code == 303
        assert response.headers['location'] == '/login?next=%2F'


def test_api_call_gets_json_not_a_redirect(settings, user):
    with TestClient(_app_with_user(settings, user), follow_redirects=False) as client:
        response = client.get('/api/clients')
        assert response.status_code == 401
        assert response.json() == {'detail': 'Not authenticated'}


def test_deactivating_a_user_kills_their_session(settings, user):
    app = _app_with_user(settings, user)
    with TestClient(app, follow_redirects=False) as client:
        client.post('/login', data={'username': 'u', 'password': 'p' * 8})
        assert client.get('/api/clients').status_code == 200
        user.is_active = False
        assert client.get('/api/clients').status_code == 401


def test_secret_key_is_generated_when_unset(settings):
    app = factory.create_app(settings)
    assert app.fastapi.state.settings.secret_key
    assert settings.secret_key == ''  # the caller's Settings is left untouched


def test_configured_secret_key_is_kept(settings):

    configured = dataclasses.replace(settings, secret_key='keep-me')
    app = factory.create_app(configured)
    assert app.fastapi.state.settings.secret_key == 'keep-me'


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
