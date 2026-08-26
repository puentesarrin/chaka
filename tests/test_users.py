"""User CRUD routes: validation, uniqueness, and the lock-yourself-out guards.

Same approach as :mod:`tests.test_routers` — the DB session is a mock whose
``execute`` results are scripted per route, so these assert the route's rules
rather than SQL.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from chaka import application, auth, database, factory, interfaces, models, passwords, schemas

VALID = {'username': 'nuevo', 'email': 'nuevo@example.com', 'password': 'sufficient1'}


def _result(**kw):
    r = MagicMock()
    r.scalar_one_or_none.return_value = kw.get('scalar_one_or_none')
    r.scalar.return_value = kw.get('scalar', 0)
    r.scalars.return_value.all.return_value = kw.get('rows', [])
    r.scalars.return_value.first.return_value = kw.get('first')
    return r


def user_row(**kw):
    defaults = dict(
        id=1,
        username='jorge',
        email='jorge@example.com',
        full_name='Jorge',
        password_hash='pbkdf2_sha256$1$c2FsdA==$ZGln',
        is_active=True,
        created_at=datetime.now(UTC),
        last_login_at=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


CURRENT = user_row(id=1, username='jorge')


@pytest.fixture
def ctx(tmp_path):
    manager = AsyncMock(spec=interfaces.IConnectionManager)
    settings = application.Settings(
        secret_key='test',
        log_file=str(tmp_path / 'c.log'),
        heartbeat_log_file=str(tmp_path / 'h.log'),
    )
    app = factory.create_app(settings, manager=manager)
    db = AsyncMock()
    db.add = MagicMock()

    async def _get_db():
        yield db

    async def _refresh(obj):
        # Stand in for the INSERT that would assign the primary key.
        if getattr(obj, 'id', None) is None:
            obj.id = 42

    db.refresh.side_effect = _refresh
    app.fastapi.dependency_overrides[database.get_db] = _get_db
    app.fastapi.dependency_overrides[auth.require_admin] = lambda: CURRENT
    return SimpleNamespace(client=TestClient(app), db=db, app=app)


# --- list / me ----------------------------------------------------------------
def test_list_users(ctx):
    ctx.db.execute.side_effect = [_result(rows=[user_row(), user_row(id=2, username='ana', email='ana@example.com')])]
    r = ctx.client.get('/api/users')
    assert r.status_code == 200
    assert [u['username'] for u in r.json()] == ['jorge', 'ana']


def test_list_never_exposes_the_password_hash(ctx):
    ctx.db.execute.side_effect = [_result(rows=[user_row()])]
    assert 'password_hash' not in ctx.client.get('/api/users').json()[0]


def test_me_returns_the_signed_in_user(ctx):
    r = ctx.client.get('/api/users/me')
    assert r.status_code == 200 and r.json()['username'] == 'jorge'


# --- create -------------------------------------------------------------------
def test_create_user(ctx):
    ctx.db.execute.side_effect = [_result(first=None)]
    r = ctx.client.post('/api/users', json=VALID)
    assert r.status_code == 201
    body = r.json()
    assert body['username'] == 'nuevo' and body['is_active'] is True
    added = ctx.db.add.call_args.args[0]
    assert passwords.verify_password('sufficient1', added.password_hash)
    assert added.password_hash != 'sufficient1'


def test_create_rejects_a_taken_username(ctx):
    ctx.db.execute.side_effect = [_result(first=user_row(username='nuevo'))]
    r = ctx.client.post('/api/users', json=VALID)
    assert r.status_code == 409 and 'Username' in r.json()['detail']


def test_create_rejects_a_taken_email(ctx):
    ctx.db.execute.side_effect = [_result(first=user_row(username='otro', email='nuevo@example.com'))]
    r = ctx.client.post('/api/users', json=VALID)
    assert r.status_code == 409 and 'Email' in r.json()['detail']


@pytest.mark.parametrize(
    'override',
    [
        {'email': 'not-an-email'},
        {'email': 'missing@domain'},
        {'email': ''},
        {'password': 'short'},
        {'username': ''},
        {'username': 'has spaces'},
    ],
)
def test_create_rejects_invalid_input(ctx, override):
    r = ctx.client.post('/api/users', json={**VALID, **override})
    assert r.status_code == 422


def test_create_accepts_an_optional_full_name(ctx):
    ctx.db.execute.side_effect = [_result(first=None)]
    r = ctx.client.post('/api/users', json={**VALID, 'full_name': 'Nueva Persona'})
    assert r.status_code == 201 and r.json()['full_name'] == 'Nueva Persona'


# --- update -------------------------------------------------------------------
def test_update_missing_user_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    assert ctx.client.patch('/api/users/9', json={'full_name': 'x'}).status_code == 404


def test_update_changes_only_the_fields_sent(ctx):
    target = user_row(id=2, username='ana', email='ana@example.com', full_name='Ana')
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=target)]
    r = ctx.client.patch('/api/users/2', json={'full_name': 'Ana María'})
    assert r.status_code == 200
    assert r.json()['full_name'] == 'Ana María'
    assert r.json()['email'] == 'ana@example.com'


def test_update_rejects_an_email_taken_by_someone_else(ctx):
    target = user_row(id=2, username='ana')
    ctx.db.execute.side_effect = [
        _result(scalar_one_or_none=target),
        _result(first=user_row(id=3, email='taken@example.com')),
    ]
    r = ctx.client.patch('/api/users/2', json={'email': 'taken@example.com'})
    assert r.status_code == 409


def test_cannot_deactivate_yourself(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=CURRENT)]
    r = ctx.client.patch('/api/users/1', json={'is_active': False})
    assert r.status_code == 409 and 'your own account' in r.json()['detail']


def test_cannot_deactivate_the_last_active_user(ctx):
    other = user_row(id=2, username='ana', email='ana@example.com')
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=other), _result(scalar=1)]
    r = ctx.client.patch('/api/users/2', json={'is_active': False})
    assert r.status_code == 409 and 'last active user' in r.json()['detail']


def test_can_deactivate_when_others_remain(ctx):
    other = user_row(id=2, username='ana', email='ana@example.com')
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=other), _result(scalar=2)]
    r = ctx.client.patch('/api/users/2', json={'is_active': False})
    assert r.status_code == 200 and r.json()['is_active'] is False


def test_reactivating_is_not_guarded(ctx):
    other = user_row(id=2, username='ana', email='ana@example.com', is_active=False)
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=other)]
    r = ctx.client.patch('/api/users/2', json={'is_active': True})
    assert r.status_code == 200 and r.json()['is_active'] is True


# --- password -----------------------------------------------------------------
def test_set_password_stores_a_hash(ctx):
    target = user_row(id=2, username='ana')
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=target)]
    r = ctx.client.post('/api/users/2/password', json={'password': 'brand-new-1'})
    assert r.status_code == 204
    assert passwords.verify_password('brand-new-1', target.password_hash)


def test_set_password_rejects_a_short_one(ctx):
    assert ctx.client.post('/api/users/2/password', json={'password': 'tiny'}).status_code == 422


def test_set_password_missing_user_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    assert ctx.client.post('/api/users/9/password', json={'password': 'brand-new-1'}).status_code == 404


# --- delete -------------------------------------------------------------------
def test_cannot_delete_yourself(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=CURRENT)]
    r = ctx.client.delete('/api/users/1')
    assert r.status_code == 409 and 'your own account' in r.json()['detail']


def test_cannot_delete_the_last_active_user(ctx):
    other = user_row(id=2, username='ana')
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=other), _result(scalar=1)]
    assert ctx.client.delete('/api/users/2').status_code == 409


def test_delete_user(ctx):
    other = user_row(id=2, username='ana')
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=other), _result(scalar=2)]
    assert ctx.client.delete('/api/users/2').status_code == 204
    ctx.db.delete.assert_awaited_once_with(other)


def test_delete_an_inactive_user_skips_the_active_count_guard(ctx):
    other = user_row(id=2, username='ana', is_active=False)
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=other)]
    assert ctx.client.delete('/api/users/2').status_code == 204


def test_delete_missing_user_404(ctx):
    ctx.db.execute.side_effect = [_result(scalar_one_or_none=None)]
    assert ctx.client.delete('/api/users/9').status_code == 404


def test_user_model_is_what_the_routes_return():
    assert 'password_hash' not in schemas.UserResponse.model_fields
    assert set(models.User.__table__.columns.keys()) - set(schemas.UserResponse.model_fields) == {'password_hash'}
