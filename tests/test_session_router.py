"""The login/logout routes: redirect targets and what the cookie does."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from chaka import application, factory, interfaces, models, passwords


@pytest.fixture
def client(tmp_path):
    settings = application.Settings(
        secret_key='test-secret',
        log_file=str(tmp_path / 'c.log'),
        heartbeat_log_file=str(tmp_path / 'h.log'),
    )
    app = factory.create_app(settings, manager=AsyncMock(spec=interfaces.IConnectionManager))
    user = models.User(
        id=1,
        username='jorge',
        email='jorge@example.com',
        full_name=None,
        password_hash=passwords.hash_password('hunter2!!', iterations=1),
        is_active=True,
        created_at=None,
    )
    repo = AsyncMock()
    repo.get.side_effect = lambda uid: user if uid == 1 else None
    repo.get_by_username.side_effect = lambda name: user if name == 'jorge' else None
    repo.count.return_value = 1
    app.fastapi.state.user_repo = repo
    return SimpleNamespace(http=TestClient(app, follow_redirects=False), user=user, repo=repo)


# --- routes -------------------------------------------------------------------
def test_login_page_renders(client):
    r = client.http.get('/login')
    assert r.status_code == 200
    assert 'name="username"' in r.text and 'name="password"' in r.text


def test_login_page_does_not_load_the_dashboard_script(client):
    assert '/static/app.js' not in client.http.get('/login').text


def test_failed_login_re_renders_with_an_error(client):
    r = client.http.post('/login', data={'username': 'jorge', 'password': 'wrong'})
    assert r.status_code == 401
    assert 'Invalid username or password' in r.text
    assert 'chaka_session' not in r.cookies


def test_successful_login_sets_a_hardened_cookie(client):
    r = client.http.post('/login', data={'username': 'jorge', 'password': 'hunter2!!'})
    assert r.status_code == 303
    cookie = r.headers['set-cookie']
    assert 'chaka_session=' in cookie
    assert 'HttpOnly' in cookie
    assert 'SameSite=lax' in cookie


@pytest.mark.parametrize('target', ['/', '/tokens', '/a?b=c'])
def test_login_honours_a_same_site_next(client, target):
    r = client.http.post('/login', data={'username': 'jorge', 'password': 'hunter2!!', 'next': target})
    assert r.headers['location'] == target


@pytest.mark.parametrize('target', ['https://evil.example', '//evil.example', 'evil.example', ''])
def test_login_ignores_an_off_site_next(client, target):
    r = client.http.post('/login', data={'username': 'jorge', 'password': 'hunter2!!', 'next': target})
    assert r.headers['location'] == '/'


@pytest.mark.parametrize('target', ['https://evil.example', '//evil.example'])
def test_login_page_ignores_an_off_site_next(client, target):
    client.http.post('/login', data={'username': 'jorge', 'password': 'hunter2!!'})
    r = client.http.get('/login', params={'next': target})
    assert r.status_code == 303 and r.headers['location'] == '/'


def test_login_page_redirects_when_already_signed_in(client):
    client.http.post('/login', data={'username': 'jorge', 'password': 'hunter2!!'})
    r = client.http.get('/login')
    assert r.status_code == 303 and r.headers['location'] == '/'


def test_logout_clears_the_cookie(client):
    client.http.post('/login', data={'username': 'jorge', 'password': 'hunter2!!'})
    r = client.http.post('/logout')
    assert r.status_code == 303 and r.headers['location'] == '/login'
    assert 'chaka_session=""' in r.headers['set-cookie'] or 'chaka_session=;' in r.headers['set-cookie']


def test_logout_is_not_reachable_by_navigation(client):
    assert client.http.get('/logout').status_code == 405
